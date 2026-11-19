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

import ipaddress
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
    # 本机 / 局域网的 OpenAI 兼容服务通常不校验 Key。路由层用 is_local_url()
    # 决定是否放行；默认 False 保持云端「必须先配 Key」的旧行为。
    allow_no_key: bool = False

    def ensure_ready(self) -> None:
        scheme = urlparse(self.base_url.strip()).scheme
        if scheme not in ("http", "https"):
            raise AiError("Base URL 必须以 http:// 或 https:// 开头")
        if not self.model.strip():
            raise AiError("还没有填写模型名")
        if not self.api_key.strip() and not self.allow_no_key:
            raise AiError("还没有配置 API Key", status=401)


def is_local_url(base_url: str) -> bool:
    """这个地址是否指向本机 / 局域网（本地模型不需要 Key）。

    覆盖 LM Studio / Ollama / llama.cpp 常见的监听地址：loopback、RFC1918
    私网、链路本地、`.local` 与 Docker 的 host 别名。解析不出 host 的一律
    当作远程，让 401 的旧保护继续生效。
    """
    try:
        host = (urlparse((base_url or "").strip()).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in {"localhost", "host.docker.internal"} or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)


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
            "Accept": "application/json",
        },
    )
    # 这一行是唯一携带 key 的地方；不要把它复制到日志里。
    # 本地无 Key 服务连空 Authorization 都不发，避免个别网关把空 Bearer 当鉴权失败。
    if cfg.api_key.strip():
        request.add_header("Authorization", f"Bearer {cfg.api_key.strip()}")

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


_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_FENCE_RE = re.compile(r"```[A-Za-z0-9_+.-]*[ \t]*\r?\n?(.*?)```", re.DOTALL)
_SPECIAL_TOKEN_RE = re.compile(r"<\|[^|>]*\|>")
# 有些本地模型会把推理写进 `<think>` 后输出 JSON，但没有闭合标签。JSON 仍以 `{`
# 开始，所以兜底逻辑照常；这里只处理有闭合标签的常见情况，避免误删正文。


def _strip_reasoning(text: str) -> str:
    """剥掉 `qwen3` / `deepseek-r1` 一类模型外露的 `<think>…</think>`。"""
    cleaned = _THINK_RE.sub("", text)
    cleaned = _SPECIAL_TOKEN_RE.sub("", cleaned)
    return cleaned


def _strip_code_fences(text: str) -> str:
    """剥掉 Markdown ```json 围栏；支持围栏前后还有说明文字。"""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1)
    cleaned = re.sub(r"^\s*```[A-Za-z0-9_+.-]*[ \t]*", "", text)
    return re.sub(r"```\s*$", "", cleaned)


def json_from_text(text: str) -> dict:
    """从模型输出里取出 JSON 对象。

    真实模型经常包一层 ```json 围栏、外露 `<think>` 推理，或在前后加一句"好的"。
    这里依次剥掉围栏 / 推理块 / 特殊 token，再做一次 `{…}` 兜底；仍失败就抛
    AiError——**不做猜测性修复**，宁可让上层重试。
    """
    raw = _strip_code_fences(_strip_reasoning((text or "").strip().lstrip("\ufeff"))).strip()
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
        # 少数推理模型（Qwen3 / R1 一类）把最终答案也写进 reasoning_content，
        # content 留空。这里兜底读一次；如果里面没有 JSON，上层仍会重问/报错。
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            content = reasoning
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
    assistant_prefill: str = "",
) -> dict:
    """发一次对话请求并要求返回 JSON 对象。

    ``retries`` 只覆盖**传输层**失败（429 / 5xx / 网络）。JSON 结构不对属于内容问题，
    由调用方决定要不要重问（`core.ai_polish` 会带上更严格的提醒重试一次）。
    """
    cfg.ensure_ready()
    url = endpoint(cfg.base_url)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if assistant_prefill:
        # 本地 Qwen 一类推理模型在“自由生成”时会把答案全写进 reasoning_content，
        # content 为空；用 assistant 前缀把回复钉死在 JSON 上，模型会直接续写。
        messages.append({"role": "assistant", "content": assistant_prefill})
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
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

        # 兼容网关 / 本地推理服务对 response_format 的支持不一致：DeepSeek 只要求
        # prompt 里出现 json，LM Studio / llama.cpp / 部分网关直接 400/404/422。
        # 先去掉该字段重发一次，不占重试次数；若错误另有原因，下一次会如实上报。
        if (
            status in (400, 404, 422)
            and not plain_tried
            and "response_format" in payload
        ):
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

        content = _extract_content(body)
        if assistant_prefill and not content.lstrip().startswith(("{", "[")):
            content = assistant_prefill + content
        parsed = json_from_text(content)
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
