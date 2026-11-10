"""音频覆盖审计：找出「字幕空白里还有像语音的声音」的区间。

这不是第二个转写引擎，也不回写字幕。它只回答一个主 VAD 回答不了的问题：

    “这条时间轴上，有没有一段明显不是静音、但完全没有字幕的音频？”

主 VAD 的漏检（VAD 没切到、模型根本没收到）不会产生任何 ``missed`` 记录，
所以质检队列必须有一条独立的、**不经过主 VAD 判决**的旁路。这里的做法是：

1. 先按字幕切出「空白间隙」（相邻字幕之间、片头片尾），只审计 >= 8s 的间隙；
2. 在间隙里算 20ms/40ms 的 RMS 包络，取全片 65 分位的能量阈值找连续发声段；
3. 对每个候选段做**局部峰值归一化**后再跑一次 Silero，只取概率均值/最大值；
4. 每个间隙只保留得分最高的一段，`vad_mean >= 0.20` 才进质检。

第 3 步是刻意的：全片 VAD 对这两句的最大概率只有 0.105 / 0.013，但把同一段
单独拉到 0.85 峰值后，概率会变成 1.000 / 0.965。主转写不应因此改变电平，
但审计可以——它只负责把这段翻出来给人听。

注意：这是启发式质检，不是“真值”。它的目标是**少漏**，不是零误报；所以
结果单独归为 ``coverage`` 组，和切片内的 ``missed/suspect/dropped`` 分开。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# 只审计足够长的空白。短于这个值的间隙更可能是正常停顿/换气，不值得刷屏。
DEFAULT_MIN_GAP_S = 8.0
# 候选发声段最短时长。低于 1.5s 的爆音/气口太多，先不报。
DEFAULT_MIN_RUN_S = 1.5
# 全片 RMS 分位阈值：65 分位在这类“轻声台词 + 大声喘息”的片子里刚好能把
# 轻声段和底噪分开；太高会漏，太低会把喘息/音乐全部放进来。
DEFAULT_ENERGY_PERCENTILE = 65.0
# 相邻能量块间隔小于这个值就合并，避免一句话被切成十几个碎片。
DEFAULT_MERGE_GAP_S = 0.5
# 每个间隙最多评估几个能量候选，按持续时间取前 N 个，控制审计耗时。
DEFAULT_MAX_CANDIDATES_PER_GAP = 4
# 局部归一化后 Silero 的平均概率门槛。7:41 实测 0.648，8:01 实测 0.282；
# 0.20 能同时留下两者，同时把大部分纯喘息/音乐挡在外面。
DEFAULT_MIN_LOCAL_VAD_MEAN = 0.20
DEFAULT_MIN_LOCAL_VAD_MAX = 0.60
# 一次质检最多展示多少条，避免长片刷出上百条。
DEFAULT_MAX_ITEMS = 20


@dataclass(slots=True)
class CoverageSpan:
    start: float
    end: float
    gap_start: float
    gap_end: float
    peak: float
    rms: float
    vad_mean: float
    vad_max: float
    score: float

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "dur": round(self.end - self.start, 2),
            "gap_start": round(self.gap_start, 3),
            "gap_end": round(self.gap_end, 3),
            "gap_dur": round(self.gap_end - self.gap_start, 2),
            "peak": round(self.peak, 4),
            "rms": round(self.rms, 5),
            "vad_mean": round(self.vad_mean, 3),
            "vad_max": round(self.vad_max, 3),
            "score": round(self.score, 3),
            "reason": "uncovered-energy",
            "rule": "audio-gap",
        }


def _cue_start(cue: Any) -> float:
    value = getattr(cue, "start", None)
    if value is None and isinstance(cue, dict):
        value = cue.get("start")
    return float(value or 0.0)


def _cue_end(cue: Any) -> float:
    value = getattr(cue, "end", None)
    if value is None and isinstance(cue, dict):
        value = cue.get("end")
    return float(value or 0.0)


def _rms_envelope(audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray, int]:
    """返回 (rms, frame_start_s, window_samples)。

    用累积平方和而不是 sliding_window_view：长片（2h）也不会铺开一个
    (frames × window) 的临时矩阵。
    """
    win = max(1, int(round(0.04 * sample_rate)))
    hop = max(1, int(round(0.02 * sample_rate)))
    if audio.size < win:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64), win
    energy = np.concatenate(([0.0], np.cumsum(np.asarray(audio, dtype=np.float64) ** 2)))
    n = (audio.size - win) // hop + 1
    starts = np.arange(n, dtype=np.int64) * hop
    sums = energy[starts + win] - energy[starts]
    rms = np.sqrt(np.maximum(sums, 0.0) / win)
    times = starts.astype(np.float64) / float(sample_rate)
    return rms, times, win


def _runs(mask: np.ndarray, times: np.ndarray, frame_s: float, merge_gap_s: float, min_run_s: float):
    """把布尔帧序列变成 [start, end) 秒区间，合并近距离碎片。"""
    if mask.size == 0:
        return []
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    raw: list[list[float]] = []
    for i in range(0, len(edges), 2):
        start = float(times[edges[i]])
        end = float(times[edges[i + 1] - 1] + frame_s)
        raw.append([start, end])

    merged: list[list[float]] = []
    for start, end in raw:
        if merged and start - merged[-1][1] <= merge_gap_s:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged if e - s >= min_run_s]


def _score_with_vad(audio: np.ndarray, model, sample_rate: int) -> tuple[float, float]:
    """对一段候选音频做局部峰值归一化，再跑 Silero，返回 (mean, max)。

    主 VAD 是整条音轨原样跑的；这里只看候选段，所以必须先归一化——这正
    是“全片峰值 0.832 导致轻声台词不归一化”的补偿。只用于审计，不回写。
    """
    if audio.size == 0:
        return 0.0, 0.0
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-7:
        return 0.0, 0.0
    chunk_audio = np.asarray(audio, dtype=np.float32) * (0.85 / peak)
    chunk_audio = np.clip(chunk_audio, -1.0, 1.0)

    try:
        import torch
    except Exception:  # pragma: no cover - torch 是运行期依赖，测试可注入假模型
        return 0.0, 0.0

    try:
        if hasattr(model, "reset_states"):
            model.reset_states()
        probs: list[float] = []
        for i in range(0, chunk_audio.size, 512):
            chunk = chunk_audio[i : i + 512]
            if chunk.size < 512:
                chunk = np.pad(chunk, (0, 512 - chunk.size))
            with torch.no_grad():
                out = model(torch.from_numpy(chunk), sample_rate)
            probs.append(float(out.item() if hasattr(out, "item") else out))
    except Exception:
        log.debug("覆盖审计局部 VAD 打分失败", exc_info=True)
        return 0.0, 0.0
    if not probs:
        return 0.0, 0.0
    arr = np.asarray(probs, dtype=np.float64)
    return float(arr.mean()), float(arr.max())


def find_coverage_spans(
    audio: np.ndarray,
    cues,
    vad_model=None,
    *,
    sample_rate: int = SAMPLE_RATE,
    time_offset: float = 0.0,
    min_gap_s: float = DEFAULT_MIN_GAP_S,
    min_run_s: float = DEFAULT_MIN_RUN_S,
    energy_percentile: float = DEFAULT_ENERGY_PERCENTILE,
    merge_gap_s: float = DEFAULT_MERGE_GAP_S,
    max_candidates_per_gap: int = DEFAULT_MAX_CANDIDATES_PER_GAP,
    min_local_vad_mean: float = DEFAULT_MIN_LOCAL_VAD_MEAN,
    min_local_vad_max: float = DEFAULT_MIN_LOCAL_VAD_MAX,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> list[dict]:
    """返回按优先级排序的未覆盖语音段；失败/无候选时返回 []。"""
    if audio is None or getattr(audio, "size", 0) == 0 or vad_model is None:
        return []
    try:
        audio = np.asarray(audio, dtype=np.float32)
        duration = float(audio.size) / float(sample_rate)
        if duration <= 0:
            return []

        intervals: list[tuple[float, float]] = []
        for cue in cues or []:
            start = max(0.0, _cue_start(cue) - float(time_offset))
            end = min(duration, _cue_end(cue) - float(time_offset))
            if end > start:
                intervals.append((start, end))
        intervals.sort(key=lambda item: item[0])

        # 把重叠/包含的字幕并成一条覆盖率，避免把同一块声音算多次。
        merged_cues: list[list[float]] = []
        for start, end in intervals:
            if merged_cues and start <= merged_cues[-1][1] + 0.05:
                merged_cues[-1][1] = max(merged_cues[-1][1], end)
            else:
                merged_cues.append([start, end])

        gaps: list[tuple[float, float]] = []
        cursor = 0.0
        for start, end in merged_cues:
            if start - cursor >= min_gap_s:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if duration - cursor >= min_gap_s:
            gaps.append((cursor, duration))
        if not gaps:
            return []

        rms, times, win_samples = _rms_envelope(audio, sample_rate)
        if rms.size == 0:
            return []
        frame_s = win_samples / float(sample_rate)
        # 只用全片分位会在“几乎恒定底噪”的间隙里把随机波动当成声音；
        # 再压一道底噪倍数，保证候选至少比本地底噪高 2.5 倍。
        threshold = max(
            float(np.percentile(rms, energy_percentile)),
            float(np.percentile(rms, 20)) * 2.5,
        )
        if not np.isfinite(threshold) or threshold <= 0:
            return []

        best: list[CoverageSpan] = []
        for gap_start, gap_end in gaps:
            lo = int(max(0.0, gap_start) * sample_rate)
            hi = int(min(duration, gap_end) * sample_rate)
            if hi - lo < int(min_run_s * sample_rate):
                continue
            mask = rms >= threshold
            # 只保留落在该间隙里的帧
            gap_mask = mask & (times >= gap_start) & (times < gap_end)
            runs = _runs(gap_mask, times, frame_s, merge_gap_s, min_run_s)
            if not runs:
                continue

            candidates: list[tuple[float, float, float, float]] = []
            for start, end in runs:
                a0 = int(max(0.0, start) * sample_rate)
                a1 = int(min(duration, end) * sample_rate)
                if a1 <= a0:
                    continue
                seg = audio[a0:a1]
                candidates.append(
                    (
                        start,
                        end,
                        end - start,
                        float(np.max(np.abs(seg))) if seg.size else 0.0,
                    )
                )
            # 时长优先：一句话通常比同间隙里的气口/爆音长。
            candidates.sort(key=lambda item: item[2], reverse=True)
            candidates = candidates[: max(1, int(max_candidates_per_gap))]

            gap_best: CoverageSpan | None = None
            for start, end, _, peak in candidates:
                a0 = int(max(0.0, start) * sample_rate)
                a1 = int(min(duration, end) * sample_rate)
                seg = audio[a0:a1]
                vad_mean, vad_max = _score_with_vad(seg, vad_model, sample_rate)
                if vad_mean < min_local_vad_mean or vad_max < min_local_vad_max:
                    continue
                rms_val = float(np.sqrt(np.mean(seg.astype(np.float64) ** 2))) if seg.size else 0.0
                gap_dur = max(0.1, (gap_end - gap_start))
                candidate = CoverageSpan(
                    start=start + float(time_offset),
                    end=end + float(time_offset),
                    gap_start=gap_start + float(time_offset),
                    gap_end=gap_end + float(time_offset),
                    peak=peak,
                    rms=rms_val,
                    vad_mean=vad_mean,
                    vad_max=vad_max,
                    # 长空白 + 强局部 VAD 优先：用户更该先听 20s 空白里的 3s 声音，
                    # 而不是 8s 空白里的 6s 喘息。
                    score=vad_mean * math.sqrt(gap_dur),
                )
                if gap_best is None or candidate.score > gap_best.score:
                    gap_best = candidate
            if gap_best is not None:
                best.append(gap_best)

        best.sort(key=lambda span: (-span.score, -span.vad_mean, -span.vad_max))
        return [span.to_dict() for span in best[: max(1, int(max_items))]]
    except Exception:
        log.debug("覆盖审计失败（不影响转写）", exc_info=True)
        return []
