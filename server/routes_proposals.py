"""提案状态：让运行中的界面发现「外部 Agent 刚提交了一份提案」。

为什么需要单独的轻量接口：轮询如果每次都拉整份提案（长片 1000+ 条、几百 KB），
两秒一次会把 sidecar 和渲染进程都拖慢。这里只 stat 文件，返回 kind/lang/路径/
mtime/大小；界面据此判断「有没有变」，变了才去拉正文。

覆盖四类落盘提案（断句重排的整份新稿也落盘，见 routes_reshape）：

- `{stem}.ai-polish.json`            润色
- `{stem}.{lang}.ai-translate.json`  翻译（可能多语种并存）
- `{stem}.ai-structure.json`         结构建议（ops）
- `{stem}.ai-reshape.json`           断句重排（整份新稿）
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from core import ai_proposal, ai_structure, reshape

from .deps import get_session
from .routes_cues import _media_stem
from .security import require_token

router = APIRouter(tags=["proposals"], dependencies=[Depends(require_token)])


def _entry(kind: str, path: Path, lang: str = "") -> dict | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return {
        "kind": kind,
        "lang": lang,
        "path": str(path),
        "name": path.name,
        "mtime": round(stat.st_mtime, 3),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def _collect(output_dir: Path, stem: str) -> list[dict]:
    base = str(stem or "").strip() or "subtitles"
    items: list[dict] = []
    polish = _entry("polish", ai_proposal.proposal_path(output_dir, base, "polish"))
    if polish:
        items.append(polish)
    for path in sorted(output_dir.glob(f"{base}.*.ai-translate.json")):
        lang = path.name[len(base) + 1 : -len(".ai-translate.json")]
        entry = _entry("translate", path, lang)
        if entry:
            items.append(entry)
    structure = _entry("structure", ai_structure.structure_path(output_dir, base))
    if structure:
        items.append(structure)
    reshaped = _entry("reshape", reshape.proposal_path(output_dir, base))
    if reshaped:
        items.append(reshaped)
    return items


@router.get("/api/proposals/status")
def proposals_status(request: Request, session=Depends(get_session)) -> dict:
    """四类提案文件的存在性与版本；没有绑定媒体时返回空表（不是错误）。"""
    output_dir = Path(getattr(request.app.state.config, "output_dir", "."))
    stem = _media_stem(request, session)
    items = _collect(output_dir, stem) if stem else []
    fingerprint = "|".join(
        f"{item['kind']}:{item['lang']}:{item['mtime_ns']}:{item['size']}" for item in items
    )
    return {
        "media_stem": stem,
        "items": items,
        "revision": hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16],
    }
