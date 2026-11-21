"""共享依赖：会话标识。

**为什么是请求头而不是 cookie**：渲染进程用 `file://` 加载（打包后），
对 `http://127.0.0.1` 的请求属于跨源，浏览器默认不发送 cookie
（`credentials: 'same-origin'`），会话就会每次新建一个——表现为「刚写入的字幕
下一次请求就没了」。所以改由客户端生成 id 并通过 `X-Kikusub-Session` 头带上。

cookie 仍然保留作为兜底：万一将来从 http:// 同源页面访问，两种方式都能用。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request, Response

from core import settings as settings_store

from .sessions import Session, SessionStore

SESSION_COOKIE = "kikusub_sid"
SESSION_HEADER = "x-kikusub-session"


def session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_session(request: Request, response: Response) -> Session:
    store = session_store(request)
    sid = (request.headers.get(SESSION_HEADER) or "").strip() or request.cookies.get(SESSION_COOKIE)
    session = store.get(sid)
    # 只有「客户端带着已有 id 回来」才算 App 的活跃会话；CLI 新建的空会话不能抢注，
    # 否则下一次 CLI 会读到空工程而不是界面上正在编辑的字幕。
    if sid and sid == session.id:
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is not None:
            runtime.note_session(session.id)
    if sid != session.id:
        response.set_cookie(
            SESSION_COOKIE,
            session.id,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return session


def media_path(request: Request, session: Session) -> str:
    """当前会话绑定的媒体绝对路径；没绑定/已被移走时返回空串。

    证据接口、第二版同步、导出提示都要同一个口径，避免各路由各写一份。
    """
    if session.media_id:
        try:
            return str(request.app.state.media.get(session.media_id).path)
        except Exception:  # noqa: BLE001 - 媒体被移走时退回 session.media_path
            pass
    return str(session.media_path or "")


def settings_path(request: Request) -> Path:
    """settings.json 的实际路径：优先取测试/嵌入方注入的 `app.state.settings_path`。

    原先 `routes_ai` / `routes_settings` / `routes_export` 各自复制了一份同名函数，
    三份实现必须永远一致（见 docs/contracts/engineering-practice.md「重复实现」）。
    """
    return Path(getattr(request.app.state, "settings_path", settings_store.SETTINGS_PATH))
