"""本地 LM Studio 的模型上下文档位与加载/重载。

只服务「单句判定」的本地模型覆盖：前端点「加载 / 重载本地模型」时，先按
LM Studio REST v1 卸载该模型的已加载实例，再以指定 ``context_length`` 重新加载。
**绝不在每次单句判定请求里重载模型**——27B 的加载要数秒并吃满内存。

约束：
- 只接受 loopback 地址（127.0.0.1 / localhost / ::1）；远程 API 或局域网服务
  不执行任何加载操作，返回可读错误。
- 只认 LM Studio 的 ``/api/v1/models``；普通 OpenAI 兼容服务返回 404 时视为
  「不是 LM Studio」，不做任何猜测。
- 不依赖 FastAPI，``ai_client`` 仍然只负责 OpenAI 兼容的 chat/completions。
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request

CONTEXT_CHOICES = (2048, 4096, 8192)
DEFAULT_CONTEXT = 2048


class LocalModelError(RuntimeError):
    """本地模型加载失败；消息可直接展示给用户（不包含密钥/大段响应）。"""


def _root(base_url: str) -> str:
    parsed = urllib.parse.urlparse((base_url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise LocalModelError("Base URL 必须以 http:// 或 https:// 开头")
    return f"{parsed.scheme}://{parsed.netloc}"


def is_loopback(base_url: str) -> bool:
    """只有本机 LM Studio 才允许被 KikuSub 重载。"""
    try:
        host = (urllib.parse.urlparse((base_url or "").strip()).hostname or "").lower()
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _request_json(
    method: str, url: str, payload: dict | None = None, timeout: float = 5.0
) -> dict:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - 读不到响应体不影响状态码
            detail = ""
        detail = detail.strip().replace("\n", " ")[:240]
        raise LocalModelError(f"LM Studio 返回 {exc.code}{('：' + detail) if detail else ''}") from exc
    except urllib.error.URLError as exc:
        raise LocalModelError(f"连不上 LM Studio：{getattr(exc, 'reason', exc)}") from exc
    except TimeoutError as exc:
        raise LocalModelError("LM Studio 响应超时") from exc
    except OSError as exc:
        raise LocalModelError(f"LM Studio 网络错误：{exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise LocalModelError("LM Studio 返回的不是 JSON") from exc
    if not isinstance(data, dict):
        raise LocalModelError("LM Studio 返回格式不正确")
    return data


def _models(base_url: str, timeout: float = 4.0) -> list[dict]:
    data = _request_json("GET", f"{_root(base_url)}/api/v1/models", timeout=timeout)
    rows = data.get("models")
    if not isinstance(rows, list):
        raise LocalModelError("这个地址不是 LM Studio（缺少 models 列表）")
    return [row for row in rows if isinstance(row, dict)]


def _find_model(rows: list[dict], model: str) -> dict | None:
    wanted = (model or "").strip()
    for row in rows:
        if str(row.get("key") or "") == wanted or str(row.get("id") or "") == wanted:
            return row
    return None


def _loaded_context(row: dict) -> tuple[bool, int | None]:
    instances = row.get("loaded_instances")
    if not isinstance(instances, list) or not instances:
        return False, None
    for instance in instances:
        if not isinstance(instance, dict):
            continue
        config = instance.get("config")
        if isinstance(config, dict):
            value = config.get("context_length")
            if isinstance(value, int) and not isinstance(value, bool):
                return True, value
    return True, None


def status(base_url: str, model: str) -> dict:
    """只读探测：是否 LM Studio、模型是否已加载、当前 context。"""
    if not is_loopback(base_url):
        return {"available": False, "reason": "not_local"}
    try:
        rows = _models(base_url)
    except LocalModelError as exc:
        return {"available": False, "reason": "not_lmstudio", "error": exc.args[0]}
    row = _find_model(rows, model)
    if row is None:
        return {
            "available": False,
            "reason": "model_missing",
            "error": f"LM Studio 里没有模型 {model or '(未填写)'}",
        }
    loaded, context_length = _loaded_context(row)
    max_context = row.get("max_context_length")
    return {
        "available": True,
        "loopback": True,
        "model": str(row.get("key") or model),
        "loaded": loaded,
        "context_length": context_length,
        "max_context_length": max_context if isinstance(max_context, int) else None,
    }


def load(base_url: str, model: str, context: int) -> dict:
    """卸载并重载本地模型到指定 context；已在该档位且已加载时直接返回。"""
    if context not in CONTEXT_CHOICES:
        raise LocalModelError(f"上下文档位只能是 {', '.join(map(str, CONTEXT_CHOICES))}")
    if not is_loopback(base_url):
        raise LocalModelError("只有本机 LM Studio 支持重载模型；远程地址不会执行该操作")
    rows = _models(base_url)

    row = _find_model(rows, model)
    if row is None:
        raise LocalModelError(f"LM Studio 里没有模型 {model or '(未填写)'}")
    loaded, current = _loaded_context(row)
    if loaded and current == context:
        return {
            "ok": True,
            "reloaded": False,
            "model": str(row.get("key") or model),
            "context_length": context,
        }

    instances = row.get("loaded_instances")
    if isinstance(instances, list):
        for instance in instances:
            if not isinstance(instance, dict):
                continue
            instance_id = str(instance.get("id") or "").strip()
            if not instance_id:
                continue
            _request_json(
                "POST",
                f"{_root(base_url)}/api/v1/models/unload",
                {"instance_id": instance_id},
                timeout=30.0,
            )

    response = _request_json(
        "POST",
        f"{_root(base_url)}/api/v1/models/load",
        {"model": model.strip(), "context_length": context},
        timeout=180.0,
    )
    if response.get("error"):
        error = response.get("error")
        message = ""
        if isinstance(error, dict):
            message = str(error.get("message") or "")
        raise LocalModelError(message or "LM Studio 加载模型失败")

    after = status(base_url, model)
    if after.get("available") and after.get("context_length") not in (None, context):
        raise LocalModelError(
            f"模型已加载，但 LM Studio 报告的 context 是 {after.get('context_length')}，不是 {context}"
        )
    load_time = response.get("load_time_seconds")
    return {
        "ok": True,
        "reloaded": True,
        "model": str(row.get("key") or model),
        "context_length": context,
        "load_time_seconds": load_time if isinstance(load_time, (int, float)) else None,
    }
