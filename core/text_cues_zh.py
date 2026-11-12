"""中文 / 中英混排字幕分句（纯函数，不 import torch）。

为什么单独成一个模块：SenseVoice-Small 与 FireRedASR2-AED 都从 sherpa-onnx 拿到
「token + 时间戳」，但中文没有空格、FireRed 又不带标点，不能沿用日语那套助词 DP
（`core/qwen_ctc.partition_cues` 的断句成本表是日语的）。这里只做两件事：

1. ``build_timed_chars()``：把 token 序列摊平成带起止时间的字符序列；
2. ``split_cues()``：按「标点 → 停顿 → 字数/时长」的优先级切成字幕条。

两条硬约束（都由测试看守）：

- **不劈开英文单词**：中英混排时，切点不能落在 ``[A-Za-z0-9]`` 中间；
- **每条字幕都有可读时长**：不产出 0.05 秒的闪字，末尾按 ``min_cue_dur`` 兜底。

刻意不做的：不做语义级断句（中文没有日语助词那种稳定线索），也不改写字。
模型没给时间戳时用 ``spread_text()`` 按字均分，并在引擎层计入「降级」统计，
不假装逐字对齐。
"""

from __future__ import annotations

from dataclasses import dataclass

# 句末与句内停顿。分号、省略号在字幕里通常意味着语气停顿，按句末处理。
STRONG_END = "。！？!?；;…‥"
WEAK_END = "，、：:,"
CLOSERS = "）)】」』”’\"'》〉"
OPENERS = "（(【「『“‘《〈"

# 单条字幕最短可读时长；低于它时向后补，但不会越过片段末尾。
MIN_CUE_DUR = 0.30
DEFAULT_PAD = 0.10


@dataclass(slots=True)
class TimedChar:
    ch: str
    start: float
    end: float


@dataclass(slots=True)
class CueDraft:
    start: float
    end: float
    text: str


def _clamp(value: float, low: float, high: float) -> float:
    if high < low:
        return low
    return max(low, min(high, value))


def _is_ascii_word(ch: str) -> bool:
    return bool(ch) and ch.isascii() and ch.isalnum()


def _needs_space(prev: TimedChar | None, token: str) -> bool:
    """中英混排的空格重建。

    sherpa 的 token 有两种形态：中文单字（``"开"``）与带前导空格的英文子词
    （``" tri"``）。中文之间不能加空格；英文单词之间必须有空格，否则导出字幕
    会变成 ``thetribal``。
    """
    if prev is None or not prev.ch or prev.ch.isspace():
        return False
    visible = token.strip()
    if not visible:
        return False
    if token[:1].isspace():
        return prev.ch not in OPENERS
    return _is_ascii_word(prev.ch) and _is_ascii_word(visible[0])


def build_timed_chars(
    tokens: list[str],
    starts: list[float],
    seg_start: float,
    seg_end: float,
) -> list[TimedChar]:
    """把 ``(tokens, timestamps)`` 摊平成字符级时间轴。

    每个 token 的结束时间取「下一个 token 的开始时间」，最后一个取片段末尾；
    多字符 token（英文子词）内部按字符均分。时间戳回退会被夹平，保证单调。
    """
    count = min(len(tokens), len(starts))
    if count <= 0 or seg_end <= seg_start:
        return []

    times = [float(value) for value in starts[:count]]
    for index in range(1, count):
        times[index] = max(times[index], times[index - 1])

    chars: list[TimedChar] = []
    pending_space = False
    for index in range(count):
        raw_token = str(tokens[index])
        visible = raw_token.strip()
        if not visible:
            # 独立的空格 token：下一个可见 token 前补一个空格（英文分词会这样切）。
            pending_space = True
            continue
        begin = _clamp(times[index], seg_start, seg_end)
        if index + 1 < count:
            finish = _clamp(times[index + 1], begin, seg_end)
        else:
            finish = seg_end
        if finish < begin:
            finish = begin

        if pending_space or _needs_space(chars[-1] if chars else None, raw_token):
            chars.append(TimedChar(" ", begin, begin))
        pending_space = False

        share = (finish - begin) / len(visible)
        for offset, ch in enumerate(visible):
            char_start = begin + share * offset
            char_end = finish if offset == len(visible) - 1 else begin + share * (offset + 1)
            chars.append(TimedChar(ch, char_start, char_end))
    return chars


def spread_text(text: str, seg_start: float, seg_end: float) -> list[TimedChar]:
    """模型没有时间戳时的退路：按字符数均分片段时间。"""
    visible = (text or "").strip()
    if not visible or seg_end <= seg_start:
        return []
    step = (seg_end - seg_start) / len(visible)
    return [
        TimedChar(ch, seg_start + step * index, seg_start + step * (index + 1))
        for index, ch in enumerate(visible)
    ]


def _cut_score(chars: list[TimedChar], position: int, pause_floor: float) -> float:
    """在 ``chars[position-1]`` 与 ``chars[position]`` 之间切一刀的分数。

    0 表示禁止切：劈开英文单词、把开括号留在上一行，都是不该发生的切点。
    """
    left = chars[position - 1]
    right = chars[position] if position < len(chars) else None

    if right is not None:
        if _is_ascii_word(left.ch) and _is_ascii_word(right.ch):
            return 0.0
        if right.ch in OPENERS:
            return 0.0
        # 标点必须留在上一行：切在「。」或「，」前面会产出单独一个标点字幕
        # （真实踩过：SenseVoice 把句号 token 的时间戳标在 0.2s 之后，停顿规则先命中）。
        if right.ch in STRONG_END or right.ch in WEAK_END or right.ch in CLOSERS:
            return 0.0

    strong = left.ch in STRONG_END or (
        left.ch in CLOSERS
        and position >= 2
        and chars[position - 2].ch in STRONG_END
    )
    weak = left.ch in WEAK_END or left.ch == " "
    # 模型给的是「token 起始时间」，停顿表现为上一个 token 的时长拉长，而不是
    # 两个 token 之间有空隙。所以两个口径都要看。
    paused = (left.end - left.start) >= pause_floor or (
        right is not None and (right.start - left.end) >= pause_floor
    )

    if strong:
        return 3.0
    if paused:
        return 2.0
    if weak:
        return 1.0
    return 0.0


def _pick_cut(
    chars: list[TimedChar],
    start: int,
    limit: int,
    min_chars: int,
    pause_floor: float,
) -> int:
    """在 ``(start, limit]`` 里挑一个切点；挑不到就硬切，但尽量不劈英文。"""
    best_score = 0.0
    best_position = 0
    for position in range(start + 2, limit + 1):
        score = _cut_score(chars, position, pause_floor)
        if score <= 0.0:
            continue
        # 标点切点不受最短字数限制（"好。"就该单独成条）；停顿/空格要求够长。
        if position - start < min_chars and score < 3.0:
            continue
        if score > best_score or (score == best_score and position > best_position):
            best_score = score
            best_position = position
    if best_position:
        return best_position

    # 硬切：从 limit 往回找最近的空格，避免把英文单词切成两半；
    # 也不要把标点甩到下一行开头。
    for position in range(limit, start + 1, -1):
        if position >= len(chars):
            continue
        left = chars[position - 1].ch
        right = chars[position].ch
        if right in STRONG_END or right in WEAK_END or right in CLOSERS:
            continue
        if left == " " or not (_is_ascii_word(left) and _is_ascii_word(right)):
            return position
    return max(start + 1, min(limit, len(chars)))


def _pick_strong_cut(chars: list[TimedChar], start: int) -> int:
    """窗口已经盖住整段剩余内容时，仍然在第一个句末标点后断开。

    一条字幕里塞进「两句完整的话」即使没超字数也读着别扭；但句内逗号不主动断，
    否则短句会被拆得七零八落。
    """
    for position in range(start + 2, len(chars)):
        if _cut_score(chars, position, pause_floor=1e9) >= 3.0:
            return position
    return 0


def split_cues(
    chars: list[TimedChar],
    *,
    seg_start: float,
    seg_end: float,
    max_cue_chars: int = 18,
    max_cue_dur: float = 4.3,
    min_pause_s: float = 0.20,
    cue_pad_s: float = DEFAULT_PAD,
    min_cue_dur: float = MIN_CUE_DUR,
) -> list[CueDraft]:
    """把字符时间轴切成字幕条。

    贪心 + 回退到最近的标点/停顿：先按 ``max_cue_chars`` 与 ``max_cue_dur`` 取窗口，
    再在窗口内挑分数最高的切点。中文单条 18 字（两行 × 9 字）是默认值。
    """
    if not chars:
        return []

    total = len(chars)
    max_chars = max(4, int(max_cue_chars or 18))
    max_dur = max(0.8, float(max_cue_dur or 4.3))
    min_chars = max(2, min(6, max_chars // 3))

    durations = sorted(
        char.end - char.start for char in chars if char.ch.strip()
    )
    median_dur = durations[len(durations) // 2] if durations else 0.0
    pause_floor = max(float(min_pause_s or 0.2), median_dur * 1.7)

    cues: list[CueDraft] = []
    start_index = 0
    previous_end = seg_start
    while start_index < total:
        limit = start_index + 1
        while (
            limit < total
            and (limit - start_index) < max_chars
            and (chars[limit].end - chars[start_index].start) <= max_dur
        ):
            limit += 1

        if limit >= total:
            end_index = _pick_strong_cut(chars, start_index) or total
        else:
            end_index = _pick_cut(chars, start_index, limit, min_chars, pause_floor)

        # 不要留「点。」这种只有 1–2 个字的尾巴：宁可让当前条稍微超一点时长。
        # 中文句末常是一个数字 + 量词/标点，模型给标点的时间戳又偏晚，最容易踩。
        if 0 < total - end_index <= 2:
            span = chars[-1].end - chars[start_index].start
            if span <= max_dur * 1.35 and (total - start_index) <= max_chars + 2:
                end_index = total

        end_index = max(start_index + 1, min(end_index, total))

        text = "".join(char.ch for char in chars[start_index:end_index]).strip()
        if text:
            begin = max(seg_start, chars[start_index].start - cue_pad_s)
            finish = min(seg_end, chars[end_index - 1].end + cue_pad_s)
            if begin < previous_end:
                begin = min(previous_end, max(seg_start, finish - 0.08))
            if finish - begin < min_cue_dur:
                finish = min(seg_end, begin + min_cue_dur)
            if finish <= begin:
                finish = begin + 0.08
            cues.append(
                CueDraft(
                    start=round(begin, 3),
                    end=round(finish, 3),
                    text=text,
                )
            )
            previous_end = finish
        start_index = end_index
    return cues
