"""一次性 token 鉴权。

两种取 token 的方式：

1. `Authorization: Bearer <token>` —— 前端 fetch 走这条（XHR 能带自定义头）。
2. `?token=<token>` —— 只给 `/media/*` 用。<video src> 由浏览器内核直接发起请求，
   发不了自定义头，这是唯一的办法。

失败统一 401，不区分「没带」和「带错了」，避免给探测者额外信息。
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

TOKEN_QUERY_PARAM = "token"


def _candidate_tokens(request: Request) -> list[str]:
    values: list[str] = []
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        values.append(header[7:].strip())
    query_token = request.query_params.get(TOKEN_QUERY_PARAM)
    if query_token:
        values.append(query_token.strip())
    return values


def token_ok(request: Request) -> bool:
    expected = getattr(request.app.state, "token", "")
    if not expected:
        return False
    return any(
        hmac.compare_digest(candidate, expected) for candidate in _candidate_tokens(request)
    )


def require_token(request: Request) -> None:
    """FastAPI 依赖：所有 `/api/*` 路由挂这个。"""
    if not token_ok(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing token",
        )
