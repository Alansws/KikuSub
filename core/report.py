"""转写任务详报的纯文本生成（无 UI 依赖）。

从 `app.py` 原样搬出：这些函数只吃数据、吐字符串，与 Gradio 无关，
所以服务层与旧界面可以共用同一份实现，避免两边文案与口径漂移。

对外主入口：`build_transcription_report()` 返回可直接展示的纯文本报告；
HTML 渲染仍在界面层（`app.render_report_panel` / 未来的前端组件）。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from .paths import OUTPUT_DIR
from .subtitles import format_duration, format_srt_timestamp

MISSED_REASON_LABELS = {
    "empty-after-retry": "重试后仍为空",
    "retry-suspicious": "重试结果不可信",
}

# 幻觉复核的判据标签（transcribe.hallucination_risk_reason 的返回值）
HALLUCINATION_RULE_LABELS = {
    "repeat": "重复复读",
    "short": "短段复核",
    "low-density": "低密度",
}

# 明细最多列这么多条，其余折叠成一行，避免长片把报告刷成流水账
HALLUCINATION_SPAN_LIMIT = 50

# E5：漏句告警的展示下限。模型对「VAD 判成语音、实际是底噪/静音」的段同样返回空，
# 这类记录是纯噪声（实测两条的 RMS 处于全片 VAD 段的第 5/6 百分位，参考字幕此处无台词）。
# 阈值以下只在 JSON 里留档，不进报告、不在状态行里喊。
MISSED_MIN_PEAK = 0.02


def _span_peak(span: dict) -> float:
    """记录的峰值；老版本 JSON 没有 peak 字段时按「有声音」处理，保持向后兼容。"""
    try:
        return float(span.get("peak", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _visible_missed_spans(spans: list[dict] | None) -> list[dict]:
    """报告/状态行里实际展示的漏句记录：滤掉近乎无声的误报。"""
    return [s for s in (spans or []) if _span_peak(s) >= MISSED_MIN_PEAK]


def _missed_hidden_count(spans: list[dict] | None) -> int:
    return len(spans or []) - len(_visible_missed_spans(spans))


def _missed_reason_label(reason: str) -> str:
    key = str(reason or "")
    return MISSED_REASON_LABELS.get(key, key or MISSED_REASON_LABELS["empty-after-retry"])


def _fmt_report_time(seconds) -> str:
    return format_srt_timestamp(max(0.0, float(seconds or 0.0))).replace(",", ".")


def _missed_spans_headline(spans: list[dict] | None) -> str:
    if not spans:
        return "未发现"
    total = sum(float(span.get("dur", 0.0) or 0.0) for span in spans)
    return f"共 {len(spans)} 处 / {total:.1f} 秒"


def missed_json_path(media_path: Path, slice_tag: str = "") -> Path:
    return OUTPUT_DIR / f"{Path(media_path).stem}{slice_tag}.missed.json"


def _hallucination_rule_label(rule: str) -> str:
    key = str(rule or "")
    return HALLUCINATION_RULE_LABELS.get(key, key or "可疑")


def _hallucination_rows(spans: list[dict], verdict: str) -> list[str]:
    """把同一结论（dropped / suspect）的复核记录渲染成报告明细行。"""
    picked = [s for s in spans if str(s.get("verdict", "")) == verdict]
    rows: list[str] = []
    for span in picked[:HALLUCINATION_SPAN_LIMIT]:
        peak_txt = f"  峰值 {_span_peak(span):.3f}" if "peak" in span else ""
        text = " ".join(str(span.get("text", "")).split())
        rows.append(
            f"• {_fmt_report_time(span.get('start', 0.0))} → {_fmt_report_time(span.get('end', 0.0))}"
            f"  ({float(span.get('dur', 0.0) or 0.0):.2f}s)  {_hallucination_rule_label(span.get('rule', ''))}"
            f"{peak_txt}  「{text}」"
        )
    if len(picked) > HALLUCINATION_SPAN_LIMIT:
        rows.append(
            f"• … 另有 {len(picked) - HALLUCINATION_SPAN_LIMIT} 段未列出"
            f"（仅展示前 {HALLUCINATION_SPAN_LIMIT} 段）"
        )
    return rows


def _cut_snap_summary(stats: dict | None) -> str:
    """报告里说明本次是否真的发生过强制切分与能量谷吸附。"""
    if not stats:
        return "无强制切分（未触发，属正常）"
    forced = int(stats.get("forced_cuts", 0) or 0)
    snapped = int(stats.get("snapped_cuts", 0) or 0)
    shift = float(stats.get("shift_s", 0.0) or 0.0)
    max_block = float(stats.get("max_block_s", 0.0) or 0.0)
    if forced <= 0:
        return f"无强制切分（最长连续语音块 {max_block:.1f}s，未超过单段上限）"
    if snapped <= 0:
        return f"{forced} 处强制切分，均未找到显著能量谷（连续说话），保持原切点"
    return f"{forced} 处强制切分，其中 {snapped} 处吸附到能量谷（累计前移 {shift:.2f}s）"


def _align_stats_headline(stats: dict | None, is_qwen: bool) -> str:
    """【逐字对齐】一行摘要：把"40ms 精度"从宣传语变成可核对的数字。"""
    if not is_qwen:
        return "该引擎无逐字对齐，句内时间按字数比例分配"
    if not stats or not stats.get("segments"):
        return "未记录（本次未产出对齐统计）"
    if not stats.get("enabled", True):
        return "逐字对齐已停用（本次按字数比例分配时间）"

    total = int(stats.get("segments", 0) or 0)
    aligned = int(stats.get("aligned", 0) or 0)
    noop = int(stats.get("noop", 0) or 0)
    degraded = int(stats.get("degraded", 0) or 0)
    empty = int(stats.get("empty", 0) or 0)
    align_chars = int(stats.get("align_chars", 0) or 0)
    interp = int(stats.get("interp_chars", 0) or 0)
    rate = (aligned / total * 100) if total else 0.0

    parts = [
        f"共 {total} 段：✅ {aligned} 段完成（{rate:.1f}%）",
        f"○ 无需对齐 {noop} 段",
        f"⚠️ 降级 {degraded} 段",
    ]
    if empty > 0:
        parts.append(f"✕ 空结果 {empty} 段（已计入疑似漏句）")
    if align_chars > 0:
        parts.append(f"字级插值 {interp}/{align_chars} 字（{interp / align_chars * 100:.1f}%）")
    truncated = int(stats.get("truncated", 0) or 0)
    if truncated > 0:
        parts.append(f"生成截断 {truncated} 段")
    capped_repeat = int(stats.get("capped_repeat", 0) or 0)
    if capped_repeat > 0:
        parts.append(f"复读吃满上限 {capped_repeat} 段（非截断，已跳过重跑）")
    return "｜".join(parts)


def write_missed_report(media_path, slice_tag: str, engine_key_name: str, spans: list[dict] | None) -> Path | None:
    """落盘疑似漏句清单；无漏句时清掉同名旧文件，避免误导核对台提示。"""
    path = missed_json_path(media_path, slice_tag)
    if not spans:
        try:
            path.unlink()
        except OSError:
            pass
        return None

    payload = {
        "media": Path(media_path).name,
        "engine": engine_key_name,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "spans": spans,
    }
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return None
    return path


def load_missed_spans(stem: str) -> list[dict]:
    """读取与该媒体主干同名的漏句清单（含时间切片版本），供核对台状态行提示。"""
    if not stem or not OUTPUT_DIR.exists():
        return []
    spans: list[dict] = []
    for path in OUTPUT_DIR.iterdir():
        name = path.name
        if not name.endswith(".missed.json"):
            continue
        base = name[: -len(".missed.json")]
        if base != stem and not base.startswith(f"{stem}_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for span in data.get("spans") or []:
            if isinstance(span, dict):
                spans.append(span)
    spans.sort(key=lambda item: float(item.get("start", 0.0) or 0.0))
    return spans


def overview_pairs(
    *,
    media_name: str,
    time_slice_desc: str,
    out_filename: str,
    out_path: str,
    engine_name: str,
    output_format: str,
    duration_str: str,
    cue_count: int,
    char_count: int,
    is_interrupted: bool,
    finish_time: str,
) -> list[tuple[str, str]]:
    """【任务概览】的字段对。文本报告与 JSON 报告共用，避免两套口径。"""
    return [
        ("媒体源文件", media_name),
        ("处理时间段", time_slice_desc),
        ("字幕文件名", out_filename),
        ("保存完整路径", out_path),
        ("识别引擎", engine_name),
        ("输出格式", output_format),
        ("转录耗时", duration_str),
        ("字幕统计", f"共 {cue_count} 条字幕 ｜ 总计 {char_count} 字符"),
        ("执行状态", "⚠️ 用户中途打断 (保存部分字幕)" if is_interrupted else "✅ 全部完成"),
        ("归档时间", finish_time),
    ]


def param_pairs(
    *,
    is_qwen: bool,
    config: object,
    ngram: int,
    penalty: float,
    use_alignment: bool,
) -> list[tuple[str, str]]:
    """【执行生效参数清单】的字段对。"""
    if is_qwen:
        return [
            ("识别方案", "Qwen3-ASR (JA Anime/Galgame) + CTC 对齐"),
            ("VAD 语音检测阈值 (vad_threshold)", getattr(config, "vad_threshold", 0.30)),
            ("最短语音长度 (vad_min_speech_ms)", f"{getattr(config, 'vad_min_speech_ms', 100)} ms"),
            ("判定为停顿的静音 (vad_min_silence_ms)", f"{getattr(config, 'vad_min_silence_ms', 200)} ms"),
            ("切片首尾留白缓冲 (vad_speech_pad_ms)", f"{getattr(config, 'vad_speech_pad_ms', 150)} ms"),
            ("相邻片段合并间隔 (merge_gap_s)", f"{getattr(config, 'merge_gap_s', 0.5)} s"),
            ("单次送模音频窗口 (max_segment_s)", f"{getattr(config, 'max_segment_s', 16.0)} s"),
            ("单条字幕目标时长 (max_cue_dur)", f"{getattr(config, 'max_cue_dur', 4.3)} s"),
            ("单条字幕最大字数 (max_cue_chars)", f"{getattr(config, 'max_cue_chars', 21)} 字"),
            ("视为停顿静音长度 (min_pause_s)", f"{getattr(config, 'min_pause_s', 0.12)} s"),
            ("字幕前后留白 (cue_pad_s)", f"{getattr(config, 'cue_pad_start_s', 0.12)} s"),
            ("CTC 逐字发声帧对齐 (use_alignment)", "启用" if use_alignment else "停用"),
            ("动态响度归一化 (enable_loudnorm)", "启用" if getattr(config, "enable_loudnorm", True) else "停用"),
        ]
    return [
        ("识别方案", "Anime Whisper (litagin/anime-whisper)"),
        ("智能句级分切 (enable_sentence_split)", "启用" if getattr(config, "enable_sentence_split", True) else "停用"),
        ("动态响度归一化 (enable_loudnorm)", "启用" if getattr(config, "enable_loudnorm", False) else "停用"),
        ("VAD 语音判定阈值 (threshold)", getattr(config, "threshold", 0.30)),
        ("最短语音片段 (min_speech_ms)", f"{getattr(config, 'min_speech_ms', 120)} ms"),
        ("判定停顿静音 (min_silence_ms)", f"{getattr(config, 'min_silence_ms', 150)} ms"),
        ("首尾留白缓冲 (speech_pad_ms)", f"{getattr(config, 'speech_pad_ms', 200)} ms"),
        ("相邻片段合并间隔 (merge_gap_s)", f"{getattr(config, 'merge_gap_s', 0.3)} s"),
        ("单次送模最长秒数 (max_segment_s)", f"{getattr(config, 'max_segment_s', 12.0)} s"),
        ("合并后最短片段 (min_speech_s)", f"{getattr(config, 'min_speech_s', 0.08)} s"),
        ("字幕首尾外扩留白 (cue_pad_s)", f"{getattr(config, 'cue_pad_s', 0.02)} s"),
        ("重复抑制 n-gram (no_repeat_ngram_size)", str(ngram)),
        ("重复惩罚因子 (repetition_penalty)", str(penalty)),
    ]


def build_transcription_report(
    media_name: str,
    out_filename: str,
    out_path: str,
    engine_name: str,
    output_format: str,
    elapsed_time: float,
    cue_count: int,
    char_count: int,
    is_qwen: bool,
    config: object,
    is_interrupted: bool = False,
    time_slice_desc: str = "全片完整转录",
    ngram: int = 5,
    penalty: float = 1.15,
    use_alignment: bool = True,
    missed_spans: list[dict] | None = None,
    segment_stats: dict | None = None,
    align_stats: dict | None = None,
) -> str:
    finish_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    duration_str = format_duration(elapsed_time)

    lines = [
        "============================================================",
        "🎬 日语影片字幕转录任务详报 (Transcription Report)",
        "============================================================",
        "【任务概览】",
        *[f"• {label}：{value}" for label, value in overview_pairs(
            media_name=media_name,
            time_slice_desc=time_slice_desc,
            out_filename=out_filename,
            out_path=out_path,
            engine_name=engine_name,
            output_format=output_format,
            duration_str=duration_str,
            cue_count=cue_count,
            char_count=char_count,
            is_interrupted=is_interrupted,
            finish_time=finish_time,
        )],
        "",
        "【执行生效参数清单】",
        *[f"• {label}：{value}" for label, value in param_pairs(
            is_qwen=is_qwen, config=config, ngram=ngram,
            penalty=penalty, use_alignment=use_alignment,
        )],
    ]

    visible_missed = _visible_missed_spans(missed_spans)
    hidden = _missed_hidden_count(missed_spans)
    hallucination_drops = int((segment_stats or {}).get("hallucination_drops", 0) or 0)
    suspect_cues = int((segment_stats or {}).get("suspect_cues", 0) or 0)
    hallucination_spans = list((segment_stats or {}).get("hallucination_spans") or [])

    # 先用一句「人话」把三类问题放到同一张速览里，再接原来的明细。
    # 用户不需要先理解 VAD / 幻觉 / 复核这些术语，也能知道下一步做什么。
    quality_parts = [f"🔍 可能漏句 {len(visible_missed)} 处"]
    if not is_qwen:
        quality_parts.append(f"✂️ 误删待核 {hallucination_drops} 段")
        quality_parts.append(f"👂 短句待确认 {suspect_cues} 段")
    lines.append("【质检速览】" + " ｜ ".join(quality_parts))
    if len(visible_missed) or hallucination_drops or suspect_cues:
        lines.append(
            "• 已生成可交互队列：页面上方 / 右下角「🔎 质检待核队列」可逐条试听、定位、补录、确认；"
            "本报告保留为归档与一键复制用。"
        )
    else:
        lines.append(
            "• 本次没有需要人工试听复核的片段；「🔎 质检待核队列」仍会保留入口，"
            "可随时打开查看三类检查的说明。"
        )
    if is_qwen:
        # Qwen 路径没有时间戳复核这一步：明确写「不启用」，避免 0 条被读成「复查过且干净」。
        lines.append(
            "• 引擎差异：Qwen3-ASR 只执行「🔍 可能漏句」检查；"
            "「✂️ 误删待核 / 👂 短句待确认」依赖 Anime Whisper 的时间戳复核，本引擎不启用。"
        )
    lines.append(
        "• 队列入口常驻右下角「🔎 质检」：0 处待核时显示为「✅ 质检完成」，不会因为队列为空而消失。"
    )

    lines.append(
        "【疑似漏句区间】" + _missed_spans_headline(visible_missed)
        + ("（有声音、但两次识别都为空 → 建议试听补录）" if visible_missed else "")
    )
    if visible_missed:
        for span in visible_missed:
            # 老记录没有 peak 字段：不显示假的 1.000，避免读成「这段很响」
            peak_txt = f"  峰值 {_span_peak(span):.3f}" if "peak" in span else ""
            lines.append(
                f"• {_fmt_report_time(span.get('start', 0.0))} → {_fmt_report_time(span.get('end', 0.0))}"
                f"  ({float(span.get('dur', 0.0)):.2f}s)  {_missed_reason_label(span.get('reason', ''))}"
                f"{peak_txt}"
            )
    else:
        lines.append("• 未发现")
    if hidden:
        lines.append(
            f"• 另有 {hidden} 处峰值低于 {MISSED_MIN_PEAK} 的近静音段未展示"
            f"（多为配乐/底噪误判，已留在 .missed.json 备查）"
        )
    lines.append("【切分点吸附】" + _cut_snap_summary(segment_stats))
    dropped_rows = _hallucination_rows(hallucination_spans, "dropped")
    suspect_rows = _hallucination_rows(hallucination_spans, "suspect")
    if is_qwen:
        # Qwen 路径没有时间戳复核这一步：不写“未发现”，避免读成“复核过且干净”
        lines.append("【幻觉门控】该引擎不启用（仅 Anime Whisper 做时间戳复核）")
    else:
        lines.append(
            "【幻觉门控】"
            + (
                f"已丢弃 {hallucination_drops} 段经时间戳复核为空的疑似幻觉"
                "（识别出过文字但复核为空，多为脑补；若你听到台词请点「恢复原句」补回）"
                if hallucination_drops
                else "未触发（没有段落复核为空被删）"
            )
        )
        lines.extend(dropped_rows)
        lines.append(
            "【幻觉复核】"
            + (
                f"{suspect_cues} 段短/低密度结果未被丢弃，建议人工核对"
                "（字幕已保留，听一遍确认保留或删除即可）"
                if suspect_cues
                else "未触发（无短段/低密度结果需要复核）"
            )
        )
        lines.extend(suspect_rows)

    headline = _align_stats_headline(align_stats, is_qwen)
    if is_interrupted and is_qwen and align_stats:
        headline += "（统计截至中断处）"
    lines.append("【逐字对齐】" + headline)

    degraded_spans = list((align_stats or {}).get("spans") or [])
    for span in degraded_spans:
        lines.append(
            f"• {_fmt_report_time(span.get('start', 0.0))} → {_fmt_report_time(span.get('end', 0.0))}"
            f"  ({float(span.get('dur', 0.0)):.2f}s)  {span.get('reason', 'unknown')}"
            f"  {int(span.get('chars', 0) or 0)} 字"
        )
    total_degraded = int((align_stats or {}).get("degraded", 0) or 0)
    if total_degraded > len(degraded_spans):
        lines.append(f"• … 另有 {total_degraded - len(degraded_spans)} 段降级未列出（仅展示前 50 段）")
    elif is_qwen and align_stats and align_stats.get("enabled", True) and total_degraded == 0:
        lines.append("• 无降级段")

    lines.append("============================================================")
    return "\n".join(lines)


def build_report_data(
    media_name: str,
    out_filename: str,
    out_path: str,
    engine_name: str,
    output_format: str,
    elapsed_time: float,
    cue_count: int,
    char_count: int,
    is_qwen: bool,
    config: object,
    is_interrupted: bool = False,
    time_slice_desc: str = "全片完整转录",
    ngram: int = 5,
    penalty: float = 1.15,
    use_alignment: bool = True,
    missed_spans: list[dict] | None = None,
    segment_stats: dict | None = None,
    align_stats: dict | None = None,
) -> dict:
    """与 `build_transcription_report` 同参数，但返回**结构化数据**。

    改造规划 §4 的要求：「`render_report_panel` 全部改为返回 JSON，渲染交给前端」。
    新前端拿 `overview` / `params` 渲染指标胶囊，拿 `sections` 渲染明细列表；
    `raw_text` 保留纯文本，供「一键复制」与归档使用，与旧界面逐字一致。

    字段口径与文本报告完全同源（`overview_pairs` / `param_pairs` / 各 `_xxx` 助手），
    所以不会出现「网页和报告对不上」。
    """
    raw_text = build_transcription_report(
        media_name=media_name,
        out_filename=out_filename,
        out_path=out_path,
        engine_name=engine_name,
        output_format=output_format,
        elapsed_time=elapsed_time,
        cue_count=cue_count,
        char_count=char_count,
        is_qwen=is_qwen,
        config=config,
        is_interrupted=is_interrupted,
        time_slice_desc=time_slice_desc,
        ngram=ngram,
        penalty=penalty,
        use_alignment=use_alignment,
        missed_spans=missed_spans,
        segment_stats=segment_stats,
        align_stats=align_stats,
    )

    visible_missed = _visible_missed_spans(missed_spans)
    hidden = _missed_hidden_count(missed_spans)
    stats = segment_stats or {}
    dropped = int(stats.get("hallucination_drops", 0) or 0)
    suspect = int(stats.get("suspect_cues", 0) or 0)
    hallucination_spans = list(stats.get("hallucination_spans") or [])
    degraded = list((align_stats or {}).get("spans") or [])
    total_degraded = int((align_stats or {}).get("degraded", 0) or 0)

    quality_parts = [f"🔍 可能漏句 {len(visible_missed)} 处"]
    if not is_qwen:
        quality_parts.append(f"✂️ 误删待核 {dropped} 段")
        quality_parts.append(f"👂 短句待确认 {suspect} 段")

    sections: list[dict] = [
        {
            "id": "missed",
            "title": "疑似漏句区间",
            "headline": _missed_spans_headline(visible_missed),
            "note": "有声音、但两次识别都为空 → 建议试听补录" if visible_missed else "",
            "empty_text": "未发现",
            "hidden": hidden,
            "hidden_text": (
                f"另有 {hidden} 处峰值低于 {MISSED_MIN_PEAK} 的近静音段未展示"
                "（多为配乐/底噪误判，已留在 .missed.json 备查）"
            )
            if hidden
            else "",
            "items": [
                {
                    "start": float(span.get("start", 0.0) or 0.0),
                    "end": float(span.get("end", 0.0) or 0.0),
                    "dur": float(span.get("dur", 0.0) or 0.0),
                    "time_text": (
                        f"{_fmt_report_time(span.get('start', 0.0))} → "
                        f"{_fmt_report_time(span.get('end', 0.0))}"
                    ),
                    "reason": str(span.get("reason", "") or ""),
                    "reason_text": _missed_reason_label(span.get("reason", "")),
                    "peak": _span_peak(span) if "peak" in span else None,
                }
                for span in visible_missed
            ],
        },
        {
            "id": "cut_snap",
            "title": "切分点吸附",
            "headline": _cut_snap_summary(segment_stats),
            "items": [],
        },
    ]

    if is_qwen:
        sections.append(
            {
                "id": "hallucination",
                "title": "幻觉门控 / 复核",
                "headline": "该引擎不启用（仅 Anime Whisper 做时间戳复核）",
                "disabled": True,
                "items": [],
            }
        )
    else:
        for section_id, title, verdict, count, empty_text in (
            (
                "hallucination_dropped",
                "幻觉门控",
                "dropped",
                dropped,
                "未触发（没有段落复核为空被删）",
            ),
            (
                "hallucination_suspect",
                "幻觉复核",
                "suspect",
                suspect,
                "未触发（无短段/低密度结果需要复核）",
            ),
        ):
            rows = [s for s in hallucination_spans if str(s.get("verdict", "")) == verdict]
            sections.append(
                {
                    "id": section_id,
                    "title": title,
                    "headline": (
                        f"{count} 段"
                        + ("经时间戳复核为空被丢弃" if verdict == "dropped" else "短/低密度结果待人工核对")
                    )
                    if count
                    else empty_text,
                    "count": count,
                    "truncated": max(0, len(rows) - HALLUCINATION_SPAN_LIMIT),
                    "items": [
                        {
                            "start": float(span.get("start", 0.0) or 0.0),
                            "end": float(span.get("end", 0.0) or 0.0),
                            "dur": float(span.get("dur", 0.0) or 0.0),
                            "time_text": (
                                f"{_fmt_report_time(span.get('start', 0.0))} → "
                                f"{_fmt_report_time(span.get('end', 0.0))}"
                            ),
                            "rule": str(span.get("rule", "") or ""),
                            "rule_text": _hallucination_rule_label(span.get("rule", "")),
                            "peak": _span_peak(span) if "peak" in span else None,
                            "text": " ".join(str(span.get("text", "")).split()),
                        }
                        for span in rows[:HALLUCINATION_SPAN_LIMIT]
                    ],
                }
            )

    align_headline = _align_stats_headline(align_stats, is_qwen)
    if is_interrupted and is_qwen and align_stats:
        align_headline += "（统计截至中断处）"
    sections.append(
        {
            "id": "alignment",
            "title": "逐字对齐",
            "headline": align_headline,
            "total_degraded": total_degraded,
            "items": [
                {
                    "start": float(span.get("start", 0.0) or 0.0),
                    "end": float(span.get("end", 0.0) or 0.0),
                    "dur": float(span.get("dur", 0.0) or 0.0),
                    "time_text": (
                        f"{_fmt_report_time(span.get('start', 0.0))} → "
                        f"{_fmt_report_time(span.get('end', 0.0))}"
                    ),
                    "reason": str(span.get("reason", "unknown") or "unknown"),
                    "chars": int(span.get("chars", 0) or 0),
                }
                for span in degraded
            ],
        }
    )

    finish_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "overview": [
            {"label": label, "value": value}
            for label, value in overview_pairs(
                media_name=media_name,
                time_slice_desc=time_slice_desc,
                out_filename=out_filename,
                out_path=out_path,
                engine_name=engine_name,
                output_format=output_format,
                duration_str=format_duration(elapsed_time),
                cue_count=cue_count,
                char_count=char_count,
                is_interrupted=is_interrupted,
                finish_time=finish_time,
            )
        ],
        "params": [
            {"label": label, "value": value}
            for label, value in param_pairs(
                is_qwen=is_qwen,
                config=config,
                ngram=ngram,
                penalty=penalty,
                use_alignment=use_alignment,
            )
        ],
        "quality": {
            "headline": " ｜ ".join(quality_parts),
            "missed": len(visible_missed),
            "hidden_missed": hidden,
            "dropped": dropped,
            "suspect": suspect,
            "degraded": total_degraded,
            "has_findings": bool(len(visible_missed) or dropped or suspect),
            "qwen_limited": bool(is_qwen),
        },
        "sections": sections,
        "raw_text": raw_text,
    }
