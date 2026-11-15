"""字幕交付文件命名与引擎标签识别（纯函数，无 torch / 无 UI 依赖）。

文件名是用户唯一能看到的「版本身份」，所以这里集中三件事：

1. **原始转写与交付稿共用一套引擎标签**：标签只在 `core/engines.py` 登记
   （`file_tag`），本模块不再维护第二份 key 白名单（AGENTS.md 红线 #12）。
2. **交付稿带 `.reviewed`**：`{stem}.{version}.reviewed{track_suffix}{ext}`。
   不加 `.reviewed` 时，Qwen 的交付稿会正好覆盖 Qwen 的原始转写
   `{stem}.Qwen3-ASR.srt`——那正是用户报障的「换引擎后前一版没了」。
3. **从文件名反推引擎**：导入旧稿时既认新标签（`.AnimeWhisper` /
   `.Qwen3-ASR`），也认历史标签（`.whisper` / `.qwen` 等）；而且必须先剥掉
   媒体主干名，避免影片名本身带 `whisper` 关键字时误判。
"""

from __future__ import annotations

from pathlib import Path

from . import engines

REVIEWED = "reviewed"


def engine_from_filename(name: str, media_stem: str = "") -> str:
    """从字幕文件名反推引擎 key；识别不出返回空串。

    只认**点分标签**：`episode.AnimeWhisper.reviewed.srt` 里的 `AnimeWhisper`
    算标签，`episode_AnimeWhisper_notes.srt` 里的不算——后者更可能是用户随手起的
    文件名，误判成引擎会让交付稿挂错版本。
    """
    raw = Path(str(name or "")).name
    stem = Path(raw).stem if raw else ""
    lowered = stem.lower()
    media = str(media_stem or "").strip().lower()
    if media:
        if lowered == media:
            return ""
        for sep in (".", "_", "-", " "):
            prefix = media + sep
            if lowered.startswith(prefix):
                stem = stem[len(prefix):]
                break
    tokens = [token.strip().lower() for token in stem.split(".") if token.strip()]
    for token in reversed(tokens):
        for spec in engines.ENGINES:
            if token in {tag.lower() for tag in engines.filename_tags(spec)}:
                return spec.key
    return ""


def review_version(source: dict | None, *, media_stem: str = "") -> str:
    """交付稿的版本标签：优先会话来源的引擎，其次从来源文件名推断，最后按来源类型。

    返回的是**文件名标签**（`AnimeWhisper` / `Qwen3-ASR` / `import` / `draft`），
    不是内部 key；调用方不要再拼一次。
    """
    src = dict(source or {})
    key = str(src.get("engine") or "").strip().lower()
    tag = engines.file_tag_of(key)
    if tag:
        return tag
    inferred = engine_from_filename(str(src.get("name") or ""), media_stem)
    if inferred:
        return engines.file_tag_of(inferred)
    kind = str(src.get("kind") or "").strip().lower()
    if kind in {"import", "draft"}:
        return kind
    return ""


def reviewed_filename(
    stem: str,
    source: dict | None,
    *,
    track_suffix: str = "",
    ext: str = ".srt",
    media_stem: str = "",
) -> str:
    """核对后交付文件名：`{stem}.{version}.reviewed{track_suffix}{ext}`。

    `track_suffix` 仍由调用方给（`.zh-Hans` / `.bilingual`）；`version` 为空时
    退化成 `{stem}.reviewed...`，仍然不会和原始转写撞名。
    """
    parts = [str(stem or "subtitles")]
    version = review_version(source, media_stem=media_stem or stem)
    if version:
        parts.append(version)
    parts.append(REVIEWED)
    return ".".join(parts) + str(track_suffix or "") + str(ext or "")
