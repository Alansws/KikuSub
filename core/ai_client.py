"""OpenAI 兼容的 `chat/completions` 客户端（纯标准库，不引 SDK）。

为什么不用 `openai` 包：sidecar 是 PyInstaller 打包的，少一个依赖就少一份体积和
版本冲突；而我们要的能力只有一个 POST（见开发文档 §5.3.1）。

**安全约束（改这个文件前必须读）**

- `api_key` 只在一次请求的内存里出现，**绝不**写日志、绝不进异常文本、绝不落盘；
  落盘/解密由 Electron 的 `safeStorage` 负责（§5.2.1）。
- 日志只允许出现 host、model、状态码、耗时、prompt 长度。
- 错误详情最多回传 ``DETAIL_LIMIT`` 个字符，避免把整段 prompt 回显到界面上。
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# 回给界面的错误详情上限。模型服务 4xx 时常常把整段请求体回显出来，不能原样透传。
DETAIL_LIMIT = 300
# 重试等待（秒）。取消令牌在等待期间也能生效。
RETRY_BACKOFF = (1.0, 3.0)


class AiError(RuntimeError):
    """AI 调用失败。``retryable`` 表示"换一次可能就好"（429/5xx/网络）。"""

    def __init__(self, message: str, *, status: int = 0, retryable: bool = False, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.retryable = retryable
        self.detail = (detail or "")[:DETAIL_LIMIT]


@dataclass
class AiConfig:
    """一次调用需要的全部参数。key 用 ``repr=False`` 防止被顺手打进日志。"""

    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    timeout_s: float = 120.0

    def ensure_ready(self) -> None:
        scheme = urlparse(self.base_url.strip()).scheme
        if scheme not in ("http", "https"):
            raise AiError("Base URL 必须以 http:// 或 https:// 开头")
        if not self.model.strip():
            raise AiError("还没有填写模型名")
        if not self.api_key.strip():
            raise AiError("还没有配置 API Key", status=401)


def endpoint(base_url: str) -> str:
    """把「Base URL」补成完整的 chat/completions 地址。

    也接受用户直接粘贴完整端点，避免他们把 `/v1` 写重了。
    """
    url = (base_url or "").strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _host(base_url: str) -> str:
    try:
        return urlparse(base_url).netloc or "(未知)"
    except ValueError:
        return "(未知)"


# --------------------------------------------------------------------------- 传输


def _post(url: str, payload: dict, cfg: AiConfig) -> tuple[int, str]:
    """发一次请求，返回 (状态码, 响应文本)。网络错误统一转成 AiError。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            # 这一行是唯一携带 key 的地方；不要把它复制到日志里。
            "Authorization": f"Bearer {cfg.api_key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout_s) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - 读不到响应体不影响上报状态码
            detail = ""
        return exc.code, detail
    except urllib.error.URLError as exc:
        raise AiError(f"连不上模型服务：{getattr(exc, 'reason', exc)}", retryable=True) from exc
    except TimeoutError as exc:
        raise AiError("模型服务超时", retryable=True) from exc
    except OSError as exc:
        raise AiError(f"网络错误：{exc}", retryable=True) from exc


def _wait(seconds: float, cancel) -> None:
    if cancel is None:
        time.sleep(seconds)
        return
    # CancelToken 自带 wait：取消时立刻返回，不用睡满
    cancel.wait(seconds)


def _check_cancel(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise AiCancelled()


class AiCancelled(RuntimeError):
    """用户取消。与失败区分开：取消不写提案、不报错给用户。"""


# --------------------------------------------------------------------------- 解析


def json_from_text(text: str) -> dict:
    """从模型输出里取出 JSON 对象。

    真实模型经常包一层 ```json 围栏，或在前后加一句"好的"。这里做两级兜底，
    仍失败就抛 AiError——**不做猜测性修复**，宁可让上层重试。
    """
    raw = (text or "").strip().lstrip("\ufeff")
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise AiError("模型返回的内容不是 JSON")
        try:
            data = json.loads(raw[start : end + 1])
        except ValueError as exc:
            raise AiError("模型返回的内容不是 JSON") from exc
    if not isinstance(data, dict):
        raise AiError("模型应返回一个 JSON 对象")
    return data


def _extract_content(body: str) -> str:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise AiError("模型服务返回的不是 JSON", detail=body) from exc
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise AiError("模型服务没有返回 choices", detail=body)
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # 少数网关把内容拆成 parts
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        raise AiError("模型返回了空内容")
    return content


# --------------------------------------------------------------------------- 对外


def chat_json(
    cfg: AiConfig,
    system: str,
    user: str,
    *,
    cancel=None,
    retries: int = 2,
    temperature: float = 0.2,
) -> dict:
    """发一次对话请求并要求返回 JSON 对象。

    ``retries`` 只覆盖**传输层**失败（429 / 5xx / 网络）。JSON 结构不对属于内容问题，
    由调用方决定要不要重问（`core.ai_polish` 会带上更严格的提醒重试一次）。
    """
    cfg.ensure_ready()
    url = endpoint(cfg.base_url)
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    started = time.perf_counter()
    last: AiError | None = None
    plain_tried = False

    for attempt in range(retries + 1):
        _check_cancel(cancel)
        try:
            status, body = _post(url, payload, cfg)
        except AiError as exc:
            last = exc
            if not exc.retryable or attempt >= retries:
                raise
            _wait(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)], cancel)
            continue

        # 兼容网关对 response_format 的支持不一致（DeepSeek 只要求 prompt 里出现 json，
        # 也有网关直接 400）。**任何** 400 都先去掉该字段重发一次，不占重试次数：
        # 若 400 另有原因，下一次仍会 400，那时如实上报，不会掩盖真实错误。
        if status == 400 and not plain_tried and "response_format" in payload:
            plain_tried = True
            payload.pop("response_format", None)
            log.info(
                "首次请求被拒，已去掉 response_format 重试 | host=%s | %s",
                _host(cfg.base_url),
                (body or "").strip()[:120],
            )
            continue

        if status == 429 or status >= 500:
            last = AiError(
                f"模型服务暂时不可用（{status}）", status=status, retryable=True, detail=body
            )
            if attempt >= retries:
                raise last
            _wait(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)], cancel)
            continue

        if status >= 400:
            raise AiError(
                f"模型服务拒绝了请求（{status}）", status=status, detail=body
            )

        parsed = json_from_text(_extract_content(body))
        log.info(
            "AI 调用成功 | host=%s | model=%s | %.1fs | prompt=%d 字",
            _host(cfg.base_url),
            cfg.model,
            time.perf_counter() - started,
            len(system) + len(user),
        )
        return parsed

    raise last or AiError("AI 调用失败")


def test_connection(cfg: AiConfig) -> dict:
    """设置页的「测试连接」：一次最小往返，返回耗时供用户判断网络。"""
    started = time.perf_counter()
    chat_json(
        cfg,
        "You output JSON only.",
        '收到就只回这个 JSON，不要别的内容：{"ok": true}',
        retries=0,
    )
    return {
        "ok": True,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model": cfg.model,
        "host": _host(cfg.base_url),
    }
