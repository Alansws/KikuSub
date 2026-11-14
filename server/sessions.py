"""会话状态：替代 Gradio 的 `gr.State`。

旧实现把四份状态放在 `gr.State` 里（转写结果 / 核对基线 / 撤销栈 / 重做栈），
只能被 Gradio 的会话机制持有。新架构改成 **`session_id` cookie + 进程内字典**，
沿用规划 §4 的结论：服务端仍是唯一真源，前端撤销栈只做乐观回显。

一个会话同一时间只服务一个媒体文件（和桌面端「一次核对一部片」的用法一致）。
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from core.subtitles import SubtitleCue
from core.textio import write_text_atomic

# 可回溯历史：最多保留 50 步**操作**（另加一条「起始状态」）。
# 统一历史把字幕、译文、质检、导出设置与 AI 草稿都算进来，20 步会显得很短。
HISTORY_LIMIT = 50
# 兼容旧名字：曾经叫 UNDO_LIMIT，语义相同。
UNDO_LIMIT = HISTORY_LIMIT
# 同一类连续调整（拖动字号滑杆 / 同一行 AI 建议反复改）在这个窗口内合并成一步。
COALESCE_SECONDS = 1.2
# 会话空闲多久回收（秒）。桌面端通常只有一个会话，这里防的是频繁开关窗口。
SESSION_TTL_S = 12 * 3600


def _copy(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    return [SubtitleCue(start=c.start, end=c.end, text=c.text) for c in cues]


def _copy_tracks(tracks: dict[str, "TranslationTrack"]) -> dict[str, "TranslationTrack"]:
    """译文轨快照：结构性编辑与撤销必须一起回滚，否则时间轴与译文会错位。"""
    return {lang: track.copy() for lang, track in tracks.items()}


def _join_cue_texts(parts: list[str]) -> str:
    """合并字幕时拼文本：日文/中文直接相连，两侧都是西文单词时才补一个空格。"""
    out = ""
    for raw in parts:
        text = str(raw or "").strip()
        if not text:
            continue
        if not out:
            out = text
            continue
        prev, nxt = out[-1], text[0]
        if prev.isascii() and prev.isalnum() and nxt.isascii() and nxt.isalnum():
            out += " " + text
        else:
            out += text
    return out


# 每个语种独立保留多少步"上一次的译文"。译文不走 review_cues 的撤销栈（D-3），
# 否则改一句原文会把整条时间轴的撤销历史搅乱。
TRACK_UNDO_LIMIT = 20


@dataclass
class TranslationTrack:
    """一个语种的译文轨：与 review_cues **逐条对齐**。

    ``base`` 是生成时的原文快照，用来算"哪几条译文已经过期"（`core.i18n.stale_indices`）。
    结构性编辑（插入 / 删除 / 切割 / 合并）必须同步搬动轨里对应位置的条目，
    否则删一句原文就会让后面所有译文整体错位一条。
    """

    lang: str
    texts: list[str]
    base: list[str]
    created_at: float = field(default_factory=time.time)
    entry: str = "in-app"

    def copy(self) -> "TranslationTrack":
        return TranslationTrack(
            lang=self.lang,
            texts=list(self.texts),
            base=list(self.base),
            created_at=self.created_at,
            entry=self.entry,
        )

    def to_dict(self) -> dict:
        return {
            "lang": self.lang,
            "texts": list(self.texts),
            "base": list(self.base),
            "created_at": self.created_at,
            "entry": self.entry,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranslationTrack":
        return cls(
            lang=str(data.get("lang") or ""),
            texts=[str(t or "") for t in (data.get("texts") or [])],
            base=[str(t or "") for t in (data.get("base") or [])],
            created_at=float(data.get("created_at") or time.time()),
            entry=str(data.get("entry") or "in-app"),
        )


# --------------------------------------------------------------------------- 第二版本
#
# 第二引擎整片稿是**参考文档**，不是核对基线：它不进 50 步 history，也不允许
# 在复核页直接改；采用哪一句永远回核对台做。但它必须按媒体身份落盘，否则
# 「切到别的片再切回来」第二版就丢了（Q11）。

ALT_REVIEW_VERSION = 1


def media_cache_key(media_path: str | Path) -> str:
    """媒体身份：绝对路径 + 文件大小 + mtime（文件不存在时只按路径）。"""
    path = Path(str(media_path or "")).expanduser()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        stat = resolved.stat()
        fingerprint = f"{resolved}|{stat.st_size}|{int(stat.st_mtime_ns)}"
    except OSError:
        fingerprint = str(resolved)
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]


def alt_cache_path(output_dir: str | Path, media_path: str | Path) -> Path:
    """第二版边车文件：放在工作草稿缓存目录（output_dir），按媒体身份分段。"""
    stem = Path(str(media_path or "")).stem or "subtitles"
    key = media_cache_key(media_path)
    return Path(output_dir) / f"{stem}.{key}.autosave_draft.alt.json"


@dataclass
class AltReview:
    """一份第二引擎整片稿。``source`` 与 ``review_source`` 同构。"""

    engine: str
    cues: list[SubtitleCue]
    source: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    params: dict = field(default_factory=dict)
    media_path: str = ""

    def copy(self) -> "AltReview":
        return AltReview(
            engine=self.engine,
            cues=_copy(self.cues),
            source=dict(self.source),
            created_at=self.created_at,
            params=copy.deepcopy(self.params),
            media_path=self.media_path,
        )

    def to_dict(self) -> dict:
        return {
            "version": ALT_REVIEW_VERSION,
            "engine": self.engine,
            "cues": [
                {"start": cue.start, "end": cue.end, "text": cue.text} for cue in self.cues
            ],
            "source": dict(self.source),
            "created_at": self.created_at,
            "params": copy.deepcopy(self.params),
            "media_path": self.media_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AltReview | None":
        if not isinstance(data, dict):
            return None
        raw_cues = data.get("cues")
        if not isinstance(raw_cues, list):
            return None
        cues: list[SubtitleCue] = []
        for item in raw_cues:
            if not isinstance(item, dict):
                return None
            try:
                cues.append(
                    SubtitleCue(
                        start=float(item.get("start") or 0.0),
                        end=float(item.get("end") or 0.0),
                        text=str(item.get("text") or ""),
                    )
                )
            except (TypeError, ValueError):
                return None
        return cls(
            engine=str(data.get("engine") or ""),
            cues=cues,
            source=dict(data.get("source") or {}),
            created_at=float(data.get("created_at") or time.time()),
            params=dict(data.get("params") or {}),
            media_path=str(data.get("media_path") or ""),
        )


@dataclass
class HistoryState:
    """时间线上的一个**完整工作区状态**。

    统一撤销的唯一真源：字幕、全部译文轨、质检队列、导出设置与 AI diff 草稿
    都在这份快照里，所以一次 ⌘Z 不会只撤回其中一块。标签挂在「操作产生后的
    状态」上：撤回时返回的就是这个标签，历史列表里用户看到的是「这一步做了什么」。

    ``source`` 必须和字幕一起回滚：导入一份别的字幕后再 ⌘Z，右侧检查器要
    恢复成「这次转写」，而不是继续把当前表当导入文件。

    ``coalesce`` 是服务端合并连续调整用的键（例如 ``style.size``），不参与回滚。
    """

    cues: list[SubtitleCue]
    label: str
    at: float = field(default_factory=time.time)
    source: dict = field(default_factory=dict)
    translations: dict[str, TranslationTrack] = field(default_factory=dict)
    qa_payload: str = ""
    export_ui: dict = field(default_factory=dict)
    ai_draft: dict = field(default_factory=dict)
    coalesce: str = ""


@dataclass
class Session:
    id: str
    media_id: str | None = None
    # 最近一次转写结果
    latest_cues: list[SubtitleCue] = field(default_factory=list)
    # 核对基线（可编辑，所有 cue 增删改都作用在它上面）
    review_cues: list[SubtitleCue] = field(default_factory=list)
    # 当前核对表的来源：{kind, name, path, job_id, at}。
    # 右侧检查器的「质检速览 / 生效参数 / 输出」必须据此判断能不能引用
    # 最近一次转写的报告；导入了一版别的字幕时，绝不能继续展示上一次的质检数字。
    review_source: dict = field(default_factory=dict)
    # 可回溯时间线：history[0] 是「起始状态」，之后每一步是一次操作后的完整快照。
    # 不用双栈，是因为界面要列「每一步是什么」并且允许点任意一步跳过去；
    # 双栈只保留了「上一步」，没有可回溯的中间态可展示。
    history: list[HistoryState] = field(default_factory=list)
    history_cursor: int = -1
    updated_at: float = field(default_factory=time.time)
    # 转写任务在 worker 线程里回写结果，请求线程同时在读；一把会话锁避免
    # 「列表一半是旧结果一半是新结果」这种撕裂。
    # 译文平行轨：lang -> track。**绝不写进 review_cues.text**（D-3）。
    translations: dict[str, TranslationTrack] = field(default_factory=dict)
    # 每个语种自己的撤回栈：只服务检查器里的「撤销译文」按钮（一次退回上一版），
    # 不再是全局 ⌘Z 的存储；全局撤销统一走 history 快照。
    translation_undo: dict[str, list[TranslationTrack]] = field(default_factory=dict)
    # 第二引擎整片稿（参考文档，不进 history）。切换媒体时按边车文件恢复。
    alt_review: AltReview | None = None
    # 当前 alt_review 属于哪个媒体身份（media_cache_key）。空串表示没有同步过。
    alt_review_key: str = ""
    # 当前媒体路径：撤销质检状态时要按它把 .qa.json 写回磁盘。
    media_path: str = ""
    # 质检队列的当前整份 payload（会话缓存）；随历史快照一起回滚。
    qa_payload: str = ""
    # 导出面板的完整 UI 状态（表单/样式）；由渲染层通过 checkpoint 写回。
    export_ui: dict = field(default_factory=dict)
    # AI 优化台里人工改过的 diff 草稿；应用提案前也属于工作区状态。
    ai_draft: dict = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # -- 历史 ---------------------------------------------------------------

    def _state(self, label: str, coalesce: str = "") -> HistoryState:
        """把当前全部可编辑状态拍成一份快照。调用方必须已持有锁。"""
        return HistoryState(
            _copy(self.review_cues),
            label,
            source=dict(self.review_source),
            translations=_copy_tracks(self.translations),
            qa_payload=self.qa_payload,
            export_ui=copy.deepcopy(self.export_ui),
            ai_draft=copy.deepcopy(self.ai_draft),
            coalesce=coalesce,
        )

    def _ensure_baseline(self) -> None:
        """第一次编辑前把当前内容记为「起始状态」。

        不能在建会话时立刻记：那时还没有导入任何字幕，空基线没有意义；
        等到第一次真正要改的时候记，才能保证 ⌘Z 能退回导入前的样子。
        """
        if not self.history:
            self.history = [self._state("起始状态")]
            self.history_cursor = 0

    def record(self, label: str, coalesce: str = "") -> None:
        """公开入口：把当前状态记成时间线上的一步。"""
        self._record(label, coalesce=coalesce)

    def ensure_baseline(self) -> None:
        """在**改动之前**先固定「起始状态」。

        译文 / 质检 / 导出设置这类路径是「先改状态再 record」，如果不提前
        建基线，第一次改动会被并进起始状态，⌘Z 就退不回去。
        """
        with self.lock:
            self._ensure_baseline()

    def _record(self, label: str, coalesce: str = "") -> None:
        with self.lock:
            self._ensure_baseline()
            now = time.time()
            text = (label or "编辑").strip()[:120] or "编辑"
            # 同一类连续调整（滑杆 / 同一行 AI 建议）在窗口内合并成一步：
            # 拖一次字号不应该塞进几十条历史。
            if (
                coalesce
                and self.history_cursor > 0
                and self.history_cursor == len(self.history) - 1
            ):
                top = self.history[-1]
                if top.coalesce == coalesce and now - top.at <= COALESCE_SECONDS:
                    merged = self._state(text, coalesce)
                    merged.at = now
                    self.history[-1] = merged
                    self.updated_at = now
                    return
            # 从历史中间编辑：截断后面的分支，与普通编辑器语义一致
            if self.history_cursor < len(self.history) - 1:
                del self.history[self.history_cursor + 1 :]
            self.history.append(self._state(text, coalesce))
            self.history_cursor = len(self.history) - 1
            overflow = len(self.history) - (HISTORY_LIMIT + 1)
            if overflow > 0:
                del self.history[:overflow]
                self.history_cursor -= overflow
            self.updated_at = now

    def _apply_state(self, state: HistoryState) -> None:
        """把一份快照写回会话；撤销 / 重做 / 跳转共用。"""
        previous_qa = self.qa_payload
        self.review_cues = _copy(state.cues)
        self.review_source = dict(state.source)
        self.translations = _copy_tracks(state.translations)
        self.qa_payload = state.qa_payload or ""
        self.export_ui = copy.deepcopy(state.export_ui)
        self.ai_draft = copy.deepcopy(state.ai_draft)
        if self.media_path and self.qa_payload != previous_qa:
            # 质检状态也属于工作区：撤销一次「删除此句」时，待核列表必须跟着回去。
            from core.audit import empty_audit_payload, write_audit_payload

            payload = self.qa_payload or empty_audit_payload(Path(self.media_path).name)
            write_audit_payload(self.media_path, payload)
        self.updated_at = time.time()

    def set_qa_payload(self, payload: str | None) -> None:
        """更新质检队列缓存（读盘 / 动作后都走这里）。"""
        with self.lock:
            self.qa_payload = str(payload or "")
            self.updated_at = time.time()

    def set_client_state(
        self,
        *,
        export_ui: dict | None = None,
        ai_draft: dict | None = None,
    ) -> None:
        """同步渲染层本地状态（导出设置 / AI 草稿），不产生历史步骤。"""
        with self.lock:
            if export_ui is not None:
                self.export_ui = copy.deepcopy(export_ui)
            if ai_draft is not None:
                self.ai_draft = copy.deepcopy(ai_draft)
            self.updated_at = time.time()

    def checkpoint(
        self,
        label: str,
        *,
        export_ui: dict | None = None,
        ai_draft: dict | None = None,
        coalesce: str = "",
        record: bool = True,
    ) -> None:
        """记一步「渲染层本地状态」的改动。

        导出设置与 AI diff 草稿只存在于渲染层；这里把它们并进同一个工作区快照，
        保证 ⌘Z 与字幕 / 译文 / 质检共用一条时间线。``record=False`` 用于切换
        AI 上下文这类「同步状态但不算编辑」的动作。
        """
        with self.lock:
            if record:
                # 先建基线，再写入新状态；否则第一次改导出设置会被并进「起始状态」。
                self._ensure_baseline()
            if export_ui is not None:
                self.export_ui = copy.deepcopy(export_ui)
            if ai_draft is not None:
                self.ai_draft = copy.deepcopy(ai_draft)
            if record:
                self._record(label, coalesce=coalesce)
            else:
                self.updated_at = time.time()

    @property
    def can_undo(self) -> bool:
        return self.history_cursor > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self.history_cursor < len(self.history) - 1

    def undo_label(self) -> str:
        """下一次 ⌘Z 会撤回哪一步（没有可撤回的返回空串）。"""
        if not self.can_undo:
            return ""
        return self.history[self.history_cursor].label

    def redo_label(self) -> str:
        """下一次 ⇧⌘Z 会重做哪一步。"""
        if not self.can_redo:
            return ""
        return self.history[self.history_cursor + 1].label

    def undo_timestamp(self) -> float:
        """下一次 ⌘Z 会撤回的那一步是在什么时候记录的（显示用）。

        统一历史已经不再按域比较先后；保留这个字段只是让工具栏 / 历史面板显示
        「这一步发生在什么时候」。没有可撤回步骤时返回 0。
        """
        if not self.can_undo:
            return 0.0
        return float(self.history[self.history_cursor].at)

    def redo_timestamp(self) -> float:
        """下一次 ⇧⌘Z 会重做的那一步的时间；没有时返回 0。"""
        if not self.can_redo:
            return 0.0
        return float(self.history[self.history_cursor + 1].at)

    def undo(self) -> str | None:
        """退回上一步，返回被撤回操作的标签；没有历史时返回 None。"""
        with self.lock:
            self._ensure_baseline()
            if self.history_cursor <= 0:
                return None
            label = self.history[self.history_cursor].label
            self.history_cursor -= 1
            self._apply_state(self.history[self.history_cursor])
            return label

    def redo(self) -> str | None:
        with self.lock:
            self._ensure_baseline()
            if self.history_cursor >= len(self.history) - 1:
                return None
            self.history_cursor += 1
            state = self.history[self.history_cursor]
            self._apply_state(state)
            return state.label

    def jump_history(self, index: int) -> str | None:
        """点历史里的任意一步：直接回到那个状态。

        越界返回 None；不产生新的历史条目——跳转不是编辑，时间线保持原样。
        """
        with self.lock:
            self._ensure_baseline()
            if not 0 <= index < len(self.history):
                return None
            self.history_cursor = index
            state = self.history[index]
            self._apply_state(state)
            return state.label

    def history_items(self) -> list[dict]:
        with self.lock:
            self._ensure_baseline()
            items = []
            for i, state in enumerate(self.history):
                if i == self.history_cursor:
                    status = "current"
                elif i < self.history_cursor:
                    status = "past"
                else:
                    status = "undone"
                items.append(
                    {
                        "id": i,
                        "label": state.label,
                        "at": state.at,
                        "state": status,
                        "cue_count": len(state.cues),
                    }
                )
            return items

    # -- 变更（全部返回是否成功，越界不抛异常） ------------------------------

    def replace_review(
        self,
        cues: list[SubtitleCue],
        label: str = "替换全部字幕",
        *,
        source: dict | None = None,
        record: bool = True,
    ) -> None:
        """整表替换；``source`` 非空时同步改写这张表的来源。

        来源必须和字幕一起进历史：先导入 A、再导入 B、再 ⌘Z 时，回退的是
        「B 的字幕 + B 的来源」，不能只回退字幕而让检查器继续把 B 当当前文件。
        普通编辑（AI 应用、查找替换）不传 ``source``，保留原来源。

        条数变了的整表替换会让任何旧译文轨无法逐条对齐，这里统一丢弃错位的轨；
        条数没变的替换保留轨（内容变化由 stale 计算如实反映）。
        """
        with self.lock:
            self._ensure_baseline()
            self.review_cues = _copy(cues)
            if source is not None:
                self.review_source = dict(source)
            self._drop_misaligned_translations()
            if record:
                self._record(label)
            else:
                self.updated_at = time.time()

    def _drop_misaligned_translations(self) -> None:
        """删掉条数已与字幕对不上的译文轨，绝不让错位的轨继续存在。"""
        count = len(self.review_cues)
        for lang in list(self.translations):
            if len(self.translations[lang].texts) != count:
                self.translations.pop(lang, None)
                self.translation_undo.pop(lang, None)

    def _drop_translation_undo(self) -> None:
        """结构性编辑后旧版整轨已无法对齐，清掉该语种的整轨撤销栈。"""
        self.translation_undo.clear()

    def _remove_translation_at(self, index: int) -> None:
        for track in self.translations.values():
            if 0 <= index < len(track.texts):
                del track.texts[index]
            if 0 <= index < len(track.base):
                del track.base[index]

    def _insert_translation_at(self, index: int) -> None:
        for track in self.translations.values():
            pos = max(0, min(index, len(track.texts)))
            track.texts.insert(pos, "")
            pos_base = max(0, min(index, len(track.base)))
            track.base.insert(pos_base, "")

    def update_cue(
        self,
        index: int,
        start: float,
        end: float,
        text: str,
        label: str = "",
    ) -> bool:
        with self.lock:
            if not 0 <= index < len(self.review_cues):
                return False
            self._ensure_baseline()
            self.review_cues[index] = SubtitleCue(start=start, end=end, text=text)
            self._record(label or f"修改第 {index + 1} 条")
            return True

    def delete_cue(self, index: int, label: str = "") -> bool:
        """删除一条：译文轨同步删掉同一位置，后面的译文不会整体前移一条。"""
        with self.lock:
            if not 0 <= index < len(self.review_cues):
                return False
            self._ensure_baseline()
            del self.review_cues[index]
            self._remove_translation_at(index)
            self._drop_translation_undo()
            self._record(label or f"删除第 {index + 1} 条")
            return True

    def delete_cues(self, indices: list[int], label: str = "") -> int:
        """批量删除（底部轨道多选）：一次历史、译文轨同步。返回实际删除条数。"""
        with self.lock:
            valid = sorted(
                {int(i) for i in indices if 0 <= int(i) < len(self.review_cues)},
                reverse=True,
            )
            if not valid:
                return 0
            self._ensure_baseline()
            for index in valid:
                del self.review_cues[index]
                self._remove_translation_at(index)
            self._drop_translation_undo()
            text = label or f"删除选中的 {len(valid)} 条字幕"
            self._record(text)
            return len(valid)

    def insert_cue(
        self,
        index: int,
        start: float,
        end: float,
        text: str,
        label: str = "",
    ) -> bool:
        """插入一条：译文轨在同一位置插入空占位，后续条目不会错位。"""
        with self.lock:
            if not 0 <= index <= len(self.review_cues):
                return False
            self._ensure_baseline()
            self.review_cues.insert(index, SubtitleCue(start=start, end=end, text=text))
            self._insert_translation_at(index)
            self._drop_translation_undo()
            self._record(label or f"插入第 {index + 1} 条")
            return True

    def split_cue(self, index: int, at: float, min_duration: float = 0.05) -> int:
        """在 ``at`` 处把一条字幕切成两条；两段都保留完整原文。

        用户明确要求切开后两段都先保留原句（若自动判断断点内容不可靠），
        再由用户分别删减。译文同样复制一份，双语轨道不会错位。
        返回新插入的后半段下标；失败返回 -1。
        """
        with self.lock:
            if not 0 <= index < len(self.review_cues):
                return -1
            cue = self.review_cues[index]
            span = cue.end - cue.start
            if span <= min_duration * 2:
                return -1
            point = max(cue.start + min_duration, min(cue.end - min_duration, float(at)))
            if point - cue.start < min_duration or cue.end - point < min_duration:
                return -1
            self._ensure_baseline()
            left = SubtitleCue(start=cue.start, end=round(point, 3), text=cue.text)
            right = SubtitleCue(start=round(point, 3), end=cue.end, text=cue.text)
            self.review_cues[index] = left
            self.review_cues.insert(index + 1, right)
            for track in self.translations.values():
                text = track.texts[index] if 0 <= index < len(track.texts) else ""
                track.texts.insert(index + 1, text)
                base = track.base[index] if 0 <= index < len(track.base) else ""
                track.base.insert(index + 1, base)
            self._drop_translation_undo()
            self._record(f"切割第 {index + 1} 条字幕")
            return index + 1

    def merge_cues(self, indices: list[int]) -> int:
        """把连续的多条字幕合并成一条（区间取首尾，文本按顺序拼接）。

        双语时译文按同样规则拼接，合并后仍然逐条对齐。返回合并后的下标；
        不足两条或下标不连续时返回 -1。
        """
        with self.lock:
            ordered = sorted({int(i) for i in indices})
            if len(ordered) < 2:
                return -1
            first, last = ordered[0], ordered[-1]
            if ordered != list(range(first, last + 1)):
                return -1
            if first < 0 or last >= len(self.review_cues):
                return -1
            self._ensure_baseline()
            span = self.review_cues[first:last + 1]
            merged = SubtitleCue(
                start=span[0].start,
                end=span[-1].end,
                text=_join_cue_texts([cue.text for cue in span]),
            )
            self.review_cues[first:last + 1] = [merged]
            count = last - first + 1
            for track in self.translations.values():
                texts = track.texts[first:last + 1]
                bases = track.base[first:last + 1]
                track.texts[first:last + 1] = [_join_cue_texts(texts)]
                track.base[first:last + 1] = [_join_cue_texts(bases)]
            self._drop_translation_undo()
            self._record(f"合并 {count} 条字幕")
            return first

    def clear_review(self, label: str = "清空全部字幕") -> None:
        with self.lock:
            self._ensure_baseline()
            self.review_cues = []
            # 字幕清空后旧来源（哪次转写 / 哪个导入文件）已经无意义；
            # 检查器不该继续展示那份报告或参数。
            self.review_source = {}
            self.translations.clear()
            self.translation_undo.clear()
            self._record(label)

    def reset_for_media(self) -> None:
        """换片：清空上一部片的所有字幕、译文、历史与来源，绝不串片。

        第二版稿只在**内存**里清掉；磁盘边车保留，切回原片时还能恢复。
        """
        with self.lock:
            self.alt_review = None
            self.alt_review_key = ""
            self.review_cues = []
            self.latest_cues = []
            self.translations.clear()
            self.translation_undo.clear()
            self.review_source = {}
            self.qa_payload = ""
            self.export_ui = {}
            self.ai_draft = {}
            self.history = []
            self.history_cursor = -1
            self.updated_at = time.time()

    # -- 第二版本（alt_review）---------------------------------------------

    def _reset_alt_memory(self) -> None:
        self.alt_review = None
        self.alt_review_key = ""

    def sync_alt_review(
        self,
        *,
        media_path: str,
        output_dir: str | Path,
        restore: bool = True,
    ) -> bool:
        """切媒体时的第二版同步：先清内存，再尝试恢复新城媒体的边车。

        返回是否发生了「媒体身份变化」（调用方据此决定要不要刷新界面）。
        同一个媒体重复调用是幂等的，不会把刚写进内存的第二版冲掉。
        """
        path = str(media_path or "")
        key = media_cache_key(path)
        with self.lock:
            if key == self.alt_review_key:
                return False
            self._reset_alt_memory()
            self.alt_review_key = key
            if not restore:
                return True
            cache = alt_cache_path(output_dir, path) if path else None
            if cache is not None and cache.exists():
                data = _load_alt_file(cache)
                alt = AltReview.from_dict(data) if data else None
                if alt is not None:
                    alt.media_path = path
                    self.alt_review = alt
            return True

    def set_alt_review(
        self,
        *,
        engine: str,
        cues: list[SubtitleCue],
        source: dict | None = None,
        params: dict | None = None,
        media_path: str = "",
        output_dir: str | Path,
    ) -> AltReview:
        """写入第二版并立刻落盘（边车文件），核对台一个字都不动。"""
        with self.lock:
            alt = AltReview(
                engine=str(engine or ""),
                cues=_copy(cues),
                source=dict(source or {}),
                created_at=time.time(),
                params=copy.deepcopy(params or {}),
                media_path=str(media_path or ""),
            )
            self.alt_review = alt
            self.alt_review_key = media_cache_key(media_path) if media_path else ""
            if media_path:
                target = alt_cache_path(output_dir, media_path)
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    write_text_atomic(
                        target, json.dumps(alt.to_dict(), ensure_ascii=False, indent=2) + "\n"
                    )
                except OSError:
                    # 落盘失败不能影响本次转写结果：内存里仍然可用，下次转写会再写。
                    pass
            self.updated_at = time.time()
            return alt

    def clear_alt_review(
        self,
        *,
        media_path: str = "",
        output_dir: str | Path = "",
        remove_cache: bool = True,
    ) -> bool:
        """丢弃第二版：内存必清，磁盘边车默认一起删（下次切回不再出现）。"""
        with self.lock:
            existed = self.alt_review is not None
            self._reset_alt_memory()
            if remove_cache and media_path and output_dir:
                target = alt_cache_path(output_dir, media_path)
                try:
                    if target.exists():
                        target.unlink()
                except OSError:
                    pass
            self.updated_at = time.time()
            return existed

    def alt_review_summary(self) -> dict:
        with self.lock:
            alt = self.alt_review
            if alt is None:
                return {"exists": False, "count": 0, "engine": "", "source": {}, "created_at": 0}
            return {
                "exists": True,
                "engine": alt.engine,
                "count": len(alt.cues),
                "source": dict(alt.source),
                "created_at": alt.created_at,
            }

    # -- 译文轨 -------------------------------------------------------------

    def set_translation(
        self,
        track: TranslationTrack,
        label: str = "应用译文",
        *,
        record: bool = True,
        remember: bool = True,
    ) -> None:
        """整轨替换；默认压一步统一历史。

        ``record=False`` 只用于「恢复草稿」这类已经在别处记过一步的批处理；
        ``remember=False`` 避免草稿恢复把旧版本塞进「撤销译文」按钮的栈。
        """
        with self.lock:
            if record:
                self._ensure_baseline()
            previous = self.translations.get(track.lang)
            if previous is not None and remember:
                stack = self.translation_undo.setdefault(track.lang, [])
                stack.append(previous.copy())
                if len(stack) > TRACK_UNDO_LIMIT:
                    stack.pop(0)
            self.translations[track.lang] = track
            if record:
                self._record(label)
            else:
                self.updated_at = time.time()

    def undo_translation(self, lang: str) -> bool:
        """把该语种退回到上一版译文；这次退回本身也记一步，⌘Z 可再回来。"""
        with self.lock:
            stack = self.translation_undo.get(lang) or []
            if not stack:
                return False
            self._ensure_baseline()
            self.translations[lang] = stack.pop()
            if not stack:
                self.translation_undo.pop(lang, None)
            self._record(f"撤回上一版 {lang} 译文")
            return True

    def patch_translation(self, lang: str, index: int, text: str, label: str = "") -> bool:
        """改某一条译文（不动原文、不动时间轴），并压一步统一历史。

        人工改完译文就算「已同步」：把 ``base[index]`` 更新成当前原文，
        这样「原文改过了，译文可能需要同步」的提示会随这一次保存消失。
        """
        with self.lock:
            track = self.translations.get(lang)
            if track is None or not 0 <= index < len(track.texts):
                return False
            text = str(text or "")
            if track.texts[index] == text:
                return True
            self._ensure_baseline()
            stack = self.translation_undo.setdefault(lang, [])
            stack.append(track.copy())
            if len(stack) > TRACK_UNDO_LIMIT:
                stack.pop(0)
            track.texts[index] = text
            while len(track.base) < len(track.texts):
                track.base.append("")
            if 0 <= index < len(self.review_cues):
                track.base[index] = self.review_cues[index].text
            self._record(label or f"修改 {lang} 译文第 {index + 1} 条")
            return True

    def drop_translation(self, lang: str, label: str = "", *, record: bool = True) -> bool:
        with self.lock:
            if lang not in self.translations:
                return False
            if record:
                self._ensure_baseline()
            self.translations.pop(lang, None)
            self.translation_undo.pop(lang, None)
            if record:
                self._record(label or f"删除 {lang} 译文")
            else:
                self.updated_at = time.time()
            return True

    def stale_translation(self, lang: str) -> list[int]:
        from core.i18n import stale_indices

        track = self.translations.get(lang)
        if track is None:
            return []
        return stale_indices(self.review_cues, track.base)


def _load_alt_file(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class SessionStore:
    """线程安全的会话表。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str | None) -> Session:
        with self._lock:
            if session_id:
                found = self._sessions.get(session_id)
                if found is not None:
                    found.updated_at = time.time()
                    return found
            sid = session_id or uuid.uuid4().hex
            session = Session(id=sid)
            self._sessions[sid] = session
            self._prune_locked()
            return session

    def peek(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _prune_locked(self) -> None:
        now = time.time()
        stale = [
            sid for sid, s in self._sessions.items() if now - s.updated_at > SESSION_TTL_S
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
