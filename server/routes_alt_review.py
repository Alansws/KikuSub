"""第二版本（双引擎复核）路由。

第二版是**参考文档**：读取、删除、整列替换核对台。2026-11-21（界面重构 Step 2）
起复核页多了「单句采用 B」的页内闭环，但它**没有**在本模块新增写接口：前端只是
把 B 那一行的文本走 ``PATCH /api/cues/{index}``（带 ``label``）写回核对台，因此
仍然是一步统一历史、⌘Z 一次撤回，也不会出现「两套可编辑字幕」。断句与时间戳
不做合并——采纳只换文本，时间轴保持核对台当前值。

四个接口：

- ``GET /api/alt-review``：第二版摘要 + 全量 cues；``diff=1`` 时附上按当前两份
  字幕**实时计算**的对齐行与统计（``core.dual_review``，不持久化下标）。
  ``ignore_punct``（默认 ``1``）只把「标点 / 空白不同」判为一致，不计入差异数。
- ``POST /api/alt-review/import``：把工作流里已经做好的另一版字幕直接导入第二列
  （与转写产出的 B 版同构：同一份 ``AltReview``、同一份边车、同样的 diff/润色链路）。
- ``DELETE /api/alt-review``：丢弃第二版，同时删内存与磁盘边车。
- ``POST /api/alt-review/replace-primary``：整列用 B 覆盖核对台，走统一历史
  （一次 ⌘Z 全退），默认覆盖成功后清掉第二版（避免两列完全相同仍占徽标）。
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import dual_review, dual_scope, export_naming
from core.cues import _unique_sorted_cues
from core.subtitles import cues_from_subtitle_file

from .deps import get_session, media_path as _media_path
from .routes_cues import _BILINGUAL_FILE_RE, _snapshot
from .security import require_token
from .sessions import AltReview, Session

router = APIRouter(tags=["alt-review"], dependencies=[Depends(require_token)])


class ImportAltRequest(BaseModel):
    """按路径导入一份已有字幕作为第二版（与媒体/字幕导入同一约定）。"""

    path: str = Field(min_length=1, max_length=4096)


class ReplacePrimaryRequest(BaseModel):
    # 覆盖成功后默认清空第二版（Q11）；想保留对照可显式传 false。
    clear_alt: bool = True
    # 2026-11-26：``auto``（默认）= 给了 start/end 就按范围替换，否则整列覆盖；
    # ``range`` = 只替换窗口内的核对台字幕（安全口径，界面默认）；
    # ``all`` = 整列覆盖。``auto`` 只为兼容不带范围的老客户端。
    # **B 只覆盖了局部时整列覆盖会被 :func:`dual_scope.would_trim` 拦下**，
    # 需要 ``confirm_trim=True`` 才放行——这就是「绝不允许误操作清空第 1、2 章」。
    mode: str = Field(default="auto", pattern="^(auto|range|all)$")
    start: float | None = None
    end: float | None = None
    confirm_trim: bool = False


def _output_dir(request: Request) -> Path:
    return Path(request.app.state.config.output_dir)


def _mode_of(payload: ReplacePrimaryRequest) -> str:
    """``auto`` 的落地口径：给了完整窗口就按范围替换，否则整列覆盖。

    老客户端（转写 1.0.1 的渲染层）只发 ``{}`` 或 ``{"clear_alt": …}``，
    它期待的是整列覆盖——``auto`` 因此退化成 ``all``，但**仍要过
    :func:`dual_scope.would_trim` 那道闸**：B 是局部稿时旧按钮只会拿到 409，
    绝不会静默丢掉前几章。
    """
    if payload.mode != "auto":
        return payload.mode
    if payload.start is not None and payload.end is not None:
        return "range"
    return "all"


def _ensure_synced(request: Request, session: Session) -> str:
    path = _media_path(request, session)
    if path:
        session.sync_alt_review(media_path=path, output_dir=_output_dir(request))
    return path


def _cues_payload(alt: AltReview) -> list[dict]:
    return [{"start": cue.start, "end": cue.end, "text": cue.text} for cue in alt.cues]


def _focus_payload(request: Request, session: Session, alt: AltReview | None, scope: str) -> dict:
    """把范围解析成一份可直接渲染的 payload（含每项条数与默认口径）。

    章节来自 ``session.chapters``（与章节页签同一份数据）；``duration`` 只用于
    A 为空时的兜底跨度。
    """
    duration = 0.0
    if session.media_id:
        try:
            info = request.app.state.media.get(session.media_id)
            duration = float(getattr(info, "duration", 0.0) or 0.0)
        except Exception:  # noqa: BLE001 - 拿不到片长不影响范围解析
            duration = 0.0
    a_cues = list(session.review_cues)
    b_cues = list(alt.cues) if alt is not None else []
    marks = list(getattr(session, "chapters", []) or [])
    options = dual_scope.scope_options(a_cues, b_cues, marks, duration)
    focus = dual_scope.resolve_focus(scope, a_cues, b_cues, marks, duration)
    auto = str(scope or "").strip() in {"", "auto"}
    hidden_a, hidden_b = dual_scope.hidden_counts(a_cues, b_cues, focus)
    trim = dual_scope.would_trim(a_cues, b_cues)
    # 可以对 B 执行「替换当前范围」的条件：B 在窗口内确有句子，且窗口不是全片
    # （全片 = 整列覆盖，走 mode=all，两件事的语义不能混）。
    in_b, _ = dual_scope.cues_in_window(b_cues, focus["start"], focus["end"])
    partial = dual_scope.is_partial_b(a_cues, b_cues)
    return {
        **focus,
        "auto": auto,
        # 「B 所在区间」是不是局部产物：决定按钮默认文案与二次确认的口径
        "partial_b": partial,
        "options": options,
        "hidden_a": hidden_a,
        "hidden_b": hidden_b,
        # 整列覆盖会丢多少条 A：0 = 安全，>0 必须显式确认
        "would_trim": trim,
        # 默认写回方式：范围可替换 → range；否则（B 盖住整片）→ all
        "replace_mode": "range" if in_b and (partial or focus["key"] != dual_scope.ALL_KEY) else "all",
        "replace_count": len(in_b),
    }


def _review_payload(
    session: Session,
    alt: AltReview,
    focus: dict,
    *,
    diff: bool,
    ignore_punct: bool,
) -> dict:
    """按范围切片对齐，下标仍指回整份字幕（见 ``core.dual_review`` 的 a_map）。"""
    a_all = list(session.review_cues)
    b_all = list(alt.cues)
    a_cues, a_map = dual_scope.cues_in_window(a_all, focus["start"], focus["end"])
    b_cues, b_map = dual_scope.cues_in_window(b_all, focus["start"], focus["end"])
    review = dual_review.build_review(
        a_cues,
        b_cues,
        ignore_punct=ignore_punct,
        a_map=a_map,
        b_map=b_map,
    )
    return review


@router.post("/api/alt-review/import")
def import_alt_review(
    payload: ImportAltRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """把一份已经导出的 SRT / VTT 作为第二版字幕导入。

    与「转写结果放进第二列」写的是同一个 ``AltReview``：
    边车落盘、切媒体恢复、实时 diff、双源润色、断句重排参考、整列覆盖全部复用。
    核对台一个字都不动，也不进 50 步历史。
    """
    path = Path(payload.path).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"文件不存在：{payload.path}") from exc
    if path.suffix.lower() not in {".srt", ".vtt"}:
        raise HTTPException(status_code=422, detail=f"只支持 .srt / .vtt：{path.suffix}")
    if _BILINGUAL_FILE_RE.search(path.name):
        raise HTTPException(
            status_code=422,
            detail="第二版要比对原文轨：双语交付文件（.bilingual）请先在核对台导入并按语言拆分",
        )

    media_path = _ensure_synced(request, session)
    if not media_path:
        raise HTTPException(
            status_code=409,
            detail="第二版按影片身份保存：请先在「导入」页打开影片，再导入这份字幕",
        )

    try:
        cues = cues_from_subtitle_file(path)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"读取失败：{exc}") from exc
    if not cues:
        raise HTTPException(status_code=422, detail="没有从该文件里解析出字幕")

    cues = _unique_sorted_cues(cues)
    engine = export_naming.engine_from_filename(path.name, Path(media_path).stem)
    source = {
        "kind": "import",
        "engine": engine,
        "name": path.name,
        "path": str(path),
        "job_id": "",
        "at": time.time(),
        "apply": "alt_review",
    }
    alt = session.set_alt_review(
        engine=engine,
        cues=cues,
        source=source,
        params={},
        media_path=media_path,
        output_dir=_output_dir(request),
    )
    return {
        "exists": True,
        "engine": alt.engine,
        "count": len(alt.cues),
        "source": dict(alt.source),
        "created_at": alt.created_at,
        "warning": _duration_warning(request, session, alt.cues),
    }


def _duration_warning(request: Request, session: Session, cues) -> str:
    """时间码明显超出影片时长时给一句提醒；不阻断导入（可能只是长版/加长片）。"""
    if not session.media_id:
        return ""
    try:
        info = request.app.state.media.get(session.media_id)
    except Exception:
        return ""
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    if duration <= 0:
        return ""
    beyond = sum(1 for cue in cues if float(cue.start) > duration + 1.0)
    if not beyond:
        return ""
    return (
        f"有 {beyond} 条字幕的时间码超出当前影片时长（{duration:.1f}s），"
        "确认这份字幕是对应本片的吗？"
    )


@router.get("/api/alt-review")
def get_alt_review(
    request: Request,
    diff: bool = False,
    ignore_punct: bool = True,
    scope: str = "",
    session: Session = Depends(get_session),
) -> dict:
    """第二版摘要 + 全量 cues + 当前对照范围的对齐结果。

    ``scope``（2026-11-26）：``auto`` / 空 = 智能默认（B 只覆盖一段就聚焦那一段）；
    ``all`` = 全片；``ch:<id>`` = 某段区间章节；``b`` = B 自己的跨度。
    范围只影响**对齐、统计与徽标**，``cues`` 永远是整份 B（切范围不必重拉）。
    """
    _ensure_synced(request, session)
    alt = session.alt_review
    if alt is None:
        return {
            "exists": False,
            "engine": "",
            "count": 0,
            "source": {},
            "created_at": 0,
            "cues": [],
            "stats": None,
            "rows": [],
            "scope": None,
        }
    data = session.alt_review_summary()
    data["cues"] = _cues_payload(alt)
    data["media_path"] = alt.media_path
    data["params"] = dict(alt.params)
    # 2026-11-21（Step 2）：``ignore_punct`` 默认开——只有标点 / 空白不同的行
    # 判为一致，不计入 ``~ 文本不同`` 与侧栏徽标；``?ignore_punct=0`` 回到严格比对。
    # 2026-11-26：对齐先按对照范围切片。统计与徽标只算当前范围，
    # 不再拿范围外的章节凑出几百个假差异。
    focus = _focus_payload(request, session, alt, scope)
    review = _review_payload(
        session, alt, focus, diff=diff, ignore_punct=ignore_punct
    )
    data["stats"] = review["stats"]
    data["ignore_punct"] = bool(ignore_punct)
    data["scope"] = focus
    # 整份 A / B 的条数：页头「A 636 条 / B 220 条」与范围口径分开显示，避免混读。
    data["total_a"] = len(session.review_cues)
    data["total_b"] = len(alt.cues)
    # diff 模式返回当前范围的全量行；否则只要统计（O(n)，不返回 rows，省传输）。
    data["rows"] = review["rows"] if diff else []
    return data


@router.delete("/api/alt-review")
def delete_alt_review(request: Request, session: Session = Depends(get_session)) -> dict:
    path = _ensure_synced(request, session)
    removed = session.clear_alt_review(
        media_path=path,
        output_dir=_output_dir(request),
        remove_cache=True,
    )
    return {"removed": removed, "exists": False}


@router.post("/api/alt-review/replace-primary")
def replace_primary(
    payload: ReplacePrimaryRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """用第二版写回核对台：**默认只替换当前范围**，整列覆盖必须显式确认。

    2026-11-26 真机报障：A 累积了第 1–3 章 636 条、B 只有第 3 章 220 条，
    旧接口只有一个「整列覆盖」——按下去就把前两章一起丢了。现在的口径：

    - ``mode="range"``（默认）：只换 ``[start, end)`` 窗口内的 A，
      窗口外一条不动（纯函数 ``core.dual_scope.replace_window``），
      仍然只压一步历史、⌘Z 一次整批退回；
    - ``mode="all"``：整列覆盖（B 是整片第二版时的正常口径）。
      B 只覆盖了局部（``would_trim > 0``）时必须带 ``confirm_trim=True``，
      否则 409 —— 这道闸门是「绝不允许误操作清空第 1、2 章」的最后防线。
    """
    path = _ensure_synced(request, session)
    alt = session.alt_review
    if alt is None or not alt.cues:
        raise HTTPException(status_code=409, detail="还没有第二版字幕")
    source = dict(alt.source)
    # 导入稿的来源必须原样保留（kind=import + 原文件名）：
    # 如果强行改写成 transcription，覆盖后检查器会去找一份不存在的转写报告，
    # ⌘Z 退回去时来源也会错位。转写生成的 B 版才标记成 transcription。
    if source.get("kind") != "import":
        source["kind"] = "transcription"
        source["engine"] = alt.engine or source.get("engine", "")
    source["apply"] = "replace" if _mode_of(payload) == "all" else "replace_range"
    source["at"] = source.get("at") or alt.created_at

    mode = _mode_of(payload)
    if mode == "range":
        if payload.start is None or payload.end is None:
            raise HTTPException(
                status_code=422,
                detail="范围替换需要 start / end：只想换一段就别做整列覆盖",
            )
        if float(payload.end) <= float(payload.start):
            raise HTTPException(status_code=422, detail="范围终点必须大于起点")
        merged, removed, inserted = dual_scope.replace_window(
            session.review_cues, alt.cues, payload.start, payload.end
        )
        if inserted <= 0:
            raise HTTPException(
                status_code=422,
                detail="这个范围里没有第二版的字幕：换个范围，或改用整列覆盖",
            )
        label = (
            f"用第二版替换 {dual_scope.format_clock(payload.start)}–"
            f"{dual_scope.format_clock(payload.end)}"
            f"（{inserted} 条，替换掉 {removed} 条）"
        )
        # keep_translations：范围外条目的译文按位置搬移，新条目留空待译。
        # 这正是「替换选区」在核对台的既有语义（见 Session.replace_review）。
        session.replace_review(
            merged,
            label=label,
            source=source,
            keep_translations=True,
        )
        if payload.clear_alt:
            # 范围替换后 B 的其余区间仍然有用（还有别的章节要对照），
            # 默认保留；只有整列覆盖才清空。
            pass
        return {
            **_snapshot(session),
            "replaced": inserted,
            "removed": removed,
            "mode": "range",
            "alt_cleared": False,
        }

    trim = dual_scope.would_trim(session.review_cues, alt.cues)
    if trim > 0 and not payload.confirm_trim:
        raise HTTPException(
            status_code=409,
            detail=(
                f"第二版只覆盖了部分时间区间：整列覆盖会丢掉范围外的 {trim} 条字幕。"
                "请改用「用 B 替换当前范围」，或显式确认整列覆盖"
            ),
        )
    label = (
        "整列采用导入的第二版" if source.get("kind") == "import" else "整列采用第二引擎稿"
    )
    session.replace_review(
        alt.copy().cues,
        label=f"{label}（{len(alt.cues)} 条）",
        source=source,
    )
    if payload.clear_alt:
        session.clear_alt_review(
            media_path=path,
            output_dir=_output_dir(request),
            remove_cache=True,
        )
    return {
        **_snapshot(session),
        "replaced": len(alt.cues),
        "removed": trim,
        "mode": "all",
        "alt_cleared": bool(payload.clear_alt),
    }
