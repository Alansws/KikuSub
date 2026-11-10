"""共享依赖：会话标识。

**为什么是请求头而不是 cookie**：渲染进程用 `file://` 加载（打包后），
对 `http://127.0.0.1` 的请求属于跨源，浏览器默认不发送 cookie
（`credentials: 'same-origin'`），会话就会每次新建一个——表现为「刚写入的字幕
下一次请求就没了」。所以改由客户端生成 id 并通过 `X-Kikusub-Session` 头带上。

cookie 仍然保留作为兜底：万一将来从 http:// 同源页面访问，两种方式都能用。
"""

from __future__ import annotations

from fastapi import Request, Response

from .sessions import Session, SessionStore

SESSION_COOKIE = "kikusub_sid"
SESSION_HEADER = "x-kikusub-session"
SESSION_HEADER = "x-kikusub-session"


def session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_session(request: Request, response: Response) -> Session:
    store = session_store(request)
    sid = (request.headers.get(SESSION_HEADER) or "").strip() or request.cookies.get(SESSION_COOKIE)
    session = store.get(sid)
    if sid != session.id:
        response.set_cookie(
            SESSION_COOKIE,
            session.id,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return session
