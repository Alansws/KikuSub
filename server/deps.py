"""共享依赖：会话 cookie。

`session_id` 走 cookie 而不是请求头，原因是前端有多个独立的 fetch 调用点
（字幕表、波形、质检队列），让每个调用都带一个 id 头容易漏；cookie 由浏览器自动携带。
"""

from __future__ import annotations

from fastapi import Request, Response

from .sessions import Session, SessionStore

SESSION_COOKIE = "kikusub_sid"


def session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_session(request: Request, response: Response) -> Session:
    store = session_store(request)
    sid = request.cookies.get(SESSION_COOKIE)
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
