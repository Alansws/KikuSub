"""会话状态：替代 Gradio 的 `gr.State`。

旧实现把四份状态放在 `gr.State` 里（转写结果 / 核对基线 / 撤销栈 / 重做栈），
只能被 Gradio 的会话机制持有。新架构改成 **`session_id` cookie + 进程内字典**，
沿用规划 §4 的结论：服务端仍是唯一真源，前端撤销栈只做乐观回显。

一个会话同一时间只服务一个媒体文件（和桌面端「一次核对一部片」的用法一致）。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from core.subtitles import SubtitleCue

# 可回溯历史：最多保留 20 步**操作**（另加一条「起始状态」）。
# 用户明确要求历史列表能看 20 步；撤销/重做、点击任意一步跳转都共用这份时间线。
HISTORY_LIMIT = 20
# 兼容旧名字：曾经叫 UNDO_LIMIT，语义相同。
UNDO_LIMIT = HISTORY_LIMIT
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


@dataclass
class HistoryState:
    """时间线上的一个状态：字幕快照 + 来源 + 产生它的操作说明。

    标签挂在「操作产生后的状态」上：撤回时返回的就是这个标签，历史列表里
    用户看到的是「这一步做了什么」。``at`` 用于界面显示时间。

    ``source`` 必须和字幕一起回滚：导入一份别的字幕后再 ⌘Z，右侧检查器要
    恢复成「这次转写」，而不是继续把当前表当导入文件。

    ``translations`` 也跟着快照：删除 / 切割 / 合并会同步搬动译文轨，撤销时必须
    把轨搬回去，否则恢复的字幕与译文会错位一条。应用整版译文本身仍不进这里，
    它有每个语种自己的撤销栈。
    """

    cues: list[SubtitleCue]
    label: str
    at: float = field(default_factory=time.time)
    source: dict = field(default_factory=dict)
    translations: dict[str, TranslationTrack] = field(default_factory=dict)


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
    # 每个语种自己的撤回栈（只存整轨快照，足够覆盖"应用了一版译文"这种批量操作）
    translation_undo: dict[str, list[TranslationTrack]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # -- 历史 ---------------------------------------------------------------

    def _ensure_baseline(self) -> None:
        """第一次编辑前把当前内容记为「起始状态」。

        不能在建会话时立刻记：那时还没有导入任何字幕，空基线没有意义；
        等到第一次真正要改的时候记，才能保证 ⌘Z 能退回导入前的样子。
        """
        if not self.history:
            self.history = [
                HistoryState(
                    _copy(self.review_cues),
                    "起始状态",
                    source=dict(self.review_source),
                    translations=_copy_tracks(self.translations),
                )
            ]
            self.history_cursor = 0

    def _record(self, label: str) -> None:
        with self.lock:
            self._ensure_baseline()
            # 从历史中间编辑：截断后面的分支，与普通编辑器语义一致
            if self.history_cursor < len(self.history) - 1:
                del self.history[self.history_cursor + 1 :]
            text = (label or "编辑字幕").strip()[:120] or "编辑字幕"
            self.history.append(
                HistoryState(
                    _copy(self.review_cues),
                    text,
                    source=dict(self.review_source),
                    translations=_copy_tracks(self.translations),
                )
            )
            self.history_cursor = len(self.history) - 1
            overflow = len(self.history) - (HISTORY_LIMIT + 1)
            if overflow > 0:
                del self.history[:overflow]
                self.history_cursor -= overflow
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
        """下一次 ⌘Z 会撤回的那一步是在什么时候记录的。

        界面用它和本地「导出设置」历史比先后：全局 ⌘Z 必须撤回**最近一次**操作，
        而不是永远先撤回字幕。没有可撤回步骤时返回 0。
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
            state = self.history[self.history_cursor]
            self.review_cues = _copy(state.cues)
            self.review_source = dict(state.source)
            self.translations = _copy_tracks(state.translations)
            self.updated_at = time.time()
            return label

    def redo(self) -> str | None:
        with self.lock:
            self._ensure_baseline()
            if self.history_cursor >= len(self.history) - 1:
                return None
            self.history_cursor += 1
            state = self.history[self.history_cursor]
            self.review_cues = _copy(state.cues)
            self.review_source = dict(state.source)
            self.translations = _copy_tracks(state.translations)
            self.updated_at = time.time()
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
            self.review_cues = _copy(state.cues)
            self.review_source = dict(state.source)
            self.translations = _copy_tracks(state.translations)
            self.updated_at = time.time()
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
            self._record(label)

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
            self.translations.clear()
            self.translation_undo.clear()
            self._record(label)

    def reset_for_media(self) -> None:
        """换片：清空上一部片的所有字幕、译文、历史与来源，绝不串片。"""
        with self.lock:
            self.review_cues = []
            self.latest_cues = []
            self.translations.clear()
            self.translation_undo.clear()
            self.review_source = {}
            self.history = []
            self.history_cursor = -1
            self.updated_at = time.time()

    # -- 译文轨 -------------------------------------------------------------

    def _sync_history_translations(self, lang: str) -> None:
        """把最新的译文轨写回历史快照里条数相同的状态。

        应用/修改译文本身不进字幕撤销栈，但之后若因删除字幕按 ⌘Z，撤回的
        「删除前状态」必须带着当时已经应用的译文；否则会把译文一起撤回、
        留下字幕恢复了但译文消失的假象。条数对不上的旧状态不能硬塞，直接清掉。
        """
        track = self.translations.get(lang)
        for state in self.history:
            if track is not None and len(state.cues) == len(track.texts):
                state.translations[lang] = track.copy()
            else:
                state.translations.pop(lang, None)

    def set_translation(self, track: TranslationTrack) -> None:
        """整轨替换，并保留上一版供撤销。"""
        with self.lock:
            previous = self.translations.get(track.lang)
            if previous is not None:
                stack = self.translation_undo.setdefault(track.lang, [])
                stack.append(previous.copy())
                if len(stack) > TRACK_UNDO_LIMIT:
                    stack.pop(0)
            self.translations[track.lang] = track
            self._sync_history_translations(track.lang)
            self.updated_at = time.time()

    def undo_translation(self, lang: str) -> bool:
        with self.lock:
            stack = self.translation_undo.get(lang) or []
            if not stack:
                return False
            self.translations[lang] = stack.pop()
            if not stack:
                self.translation_undo.pop(lang, None)
            self._sync_history_translations(lang)
            self.updated_at = time.time()
            return True

    def patch_translation(self, lang: str, index: int, text: str) -> bool:
        """改某一条译文（不动原文、不动时间轴），并留一步撤销。

        人工改完译文就算「已同步」：把 ``base[index]`` 更新成当前原文，
        这样「原文改过了，译文可能需要同步」的提示会随这一次保存消失。
        """
        with self.lock:
            track = self.translations.get(lang)
            if track is None or not 0 <= index < len(track.texts):
                return False
            stack = self.translation_undo.setdefault(lang, [])
            stack.append(track.copy())
            if len(stack) > TRACK_UNDO_LIMIT:
                stack.pop(0)
            track.texts[index] = str(text or "")
            while len(track.base) < len(track.texts):
                track.base.append("")
            if 0 <= index < len(self.review_cues):
                track.base[index] = self.review_cues[index].text
            self._sync_history_translations(lang)
            self.updated_at = time.time()
            return True

    def drop_translation(self, lang: str) -> bool:
        with self.lock:
            if self.translations.pop(lang, None) is None:
                return False
            self.translation_undo.pop(lang, None)
            for state in self.history:
                state.translations.pop(lang, None)
            self.updated_at = time.time()
            return True

    def stale_translation(self, lang: str) -> list[int]:
        from core.i18n import stale_indices

        track = self.translations.get(lang)
        if track is None:
            return []
        return stale_indices(self.review_cues, track.base)


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
