"""音频感知的句首静音拉回（P0）。

问题：Anime Whisper 没有逐字时间轴，VAD 段起点只要带进 0.6–1.5s 的底噪/前导静音，
字幕就会“提前出现、拖得很长”。WhisperJAV 的 ``TimingAdjuster`` 用 ``文字数 / 7 CPS``
把 start 向 end 收，但它是纯文本的：对「えー…」这种合法长叹词会算出 0.3s，直接砍掉。

这里只做一件更保守的事：**保留 end，只把段首的静音拉掉**。判据不是纯 CPS，而是
音频里的“首个可信发声帧” + 四道文本/时长安全闸门：

- ``head_removed``：句首笑声已经被 ``_refine_bounds_by_pauses`` 挪过边界 → 跳过；
- 纯拟声/喘息（``is_nonverbal_only``）→ 跳过；
- 「…」开头且只有单/双假名 → 跳过（「…むぅ」「…んっ」很可能就是长叹词）；
  三字以上允许按音频证据拉回，省略号仍留在文本里；
- 单个/两个假名的短叹词：阈值提高到 0.8s、最多拉 40%、保底 0.8s，避免「えー？」被砍。

模块只依赖 numpy，不 import torch / transcribe，因此可以在纯函数测试里直接跑。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000

# 触发拉回的最低句首静音。0.6s 是 Test 2 实测里有 13 条落在 0.6–0.89s 的区间；
# 0.55 留 50ms 给 RMS 帧边界误差。
MIN_LEAD_S = 0.55
# 单/双假名是正常台词（「え？」「ん…」），不能按普通句子的阈值处理。
SHORT_TEXT_MAX_CHARS = 2
SHORT_TEXT_MIN_LEAD_S = 0.80
SHORT_TEXT_MAX_PULL_RATIO = 0.40
SHORT_TEXT_MIN_DURATION_S = 0.80

# 普通句子：只修“看起来就慢”的条。CPS >= 3.0 且 <= 4.2s 的条不动——
# 实证里这类条多半是时间分配正常，硬拉会把句中停顿吃掉。
MIN_DURATION_S = 1.20
CPS_FLOOR = 3.0
LONG_CUE_S = 4.2
MAX_PULL_RATIO = 0.60
MIN_NEW_DURATION_S = 0.60
PRE_ROLL_S = 0.05
MIN_PULL_S = 0.15
OVERLAP_GAP_S = 0.05

# 句首是这些字符时，说明说话人/字幕本来就要留一个停顿。
_LEADING_PAUSE_PREFIXES = ("…", "‥", "、", "。")


@dataclass(frozen=True, slots=True)
class PullResult:
    """一次段首拉回的决策结果。``pulled=False`` 时 ``start`` 原样返回。"""

    start: float
    pulled: bool
    reason: str
    lead_s: float = 0.0
    pull_s: float = 0.0


def _frame_rms(audio: np.ndarray, frame: int, hop: int) -> np.ndarray:
    """逐帧 RMS（float32）。分块计算，避免长片一次性铺开 (frames × frame) 临时矩阵。"""
    data = np.asarray(audio, dtype=np.float32)
    if data.size < frame or frame <= 0 or hop <= 0:
        return np.zeros(0, dtype=np.float32)
    count = 1 + (data.size - frame) // hop
    out = np.empty(count, dtype=np.float32)
    block = 4096
    for start in range(0, count, block):
        stop = min(count, start + block)
        offsets = np.arange(start, stop, dtype=np.int64) * hop
        windows = data[offsets[:, None] + np.arange(frame, dtype=np.int64)[None, :]]
        out[start:stop] = np.sqrt(np.mean(np.square(windows, dtype=np.float64), axis=1))
    return out


def estimate_noise_floor(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    """全片 10ms 帧 RMS 的 20 分位，作为“底噪”估计。

    与评测脚本的口径一致：``max(底噪×3, 段内峰值×6%)``。全片 2 小时约 72 万帧，
    分块计算，耗时可忽略；只在启用拉回时调用一次。
    """
    frame = max(1, int(round(sample_rate * 0.010)))
    rms = _frame_rms(audio, frame, frame)
    if rms.size == 0:
        return 0.0
    return float(np.quantile(rms, 0.20))


def leading_silence_seconds(
    audio: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    *,
    noise_floor: float = 0.0,
    frame_ms: float = 10.0,
    threshold_factor: float = 3.0,
    peak_ratio: float = 0.06,
    consecutive: int = 2,
) -> float:
    """返回段首“没有可信发声”的秒数；整段无声时返回 0（不触发拉回）。

    判据是 10ms RMS 连续 ``consecutive`` 帧超过 ``max(底噪×3, 峰值×6%)``。
    单帧爆音/点击不会被当成发声起点；这正是不用“首个非零帧”的原因。
    """
    data = np.asarray(audio, dtype=np.float32)
    frame = max(1, int(round(sample_rate * frame_ms / 1000.0)))
    rms = _frame_rms(data, frame, frame)
    if rms.size == 0:
        return 0.0
    peak = float(rms.max())
    if peak <= 1e-8:
        return 0.0
    threshold = max(float(noise_floor) * threshold_factor, peak * peak_ratio)
    above = rms >= threshold
    if not above.any():
        return 0.0
    consecutive = max(1, int(consecutive))
    if consecutive > 1:
        if above.size < consecutive:
            return 0.0
        runs = np.convolve(above.astype(np.int8), np.ones(consecutive, dtype=np.int8), mode="valid")
        hits = np.flatnonzero(runs >= consecutive)
        if hits.size == 0:
            return 0.0
        first = int(hits[0])
    else:
        first = int(np.flatnonzero(above)[0])
    return first * (frame / float(sample_rate))


def _starts_with_pause(text: str) -> bool:
    return str(text or "").lstrip().startswith(_LEADING_PAUSE_PREFIXES)


def _chars(text: str) -> int:
    """有效字数：去掉首尾省略号/顿号/空白，避免把「…」算成台词。"""
    body = str(text or "").strip("…‥、。 \t")
    return len("".join(body.split()))


def plan_start_pull(
    *,
    start: float,
    end: float,
    lead_s: float,
    text: str,
    prev_end: float | None = None,
    head_removed: bool = False,
    nonverbal: bool = False,
) -> PullResult:
    """决定是否把段起点向右拉，返回新起点（end 永远不变）。

    纯函数：不碰音频、不碰模型；所有阈值都在本模块顶部，便于 A/B 与单测。
    """
    start = float(start)
    end = float(end)
    duration = end - start
    lead = max(0.0, float(lead_s))
    chars = _chars(text)

    if duration <= 0:
        return PullResult(start, False, "no-audio", lead)
    if head_removed:
        return PullResult(start, False, "head-removed", lead)
    if nonverbal:
        return PullResult(start, False, "nonverbal", lead)
    # 「…」开头本身是语义（停顿/拖长），但只在单/双假名时把它当保护闸门：
    # 这类「…むぅ」「…んっ」很可能就是长叹词，强行拉会砍掉起音。
    # 三字以上的「…お熱あかろっか」允许按音频证据拉回——省略号仍留在文本里，
    # 只是字幕不再提前 0.8s 出现。
    if _starts_with_pause(text) and chars <= SHORT_TEXT_MAX_CHARS:
        return PullResult(start, False, "pause-prefix", lead)
    if lead <= 0:
        return PullResult(start, False, "no-lead", lead)

    min_lead = SHORT_TEXT_MIN_LEAD_S if chars <= SHORT_TEXT_MAX_CHARS else MIN_LEAD_S
    if lead < min_lead:
        return PullResult(start, False, "short-lead", lead)
    if duration < MIN_DURATION_S:
        return PullResult(start, False, "short-duration", lead)

    cps = chars / duration if duration > 0 else 0.0
    if cps >= CPS_FLOOR and duration <= LONG_CUE_S:
        return PullResult(start, False, "not-slow", lead)

    new_start = start + lead - PRE_ROLL_S
    if chars <= SHORT_TEXT_MAX_CHARS:
        # 短叹词：最多拉 40%，且保底 0.8s，不让「えー？」变成 0.2s 的闪条。
        new_start = min(new_start, start + duration * SHORT_TEXT_MAX_PULL_RATIO)
        new_start = min(new_start, end - SHORT_TEXT_MIN_DURATION_S)
    else:
        new_start = min(new_start, start + duration * MAX_PULL_RATIO)
        new_start = min(new_start, end - max(MIN_NEW_DURATION_S, duration * 0.35))

    if prev_end is not None:
        new_start = max(new_start, float(prev_end) + OVERLAP_GAP_S)
    new_start = max(new_start, start)

    min_duration = (
        SHORT_TEXT_MIN_DURATION_S if chars <= SHORT_TEXT_MAX_CHARS else MIN_NEW_DURATION_S
    )
    if end - new_start < min_duration:
        return PullResult(start, False, "too-small", lead)
    pull = new_start - start
    if pull < MIN_PULL_S:
        return PullResult(start, False, "too-small", lead)
    return PullResult(round(new_start, 3), True, "pulled", lead, round(pull, 3))


def empty_stats(*, enabled: bool = True) -> dict:
    """报告/测试共用的计数器形状；``reason`` 是稳定的英文键。"""
    return {
        "enabled": bool(enabled),
        "considered": 0,
        "pulled": 0,
        "total_pull_s": 0.0,
        "max_pull_s": 0.0,
        "head_removed": 0,
        "nonverbal": 0,
        "pause_prefix": 0,
        "no_lead": 0,
        "short_lead": 0,
        "short_duration": 0,
        "not_slow": 0,
        "too_small": 0,
    }


def record(stats: dict, result: PullResult) -> None:
    """把一次决策累加进 stats（原地修改）。"""
    if not stats:
        return
    stats["considered"] = int(stats.get("considered", 0)) + 1
    reason = str(result.reason or "")
    if reason == "pulled":
        stats["pulled"] = int(stats.get("pulled", 0)) + 1
        stats["total_pull_s"] = round(
            float(stats.get("total_pull_s", 0.0)) + float(result.pull_s), 3
        )
        stats["max_pull_s"] = round(
            max(float(stats.get("max_pull_s", 0.0)), float(result.pull_s)), 3
        )
    else:
        key = reason.replace("-", "_")
        if key in stats:
            stats[key] = int(stats.get(key, 0)) + 1


def describe_stats(stats: dict | None) -> str:
    """一句话报告文案；没有触发时也要能说清“检查过但没动”。"""
    data = stats or {}
    if not data:
        return "未启用"
    if not data.get("enabled", True):
        return "未启用"
    considered = int(data.get("considered", 0) or 0)
    pulled = int(data.get("pulled", 0) or 0)
    if not pulled:
        return f"未触发（检查 {considered} 段）"
    avg = float(data.get("total_pull_s", 0.0) or 0.0) / max(1, pulled)
    skipped = (
        int(data.get("head_removed", 0) or 0)
        + int(data.get("nonverbal", 0) or 0)
        + int(data.get("pause_prefix", 0) or 0)
        + int(data.get("short_lead", 0) or 0)
        + int(data.get("short_duration", 0) or 0)
        + int(data.get("not_slow", 0) or 0)
        + int(data.get("no_lead", 0) or 0)
        + int(data.get("too_small", 0) or 0)
    )
    return (
        f"拉回 {pulled}/{considered} 段 ｜ 平均 {avg * 1000:.0f}ms"
        f" ｜ 最大 {float(data.get('max_pull_s', 0.0) or 0.0) * 1000:.0f}ms"
        f" ｜ 跳过 {skipped} 段"
    )
