"""中文 / 中英混排字幕分句（纯函数，不 import torch）。

为什么单独成一个模块：SenseVoice-Small 与 FireRedASR2-AED 都从 sherpa-onnx 拿到
「token + 时间戳」，但中文没有空格、FireRed 又不带标点，不能沿用日语那套助词 DP
（`core/qwen_ctc.partition_cues` 的断句成本表是日语的）。这里只做两件事：

1. ``build_timed_chars()``：把 token 序列摊平成带起止时间的字符序列；
2. ``spread_text()`` / ``spread_text_voiced()``：模型不给时间戳时（FireRed）按字
   均分，或按能量找到的「有声区间」铺开，不假装逐字对齐；
3. ``split_cues()``：按「句末标点 → 停顿 → 逗号 → 词首」的优先级切成字幕条。

三条硬约束（都由测试看守）：

- **不劈开词**：中英混排时不切在 ``[A-Za-z0-9]`` 中间；中文用 jieba 的词边界兜底，
  不把「办理」切成「办 / 理」；
- **不劈开 eSIM 这类词**：FireRed 会把它切成 ``E``/``SIM`` 两个 token，切点不能落在
  单字母与英文词之间；
- **每条字幕都有可读时长**：不产出 0.05 秒的闪字，末尾按 ``min_cue_dur`` 兜底。

刻意不做的：不做语义级断句（中文没有日语助词那种稳定线索），也不改写字。
"""

from __future__ import annotations

from dataclasses import dataclass

# 句末与句内停顿。分号、省略号在字幕里通常意味着语气停顿，按句末处理。
STRONG_END = "。！？!?；;…‥"
WEAK_END = "，、：:,"
CLOSERS = "）)】」』”’\"'》〉"
OPENERS = "（(【「『“‘《〈"

# 不能出现在字幕开头的字：切在这些字前面（「…国内 / 的eSIM了」）读起来最别扭。
NO_LINE_START = set("的了着过地得吗呢吧啊呀哦嘛呗啦是不在和与及或就都也还又才")
# 不能出现在字幕结尾的字：副词/介词悬在句尾同样别扭（「然后它也 / 是国内」）。
NO_LINE_END = set("很太更最没别也又还就都才把将被给对从向在和与及或是不")

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


def _is_cjk(ch: str) -> bool:
    return bool(ch) and "\u4e00" <= ch <= "\u9fff"


def word_starts(text: str) -> set[int]:
    """返回「词首」字符下标集合（含 0）；jieba 不可用时返回空集。

    中文没有空格，只靠字数硬切必然切进词里（真实素材：「办理」被劈成
    「办 / 理」、「手机」被劈成「手 / 机」）。这里借 jieba 的词典分词拿到词边界，
    只用来**打分**：切点优先落在句末标点 → 停顿 → 逗号 → 词首。jieba 是纯 Python
    的 5 MB 词典，不改变模型链路；缺了它只是回到「字数硬切」的旧行为。
    """
    value = text or ""
    if not value:
        return set()
    try:
        import jieba

        # 默认 INFO 会把「Building prefix dict …」打进 sidecar stderr/诊断日志。
        jieba.setLogLevel(30)
    except Exception:  # noqa: BLE001 - 分词是增强项，缺了不能影响转写
        return set()
    starts = {0}
    position = 0
    for token in jieba.cut(value, HMM=False):
        if not token:
            continue
        position += len(token)
        starts.add(position)
    return starts


def _leading_space_token(prev: TimedChar | None, token: str) -> bool:
    """中英混排的空格重建：**只认 token 自带的词边界**。

    sherpa 的 token 是 SentencePiece 形状：词边界表现为 token 自带前导空格
    （``" tri"``），词内子词没有空格（``"E" "s" "im"`` → ``Esim``）。所以不能再按
    「前一个和下一个都是 ASCII 就补空格」的规则重建——真实踩过：SenseVoice 把
    ``eSIM`` 切成 ``E``/``s``/``im``，旧规则会输出 ``E s im``，而模型给的 ``text``
    明明是 ``Esim``。
    """
    if prev is None or not prev.ch or prev.ch.isspace():
        return False
    if not token.strip():
        return False
    return token[:1].isspace() and prev.ch not in OPENERS


def build_timed_chars(
    tokens: list[str],
    starts: list[float],
    seg_start: float,
    seg_end: float,
) -> list[TimedChar]:
    """把 ``(tokens, timestamps)`` 摊平成字符级时间轴。

    ``starts`` 是 sherpa-onnx 给出的**片段内相对时间**（秒）；本函数负责加上
    ``seg_start`` 变成原片绝对时间。每个 token 的结束时间取「下一个 token 的开始
    时间」，最后一个取片段末尾；多字符 token（英文子词）内部按字符均分。
    时间戳回退会被夹平，保证单调。
    """
    count = min(len(tokens), len(starts))
    if count <= 0 or seg_end <= seg_start:
        return []

    # sherpa-onnx 的 timestamps 是**相对片段起点**的秒数，不是绝对时间轴。
    # 旧实现直接把它当绝对时间再做 clamp，结果整段字符被压到 seg_start 上，
    # 字幕塌成 0.3 秒、剩下的字被 _dedupe 当重叠丢掉（SenseVoice 默认参数
    # CER 69% 的根因）。这里统一加上 seg_start。
    times = [seg_start + float(value) for value in starts[:count]]
    for index in range(1, count):
        times[index] = max(times[index], times[index - 1])
    times = [_clamp(value, seg_start, seg_end) for value in times]

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

        if pending_space or _leading_space_token(chars[-1] if chars else None, raw_token):
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


def voiced_spans(
    audio,
    *,
    sample_rate: int = 16000,
    frame_ms: int = 20,
    relative_threshold: float = 0.12,
    min_gap_s: float = 0.10,
) -> list[tuple[float, float]]:
    """用能量找出一段音频里「真的在说话」的区间（相对片段起点，秒）。

    中文两个引擎里 FireRedASR2 不返回时间戳，只能按字均分；均分的问题是把停顿
    也算成发音时间，字幕条会跨着静音走。VAD 段内部本来就含 0.1–0.35s 的停顿，
    用能量把这些停顿找出来，再把字铺在「有声时间」上，切点就能落在停顿附近。

    只做粗粒度（20ms 帧），不追求毫秒级；找不到任何有声区间时返回空列表，
    调用方回退到按字均分。
    """
    import numpy as np

    data = np.asarray(audio, dtype=np.float32)
    if data.size == 0 or sample_rate <= 0:
        return []
    frame = max(1, int(sample_rate * frame_ms / 1000))
    usable = data.size - data.size % frame
    if usable < frame * 5:
        return []
    frames = data[:usable].reshape(-1, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    peak = float(np.percentile(rms, 95))
    if peak <= 0:
        return []
    active = rms >= peak * relative_threshold
    spans: list[list[float]] = []
    start_index = None
    for index, flag in enumerate(active):
        if flag and start_index is None:
            start_index = index
        elif not flag and start_index is not None:
            spans.append([start_index * frame / sample_rate, index * frame / sample_rate])
            start_index = None
    if start_index is not None:
        spans.append([start_index * frame / sample_rate, usable / sample_rate])
    # 太短的「有声」多半是爆音/呼吸，直接并进前一段。
    merged: list[list[float]] = []
    for span in spans:
        if merged and span[0] - merged[-1][1] < min_gap_s:
            merged[-1][1] = span[1]
        else:
            merged.append(span)
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a >= 0.08]


def spread_text_voiced(
    text: str,
    seg_start: float,
    seg_end: float,
    spans: list[tuple[float, float]],
) -> list[TimedChar]:
    """按字把文本铺在「有声区间」上（FireRed 这种没有时间戳的引擎用）。

    字与字之间不跨停顿：第 k 个字落在第 k/N 个有声时长处。没有可用区间时退回
    `spread_text()`。
    """
    visible = (text or "").strip()
    if not visible or seg_end <= seg_start:
        return []
    if not spans:
        return spread_text(text, seg_start, seg_end)
    total = sum(end - begin for begin, end in spans)
    if total <= 0:
        return spread_text(text, seg_start, seg_end)

    def locate(ratio: float) -> tuple[int, float]:
        """有声时间比例 → (第几个有声区间, 区间内绝对时间)。"""
        target = min(max(ratio, 0.0), 1.0) * total
        cursor = 0.0
        for index, (begin, end) in enumerate(spans):
            length = end - begin
            if target <= cursor + length:
                return index, seg_start + begin + max(0.0, target - cursor)
            cursor += length
        last = len(spans) - 1
        return last, seg_start + spans[last][1]

    count = len(visible)
    chars: list[TimedChar] = []
    for index, ch in enumerate(visible):
        span_index, begin = locate(index / count)
        next_span, finish = locate((index + 1) / count)
        # 跨了停顿就停在当前区间的末尾：把空隙留给「两条字幕之间」，而不是把它
        # 摊到一个字的时长里。否则切开时会切在停顿的**下一个字之后**，正好劈开
        # 「办 / 理」这种词（真实踩过）。
        if next_span != span_index:
            finish = seg_start + spans[span_index][1]
        if finish < begin:
            finish = begin
        chars.append(TimedChar(ch, begin, finish))
    return chars


def _ascii_break_forbidden(chars: list[TimedChar], position: int) -> bool:
    """切点是否会把一个英文词（含 ``E SIM`` 这种单字母 + 词的写法）劈成两半。"""
    if position <= 0 or position >= len(chars):
        return False
    left = chars[position - 1].ch
    right = chars[position].ch
    if _is_ascii_word(left) and _is_ascii_word(right):
        return True
    # "E | SIM"：切在空格之后。只有**独立单字母**才算（"the tribal" 里的 e 不是）。
    if left == " " and position >= 2:
        before = chars[position - 2].ch
        prev_before = chars[position - 3].ch if position >= 3 else ""
        standalone = before.isascii() and before.isalpha() and not _is_ascii_word(prev_before)
        if standalone and _is_ascii_word(right):
            return True
    # "E | SIM"：切在空格之前（char 之间的空格也算一个字符）
    if right == " " and position + 1 < len(chars):
        after = chars[position + 1].ch
        prev = chars[position - 2].ch if position >= 2 else ""
        standalone = left.isascii() and left.isalpha() and not _is_ascii_word(prev)
        if standalone and _is_ascii_word(after):
            return True
    return False


def _cut_score(
    chars: list[TimedChar],
    position: int,
    pause_floor: float,
    gap_floor: float | None = None,
    word_starts_set: set[int] | None = None,
) -> float:
    """在 ``chars[position-1]`` 与 ``chars[position]`` 之间切一刀的分数。

    0 表示禁止切：劈开英文单词、把开括号留在上一行，都是不该发生的切点。
    """
    left = chars[position - 1]
    right = chars[position] if position < len(chars) else None

    if right is not None:
        # 不劈英文词：`E SIM` 这种单字母 + 词的写法最伤（FireRed 把 eSIM 拆成
        # E/SIM 两个 token，切在空格上就变成「国内的 E / SIM了」）。
        if _ascii_break_forbidden(chars, position):
            return 0.0
        # 虚词不能当行首，副词不能当行尾（真实素材：「…国内 / 的eSIM了」）。
        # 但标点本身就是天然边界，不做这条限制。
        if not (
            left.ch in STRONG_END or left.ch in WEAK_END or left.ch in CLOSERS
        ) and (right.ch in NO_LINE_START or left.ch in NO_LINE_END):
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
    # 空格**不算**切点：FireRed 会把 eSIM 这类词切成 `E`/`SIM` 两个 token（文本里
    # 也带空格），拿空格当弱切点就会切出「国内的 E / SIM了」这种把词劈成两半的字幕。
    # 纯英文长句仍由 `_hard_cut` 在词边界上兜底。
    weak = left.ch in WEAK_END
    # 两个口径都要看：
    # - 有 token 时间戳的引擎（SenseVoice）给的是「token 起始时间」，停顿表现为
    #   上一个 token 的时长拉长，用 pause_floor 判断；
    # - 按能量铺时间的引擎（FireRed）停顿表现为两个字符之间的空隙，用 gap_floor
    #   判断。混用一个门槛会把 0.12s 的真停顿判成「没有停顿」，只能硬切在词中间。
    floor = pause_floor if gap_floor is None else gap_floor
    paused = (left.end - left.start) >= pause_floor or (
        right is not None and (right.start - left.end) >= floor
    )

    if strong:
        return 3.0
    if paused:
        # 停顿落在词的中间时**不让切**：真停顿落在词中间本来就罕见，能检测到的
        # 多半是能量门限的抖动；宁可交给后面的词边界兜底，也不写「办 / 理」。
        # 只对中文字符要求词边界：英文由 `_ascii_break_forbidden` 守，jieba 对
        # 英文子串的切分不可信（会把 tribal 切成 trib / al）。
        if (
            word_starts_set
            and _is_cjk(left.ch)
            and right is not None
            and _is_cjk(right.ch)
            and position not in word_starts_set
        ):
            return 0.0
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
    gap_floor: float | None = None,
    word_starts_set: set[int] | None = None,
) -> int:
    """在 ``(start, limit]`` 里挑一个切点；挑不到就硬切，但尽量不劈英文。"""
    best_score = 0.0
    best_position = 0
    for position in range(start + 2, limit + 1):
        score = _cut_score(chars, position, pause_floor, gap_floor, word_starts_set)
        if score <= 0.0:
            continue
        # 标点切点不受最短字数限制（"好。"就该单独成条）；停顿/空格要求够长。
        if position - start < min_chars and score < 3.0:
            continue
        if score > best_score or (score == best_score and position > best_position):
            best_score = score
            best_position = position
    return best_position


def _extend_to_marks(
    chars: list[TimedChar],
    start: int,
    limit: int,
    *,
    extra_chars: int = 6,
    max_duration: float = 0.0,
    gap_floor: float | None = None,
    word_starts_set: set[int] | None = None,
) -> int:
    """窗口里没有切点、但标点就在后面几个字时，把这一条稍微放长。

    真实案例（FireRed + FireRedPunc）：一句 21 字的话，逗号在第 21 个字后，
    而 ``max_cue_chars=18``；硬切会切出「戏演得特 / 别好，」这种把词劈开的字幕。
    宁可这一条多 3 个字，也要停在逗号上。
    """
    # limit 已经是**绝对下标**；旧实现写成 start + limit + extra，等于把窗口
    # 又多放了一个 start，21 字的条会被拉到 39 字（FireRed 断句「别扭」的主因）。
    stop = min(len(chars), max(limit, 0) + max(1, extra_chars))
    for position in range(limit + 1, stop + 1):
        if position <= start + 1:
            continue
        if max_duration > 0 and (chars[position - 1].end - chars[start].start) > max_duration:
            break
        if (
            _cut_score(
                chars,
                position,
                pause_floor=1e9,
                gap_floor=gap_floor,
                word_starts_set=word_starts_set,
            )
            >= 1.0
        ):
            return position
    return 0


def _hard_cut(
    chars: list[TimedChar],
    start: int,
    limit: int,
    word_starts_set: set[int] | None = None,
) -> int:
    """实在没有标点/停顿可用时的兜底：优先词首，其次空格，最后才按字数硬切。

    jieba 的词边界在这里兜住「办 / 理」「手 / 机」这类事故；没有 jieba 时退化为
    「不劈英文单词」的旧口径。
    """
    best_safe = 0
    for position in range(limit, start + 1, -1):
        if position >= len(chars):
            continue
        left = chars[position - 1].ch
        right = chars[position].ch
        if right in STRONG_END or right in WEAK_END or right in CLOSERS:
            continue
        if not (left in STRONG_END or left in WEAK_END or left in CLOSERS) and (
            right in NO_LINE_START or left in NO_LINE_END
        ):
            continue
        if _ascii_break_forbidden(chars, position):
            continue
        if left == " ":
            return position
        if word_starts_set and _is_cjk(left) and _is_cjk(right) and position in word_starts_set:
            return position
        if not best_safe:
            best_safe = position
    if best_safe:
        return best_safe
    return max(start + 1, min(limit, len(chars)))


def _pick_strong_cut(chars: list[TimedChar], start: int) -> int:
    """窗口已经盖住整段剩余内容时，仍然在第一个句末标点后断开。

    一条字幕里塞进「两句完整的话」即使没超字数也读着别扭；但句内逗号不主动断，
    否则短句会被拆得七零八落。
    """
    for position in range(start + 2, len(chars)):
        if _cut_score(chars, position, pause_floor=1e9, gap_floor=1e9) >= 3.0:
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
    # 停顿切点的最短长度：太短会切出「说是那个卖 / 手机之前」这种碎条。
    # 句末标点不受这条限制（"好。"该单独成条）。
    min_chars = max(4, min(6, max_chars // 2))

    starts_set = word_starts("".join(char.ch for char in chars))

    durations = sorted(
        char.end - char.start for char in chars if char.ch.strip()
    )
    median_dur = durations[len(durations) // 2] if durations else 0.0
    # 空隙门槛用绝对秒数：按能量铺时间的引擎里，0.1–0.2s 的空隙就是真停顿。
    gap_floor = float(min_pause_s or 0.2)
    pause_floor = max(gap_floor, median_dur * 1.7)

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
            end_index = _pick_cut(
                chars, start_index, limit, min_chars, pause_floor, gap_floor, starts_set
            )
            if not end_index:
                end_index = _extend_to_marks(
                    chars,
                    start_index,
                    limit,
                    extra_chars=max(4, max_chars // 3),
                    max_duration=max_dur * 1.5,
                    gap_floor=gap_floor,
                    word_starts_set=starts_set,
                )
            if not end_index:
                end_index = _hard_cut(chars, start_index, limit, starts_set)

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
