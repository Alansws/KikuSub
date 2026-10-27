"""日语影片字幕转录工作台 (Web UI) — 专业影视级双栏核对工作台。

支持 Anime Whisper 与 Qwen3-ASR + CTC 逐字对齐双引擎，
提供动态 VAD 调参、预设方案管理、时间片段切片提取、中途打断保护与转录任务详报一键复制。
"""

from __future__ import annotations

import os

for proxy_key in [
    "http_proxy", "https_proxy", "all_proxy",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"
]:
    os.environ.pop(proxy_key, None)

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# 确保本地回环与 Gradio 内部通信绝不走代理
os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

import datetime
import html
import json
import logging
import math
import subprocess
import tempfile
import threading
import time
import queue
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote



warnings.filterwarnings("ignore", message=".*HTTP_422_UNPROCESSABLE_ENTITY.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="gradio.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="starlette.*")
warnings.filterwarnings("ignore", message=".*torch.jit.load is deprecated.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="torch.*")
warnings.filterwarnings("ignore", message=".*processor_kwargs.*")
warnings.filterwarnings("ignore", message=".*Kwargs passed to `processor.__call__`.*")
warnings.filterwarnings("ignore", message=".*The parameters have been moved from the Blocks constructor.*")
warnings.filterwarnings("ignore", message=".*show_copy_button.*")
warnings.filterwarnings("ignore", message=".*The input name `inputs` is deprecated.*", category=FutureWarning)


class _TransformersLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "processor_kwargs" in msg or "Kwargs passed to `processor.__call__`" in msg:
            return False
        if "Passing `generation_config`" in msg:
            return False
        if "The input name `inputs` is deprecated" in msg:
            return False
        return True


logging.getLogger("transformers").addFilter(_TransformersLogFilter())

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import gradio as gr
import numpy as np
from transformers import logging as hf_logging
hf_logging.set_verbosity_error()

from presets import PresetError, PresetStore
import audio_cache
from transcribe import (
    ENGINE,
    MODEL_DIR,
    SubtitleCue,
    WhisperVadConfig,
    build_whisper_config,
    cues_to_srt,
    cues_to_txt,
    cues_to_vtt,
    detect_device,
    format_duration,
    format_srt_timestamp,
    format_time_tag,
    parse_time_str,
    remove_ellipsis_only_cues,
    srt_to_cues,
)
from qwen_ctc import QwenCtcConfig, QwenCtcEngine

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def write_text_atomic(path: str | Path, text: str, encoding: str = "utf-8") -> Path:
    """原子写文本：先写同目录临时文件并 fsync，再 os.replace 覆盖目标。

    `Path.write_text` 在写入过程中崩溃/断电会留下半截文件，而 SRT 解析器对半截
    文件不会报错，只会少最后几条——用户无从察觉。这里保证目标文件"要么是旧内容、
    要么是完整新内容"，任何中间态都只存在于临时文件里。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target

QWEN = QwenCtcEngine()
ENGINES = {
    "Anime Whisper（litagin）": ENGINE,
    "Qwen3-ASR + 逐字对齐（jaykwok）": QWEN,
}

ENGINE_A_TO_KEY = {
    "Anime Whisper（litagin）": "whisper",
    "Qwen3-ASR + 逐字对齐（jaykwok）": "qwen",
}
ENGINE_KEY_TO_A = {key: name for name, key in ENGINE_A_TO_KEY.items()}
ENGINE_DISPLAY = {
    "whisper": "Anime Whisper",
    "qwen": "Qwen3-ASR 对齐",
    None: "通用配置",
}


def engine_key(engine_name: str) -> str:
    return ENGINE_A_TO_KEY.get(engine_name) or "whisper"


SUPPORTED = {
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".avi",
    ".m4v",
    ".ts",
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
    ".ogg",
    ".aac",
}

STORE = PresetStore()

CANCEL_EVENT = threading.Event()


def device_banner() -> str:
    """渲染顶部运行环境胶囊条（纯 HTML，避免 Markdown 行内代码的白底色）。"""
    device = detect_device().upper()
    whisper_ready = MODEL_DIR.exists() and (MODEL_DIR / "model.safetensors").exists()
    whisper_status = "已就绪" if whisper_ready else "未下载"
    qwen_status = "已就绪" if QWEN.model_available else "未下载"

    def chip(label: str, value: str, pending: bool = False, accent: bool = False) -> str:
        classes = "device-chip"
        if pending:
            classes += " is-pending"
        if accent:
            classes += " is-accent"
        tip = ' title="首次转写时会自动加载模型"' if pending else ""
        return (
            f'<span class="{classes}"{tip}>'
            f'<span class="chip-dot"></span>'
            f'<span class="chip-label">{label}</span>'
            f'<span class="chip-value">{value}</span>'
            f"</span>"
        )

    return (
        '<div class="device-chips">'
        + chip("计算设备", device, accent=True)
        + chip("Anime Whisper", whisper_status, pending=not whisper_ready)
        + chip("Qwen3-ASR + CTC", qwen_status, pending=not QWEN.model_available)
        + "</div>"
    )


def resolve_engine(name: str):
    engine = ENGINES.get(name)
    if engine is None:
        raise gr.Error(f"未知的识别引擎: {name}")
    return engine


def output_suffix(name: str) -> str:
    return "" if name.startswith("Anime Whisper") else ".qwen"


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    component: object
    engine: str
    cast: str
    config_field: str | tuple[str, ...] | None = None
    default: object = None


PARAMS: list[ParamSpec] = []


def param(key, label, component, engine, cast, config_field=None) -> object:
    PARAMS.append(
        ParamSpec(
            key=key,
            label=label,
            component=component,
            engine=engine,
            cast=cast,
            config_field=config_field,
            default=component.value,
        )
    )
    return component


def coerce_value(spec: ParamSpec, raw) -> int | float | bool:
    if spec.cast == "bool":
        return bool(raw)
    component = spec.component
    minimum = getattr(component, "minimum", None)
    maximum = getattr(component, "maximum", None)
    step = getattr(component, "step", None)
    value = float(raw)
    if minimum is not None:
        value = max(value, float(minimum))
    if maximum is not None:
        value = min(value, float(maximum))
    if step:
        base = float(minimum) if minimum is not None else 0.0
        index = math.floor(round((value - base) / float(step), 9) + 0.5)
        value = round(base + index * float(step), 6)
        if minimum is not None:
            value = max(value, float(minimum))
        if maximum is not None:
            value = min(value, float(maximum))
    return int(round(value)) if spec.cast == "int" else float(value)


def updates_for(values: dict) -> list[dict]:
    return [
        gr.update(value=coerce_value(spec, values.get(spec.key, spec.default)))
        for spec in PARAMS
    ]


def _cast(spec: ParamSpec, raw):
    if spec.cast == "bool":
        return bool(raw)
    if spec.cast == "int":
        return int(round(float(raw)))
    return float(raw)


def config_kwargs(engine: str, values) -> dict:
    out: dict = {}
    for spec, raw in zip(PARAMS, values):
        if spec.engine != engine or not spec.config_field:
            continue
        fields = spec.config_field if isinstance(spec.config_field, tuple) else (spec.config_field,)
        for field in fields:
            out[field] = _cast(spec, raw)
    return out


def passthrough_kwargs(engine: str, values) -> dict:
    out: dict = {}
    for spec, raw in zip(PARAMS, values):
        if spec.engine == engine and spec.config_field is None:
            out[spec.key.split(".", 1)[1]] = _cast(spec, raw)
    return out


def validate_params() -> None:
    import dataclasses

    seen: set[str] = set()
    for spec in PARAMS:
        if spec.key in seen:
            raise RuntimeError(f"重复的参数键: {spec.key}")
        seen.add(spec.key)
        if not spec.key.startswith(f"{spec.engine}."):
            raise RuntimeError(f"参数键 {spec.key!r} 与引擎 {spec.engine!r} 不匹配")
        if spec.config_field is None:
            continue
        target = WhisperVadConfig if spec.engine == "whisper" else QwenCtcConfig
        fields = (
            spec.config_field if isinstance(spec.config_field, tuple) else (spec.config_field,)
        )
        valid = {f.name for f in dataclasses.fields(target)}
        for field in fields:
            if field not in valid:
                raise RuntimeError(
                    f"参数 {spec.key!r} 映射到 {target.__name__}.{field}，但该字段不存在"
                )


def preset_choices_list() -> list[tuple[str, str]]:
    return [
        (f"{name}（{ENGINE_DISPLAY.get(engine, '通用')}）", name)
        for name, engine in STORE.list()
    ]


def preset_choices_update(selected: str | None = None) -> dict:
    choices = preset_choices_list()
    names = [name for _, name in choices]
    value = selected if selected in names else (names[0] if names else None)
    return gr.update(choices=choices, value=value)


def render_active_params_banner(engine_name: str, *values) -> str:
    eng = engine_key(engine_name)
    now_str = datetime.datetime.now().strftime("%H:%M:%S")

    param_dict = {}
    for spec, raw in zip(PARAMS, values):
        if spec.engine == eng:
            val = _cast(spec, raw)
            param_dict[spec.key.split(".", 1)[1]] = val
            if spec.config_field:
                fields = spec.config_field if isinstance(spec.config_field, tuple) else (spec.config_field,)
                for f in fields:
                    param_dict[f] = val

    if eng == "whisper":
        split_txt = "已启用" if param_dict.get("enable_sentence_split", True) else "已停用"
        loud_txt = "已启用" if param_dict.get("enable_loudnorm", False) else "已停用"
        th = param_dict.get("vad_threshold", param_dict.get("threshold", 0.30))
        min_sp = param_dict.get("vad_min_speech_ms", param_dict.get("min_speech_ms", 120))
        min_sil = param_dict.get("vad_min_silence_ms", param_dict.get("min_silence_ms", 150))
        pad = param_dict.get("vad_speech_pad_ms", param_dict.get("speech_pad_ms", 200))
        gap = param_dict.get("vad_merge_gap_s", param_dict.get("merge_gap_s", 0.3))
        max_seg = param_dict.get("vad_max_segment_s", param_dict.get("max_segment_s", 12.0))
        cue_pad = param_dict.get("cue_pad_s", 0.02)
        ngram = param_dict.get("no_repeat_ngram_size", 5)
        penalty = param_dict.get("repetition_penalty", 1.15)

        engine_tag = "Anime Whisper"
        chips = [
            ("VAD 阈值", f"{th}"),
            ("留白缓冲", f"{pad} ms"),
            ("静音停顿", f"{min_sil} ms"),
            ("最短语音", f"{min_sp} ms"),
            ("合并间隔", f"{gap} s"),
            ("单段最长", f"{max_seg} s"),
            ("智能分句", split_txt, True),
            ("响度归一化", loud_txt, True),
            ("抑制重复", f"ngram {ngram} · penalty {penalty}"),
            ("留白外扩", f"{cue_pad} s"),
        ]
    else:
        loud_txt = "已启用" if param_dict.get("enable_loudnorm", True) else "已停用"
        align_txt = "已启用" if param_dict.get("use_alignment", True) else "已停用"
        th = param_dict.get("vad_threshold", 0.30)
        max_dur = param_dict.get("max_cue_dur", 4.3)
        max_chars = param_dict.get("max_cue_chars", 21)
        pad = param_dict.get("vad_speech_pad_ms", 150)
        gap = param_dict.get("merge_gap_s", 0.5)

        engine_tag = "Qwen3-ASR + CTC 逐字对齐"
        chips = [
            ("VAD 阈值", f"{th}"),
            ("首尾缓冲", f"{pad} ms"),
            ("合并间隔", f"{gap} s"),
            ("单句目标时长", f"{max_dur} s"),
            ("单句字数上限", f"{max_chars}"),
            ("CTC 逐字对齐", align_txt, True),
            ("响度优化", loud_txt, True),
        ]

    chip_html = "".join(
        f'<span class="p-chip{" is-flag" if len(item) > 2 and item[2] else ""}">'
        f"<i>{item[0]}</i><b>{item[1]}</b></span>"
        for item in chips
    )
    return (
        '<div class="params-strip">'
        '<div class="params-strip-head">'
        '<span class="dot"></span><b>当前生效参数</b>'
        f'<span class="engine-tag">{engine_tag}</span>'
        f'<span class="ts">{now_str} 同步</span>'
        "</div>"
        f'<div class="params-chips">{chip_html}</div>'
        "</div>"
    )


def save_preset(name, engine_name, *values):
    eng = engine_key(engine_name)
    subset = {
        spec.key: raw
        for spec, raw in zip(PARAMS, values)
        if spec.engine == eng
    }
    try:
        saved, created = STORE.save(name, subset, engine=eng)
    except (PresetError, OSError) as exc:
        raise gr.Error(f"保存失败：{exc}")

    action = "已保存" if created else "已覆盖更新"
    tag = ENGINE_DISPLAY[eng]
    gr.Info(f"💾 预设「{saved}」{action}！（包含 {len(subset)} 项参数，引擎：{tag}）")
    banner = render_active_params_banner(engine_name, *values)
    return (
        preset_choices_update(saved),
        banner,
    )


def load_preset(name):
    if not name:
        raise gr.Error("请先在下拉列表中选择预设。")
    entry = STORE.get(name)
    if entry is None:
        raise gr.Error(f"未找到预设「{name}」。")

    engine, values = entry.get("引擎"), entry.get("参数", {})
    if engine in ("whisper", "qwen"):
        engine_update = gr.update(value=ENGINE_KEY_TO_A[engine])
        updates = []
        for spec in PARAMS:
            if spec.engine == engine:
                updates.append(gr.update(value=coerce_value(spec, values.get(spec.key, spec.default))))
            else:
                updates.append(gr.update())
        whisper_vis = gr.update(visible=(engine == "whisper"))
        qwen_vis = gr.update(visible=(engine == "qwen"))
    else:
        engine_update = gr.update()
        updates = updates_for(values)
        whisper_vis = gr.update()
        qwen_vis = gr.update()

    banner_engine = ENGINE_KEY_TO_A.get(engine, "Anime Whisper（litagin）") if engine else "Anime Whisper（litagin）"
    current_values = []
    for spec in PARAMS:
        if spec.key in values:
            current_values.append(coerce_value(spec, values[spec.key]))
        else:
            current_values.append(spec.default)
    banner_content = render_active_params_banner(banner_engine, *current_values)

    gr.Info(f"✨ 预设载入成功：「{name}」参数已全面应用至当前工作台。")

    return (
        engine_update,
        *updates,
        preset_choices_update(name),
        banner_content,
        whisper_vis,
        qwen_vis,
    )


def delete_preset(name):
    if not name:
        raise gr.Error("请先在下拉列表中选择预设。")
    try:
        removed = STORE.delete(name)
    except (PresetError, OSError) as exc:
        raise gr.Error(f"删除失败：{exc}")
    gr.Info(f"🗑️ 已成功删除预设「{removed}」。")
    return preset_choices_update()


def reset_params(engine_name):
    eng = engine_key(engine_name)
    updates = []
    current_values = []
    for spec in PARAMS:
        if spec.engine == eng:
            updates.append(gr.update(value=spec.default))
            current_values.append(spec.default)
        else:
            updates.append(gr.update())
            current_values.append(spec.default)
    banner_content = render_active_params_banner(engine_name, *current_values)
    gr.Info(f"🔄 已将「{ENGINE_DISPLAY[eng]}」参数恢复为推荐默认值。")
    return (
        *updates,
        preset_choices_update(),
        banner_content,
    )


def pick_fills_name(name):
    return gr.update(value=name or "")


def trigger_cancel():
    CANCEL_EVENT.set()
    gr.Warning("⚠️ 已发送中途打断指令！正在中止后续处理并妥善保存当前已转录的字幕…")


def cues_to_table(cues: list[SubtitleCue]) -> list[list]:
    rows = []
    for i, c in enumerate(cues, start=1):
        rows.append([
            i,
            format_srt_timestamp(c.start),
            format_srt_timestamp(c.end),
            c.text.strip(),
        ])
    return rows


MISSED_REASON_LABELS = {
    "empty-after-retry": "重试后仍为空",
    "retry-suspicious": "重试结果不可信",
}

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
        f"• 媒体源文件：{media_name}",
        f"• 处理时间段：{time_slice_desc}",
        f"• 字幕文件名：{out_filename}",
        f"• 保存完整路径：{out_path}",
        f"• 识别引擎：{engine_name}",
        f"• 输出格式：{output_format}",
        f"• 转录耗时：{duration_str}",
        f"• 字幕统计：共 {cue_count} 条字幕 ｜ 总计 {char_count} 字符",
        f"• 执行状态：{'⚠️ 用户中途打断 (保存部分字幕)' if is_interrupted else '✅ 全部完成'}",
        f"• 归档时间：{finish_time}",
        "",
        "【执行生效参数清单】",
    ]

    if is_qwen:
        lines.extend([
            "• 识别方案：Qwen3-ASR (JA Anime/Galgame) + CTC 对齐",
            f"• VAD 语音检测阈值 (vad_threshold)：{getattr(config, 'vad_threshold', 0.30)}",
            f"• 最短语音长度 (vad_min_speech_ms)：{getattr(config, 'vad_min_speech_ms', 100)} ms",
            f"• 判定为停顿的静音 (vad_min_silence_ms)：{getattr(config, 'vad_min_silence_ms', 200)} ms",
            f"• 切片首尾留白缓冲 (vad_speech_pad_ms)：{getattr(config, 'vad_speech_pad_ms', 150)} ms",
            f"• 相邻片段合并间隔 (merge_gap_s)：{getattr(config, 'merge_gap_s', 0.5)} s",
            f"• 单次送模音频窗口 (max_segment_s)：{getattr(config, 'max_segment_s', 16.0)} s",
            f"• 单条字幕目标时长 (max_cue_dur)：{getattr(config, 'max_cue_dur', 4.3)} s",
            f"• 单条字幕最大字数 (max_cue_chars)：{getattr(config, 'max_cue_chars', 21)} 字",
            f"• 视为停顿静音长度 (min_pause_s)：{getattr(config, 'min_pause_s', 0.12)} s",
            f"• 字幕前后留白 (cue_pad_s)：{getattr(config, 'cue_pad_start_s', 0.12)} s",
            f"• CTC 逐字发声帧对齐 (use_alignment)：{'启用' if use_alignment else '停用'}",
            f"• 动态响度归一化 (enable_loudnorm)：{'启用' if getattr(config, 'enable_loudnorm', True) else '停用'}",
        ])
    else:
        lines.extend([
            "• 识别方案：Anime Whisper (litagin/anime-whisper)",
            f"• 智能句级分切 (enable_sentence_split)：{'启用' if getattr(config, 'enable_sentence_split', True) else '停用'}",
            f"• 动态响度归一化 (enable_loudnorm)：{'启用' if getattr(config, 'enable_loudnorm', False) else '停用'}",
            f"• VAD 语音判定阈值 (threshold)：{getattr(config, 'threshold', 0.30)}",
            f"• 最短语音片段 (min_speech_ms)：{getattr(config, 'min_speech_ms', 120)} ms",
            f"• 判定停顿静音 (min_silence_ms)：{getattr(config, 'min_silence_ms', 150)} ms",
            f"• 首尾留白缓冲 (speech_pad_ms)：{getattr(config, 'speech_pad_ms', 200)} ms",
            f"• 相邻片段合并间隔 (merge_gap_s)：{getattr(config, 'merge_gap_s', 0.3)} s",
            f"• 单次送模最长秒数 (max_segment_s)：{getattr(config, 'max_segment_s', 12.0)} s",
            f"• 合并后最短片段 (min_speech_s)：{getattr(config, 'min_speech_s', 0.08)} s",
            f"• 字幕首尾外扩留白 (cue_pad_s)：{getattr(config, 'cue_pad_s', 0.02)} s",
            f"• 重复抑制 n-gram (no_repeat_ngram_size)：{ngram}",
            f"• 重复惩罚因子 (repetition_penalty)：{penalty}",
        ])

    visible_missed = _visible_missed_spans(missed_spans)
    hidden = _missed_hidden_count(missed_spans)
    lines.append("【疑似漏句区间】" + _missed_spans_headline(visible_missed))
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


_REPORT_SECTION_RE = re.compile(r"^【(?P<title>[^】]+)】(?P<note>.*)$")
_REPORT_BANNER_CHARS = set("=-—_ ")


def _report_chip(
    label: str, value: str, accent: bool = False, dot: bool = False, pending: bool = False
) -> str:
    """顶部设备胶囊同款小胶囊：label 灰字 + value 等宽粗体。"""
    if not value:
        return ""
    classes = "device-chip"
    if accent:
        classes += " is-accent"
    if pending:
        classes += " is-pending"
    dot_html = '<span class="chip-dot"></span>' if dot else ""
    return (
        f'<span class="{classes}">{dot_html}'
        f'<span class="chip-label">{html.escape(label)}</span>'
        f'<span class="chip-value">{html.escape(value)}</span></span>'
    )


def _report_metrics_html(report_text: str) -> str:
    """从详报正文抽取核心指标，渲染成胶囊行（耗时 / 条数 / 字符数 …）。"""

    def pick(pattern: str) -> str:
        match = re.search(pattern, report_text)
        return match.group(1).strip() if match else ""

    status = pick(r"• 执行状态：(.+)")
    elapsed = pick(r"• 转录耗时：(.+)")
    engine = pick(r"• 识别引擎：(.+)")
    span_desc = pick(r"• 处理时间段：(.+)")

    cue_count = char_count = ""
    stats_match = re.search(r"• 字幕统计：共\s*(\d+)\s*条字幕\s*｜\s*总计\s*(\d+)\s*字符", report_text)
    if stats_match:
        cue_count, char_count = stats_match.group(1), stats_match.group(2)

    done = status.startswith("✅")
    chips = [
        _report_chip("状态", status, accent=done, dot=True, pending=not done),
        _report_chip("耗时", elapsed, accent=True),
        _report_chip("条数", f"{cue_count} 条" if cue_count else ""),
        _report_chip("字符数", f"{char_count} 字" if char_count else ""),
        _report_chip("引擎", engine),
        _report_chip("时间段", span_desc),
    ]
    body = "".join(chip for chip in chips if chip)
    return f'<div class="report-metrics">{body}</div>' if body else ""


def _report_rows_html(lines: list[str]) -> str:
    rows = []
    for raw in lines:
        item = raw[2:].strip() if raw.startswith("• ") else raw.strip()
        if not item:
            continue
        if "：" in item:
            key, value = item.split("：", 1)
            key, value = key.strip(), value.strip()
            if key and value:
                rows.append(
                    f'<div class="rp-row"><span class="rp-key">{html.escape(key)}</span>'
                    f'<span class="rp-val">{html.escape(value)}</span></div>'
                )
                continue
        accent = " is-accent" if item.startswith(("✅", "⚠️", "❌")) else ""
        rows.append(f'<div class="rp-row"><span class="rp-val{accent}">{html.escape(item)}</span></div>')
    return "".join(rows)


def render_report_panel(report_text: str) -> str:
    """把纯文本详报渲染成结构化 HTML 面板。

    自带 `overflow-y: auto` 滚动容器（不依赖 Gradio Textbox 的自动增高逻辑），
    无论转写多少次都能稳定上下滑动；原始纯文本藏在 `.report-raw-src` 里供一键复制。
    """
    text = (report_text or "").strip()
    head = (
        '<div class="report-panel-head">'
        '<span class="report-panel-title">📄 转录任务报告</span>'
        '<span class="report-panel-hint">滚轮上下滑动查看全文 · 复制按钮输出纯文本原稿</span>'
        "</div>"
    )

    if not text:
        return (
            '<div class="report-panel">'
            f"{head}"
            '<div class="report-empty">转写完成后将在此生成详细报告…</div>'
            "</div>"
        )

    sections: list[dict] = []
    loose: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or set(line) <= _REPORT_BANNER_CHARS:
            continue
        section_match = _REPORT_SECTION_RE.match(line)
        if section_match:
            sections.append({
                "title": section_match.group("title").strip(),
                "note": section_match.group("note").strip(),
                "rows": [],
            })
            continue
        if sections:
            sections[-1]["rows"].append(line)
        else:
            loose.append(line)

    blocks = []
    for line in loose:
        # 顶部 banner 标题（🎬 …）已在 Tab 名里，不再重复
        if line.startswith("🎬"):
            continue
        blocks.append(f'<div class="rp-note">{html.escape(line)}</div>')

    for section in sections:
        title = html.escape(section["title"])
        note = f'<span class="rp-sec-note">{html.escape(section["note"])}</span>' if section["note"] else ""
        blocks.append(
            '<section class="rp-sec">'
            f'<div class="rp-sec-head"><span class="rp-sec-title">{title}</span>{note}</div>'
            f'{_report_rows_html(section["rows"])}'
            "</section>"
        )

    raw_source = f'<pre id="report-raw-text" class="report-raw-src">{html.escape(text)}</pre>'
    return (
        '<div class="report-panel">'
        f"{head}"
        f"{_report_metrics_html(text)}"
        f'<div class="report-body">{"".join(blocks)}</div>'
        f"{raw_source}"
        "</div>"
    )


def render_subtitles(cues: list[SubtitleCue], output_format: str) -> tuple[str, str]:
    if output_format == "SRT":
        return cues_to_srt(cues), ".srt"
    if output_format == "VTT":
        return cues_to_vtt(cues), ".vtt"
    return cues_to_txt(cues), ".txt"


def transcribe_media(
    media_file,
    engine_name,
    output_format,
    save_beside,
    start_time_text,
    end_time_text,
    keep_absolute_timeline,
    *values,
    progress=gr.Progress(),
):
    if media_file is None:
        gr.Warning("请先上传视频或音频文件。")
        yield (gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), "⚠️ 请先上传视频或音频文件。")
        return

    media_path = Path(media_file)
    if media_path.suffix.lower() not in SUPPORTED:
        gr.Warning(f"不支持的文件格式: {media_path.suffix}")
        yield (gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), f"❌ 不支持的文件格式: {media_path.suffix}")
        return

    CANCEL_EVENT.clear()

    start_s = parse_time_str(start_time_text)
    end_s = parse_time_str(end_time_text)
    if start_s is not None and start_s < 0:
        start_s = 0.0
    if end_s is not None and start_s is not None and end_s <= start_s:
        gr.Warning(f"终止时间点 ({end_time_text}) 必须大于起始时间点 ({start_time_text})。")
        yield (gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), "❌ 终止时间点必须大于起始时间点。")
        return

    slice_tag = ""
    time_slice_desc = "全片完整转录"
    if start_s is not None and end_s is not None:
        slice_tag = f"_{format_time_tag(start_s)}-{format_time_tag(end_s)}"
        time_slice_desc = f"{format_time_tag(start_s)} 至 {format_time_tag(end_s)} ({end_s - start_s:.1f} 秒)"
    elif start_s is not None:
        slice_tag = f"_from_{format_time_tag(start_s)}"
        time_slice_desc = f"从 {format_time_tag(start_s)} 开始至片尾"
    elif end_s is not None:
        slice_tag = f"_to_{format_time_tag(end_s)}"
        time_slice_desc = f"从 00m00s 开始至 {format_time_tag(end_s)}"

    time_offset = (start_s or 0.0) if keep_absolute_timeline else 0.0
    engine = resolve_engine(engine_name)
    is_qwen = engine is QWEN

    q = queue.Queue()

    def cb(ratio, message):
        progress(ratio, desc=message)
        q.put(("progress", ratio, message))

    def worker():
        try:
            start_timestamp = time.perf_counter()
            ngram = 5
            penalty = 1.15
            use_alignment = True

            if is_qwen:
                config = QwenCtcConfig(**config_kwargs("qwen", values))
                use_alignment = bool(passthrough_kwargs("qwen", values).get("use_alignment", True))
                if not engine.ready:
                    cb(0.01, f"正在载入 {engine_name}…")
                cues = engine.transcribe_file(
                    media_path,
                    progress_cb=cb,
                    use_alignment=use_alignment,
                    config=config,
                    cancel_event=CANCEL_EVENT,
                    start_time_s=start_s,
                    end_time_s=end_s,
                    time_offset=time_offset,
                )
                stats_note = ""
            else:
                config = build_whisper_config(**config_kwargs("whisper", values))
                gen = passthrough_kwargs("whisper", values)
                ngram = int(gen.get("no_repeat_ngram_size", 5))
                penalty = float(gen.get("repetition_penalty", 1.15))
                cues = ENGINE.transcribe_file(
                    media_path,
                    config=config,
                    no_repeat_ngram_size=ngram,
                    repetition_penalty=penalty,
                    progress_cb=cb,
                    cancel_event=CANCEL_EVENT,
                    start_time_s=start_s,
                    end_time_s=end_s,
                    time_offset=time_offset,
                )
                stats_note = f"\n\n`{ENGINE.last_stats.describe()}`"

            elapsed_time = time.perf_counter() - start_timestamp
            is_interrupted = bool(engine.last_interrupted) or CANCEL_EVENT.is_set()
            missed_spans = list(getattr(engine, "last_missed_spans", []) or [])
            segment_stats = dict(getattr(engine, "last_segment_stats", {}) or {})
            align_stats = dict(getattr(engine, "last_align_stats", {}) or {})

            if not cues:
                if is_interrupted:
                    raise RuntimeError("转录已取消，尚未生成有效字幕。")
                raise RuntimeError("未检测到有效语音。请尝试调低 VAD 阈值（如 0.20）或开启「动态响度归一化」后再试。")

            text, ext = render_subtitles(cues, output_format)
            tag = output_suffix(engine_name)
            interrupted_tag = ".part_cancelled" if is_interrupted else ""
            out_filename = f"{media_path.stem}{slice_tag}{tag}{interrupted_tag}{ext}"

            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            out_path = OUTPUT_DIR / out_filename
            write_text_atomic(out_path, text)

            if save_beside:
                beside = media_path.with_name(out_filename)
                try:
                    beside.parent.mkdir(parents=True, exist_ok=True)
                    write_text_atomic(beside, text)
                    out_path = beside
                except OSError:
                    pass

            char_count = sum(len(c.text) for c in cues)
            write_missed_report(media_path, slice_tag, "qwen" if is_qwen else "whisper", missed_spans)
            report_text = build_transcription_report(
                media_name=media_path.name,
                out_filename=out_filename,
                out_path=str(out_path),
                engine_name=engine_name,
                output_format=output_format,
                elapsed_time=elapsed_time,
                cue_count=len(cues),
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

            preview_lines = [f"[{c.start:7.2f} → {c.end:7.2f}] {c.text}" for c in cues[:100]]
            preview = "\n".join(preview_lines)
            if len(cues) > 100:
                preview += f"\n\n… 共 {len(cues)} 条字幕（已展示前 100 条）"
            preview += stats_note

            table_data = cues_to_table(cues)
            if is_interrupted:
                status_summary = (
                    f"⚠️ **转录已中途打断** ｜ 已抢救保存前 `{len(cues)}` 条字幕 ｜ "
                    f"耗时：`{format_duration(elapsed_time)}`"
                )
                final_progress = f"⚠️ 转写打断！已抢救保存前 {len(cues)} 条字幕。"
            else:
                status_summary = (
                    f"✅ **转写完成** ｜ 耗时：`{format_duration(elapsed_time)}` ｜ "
                    f"条数：`{len(cues)}` 条 ｜ 字符数：`{char_count}` 字"
                )
                final_progress = f"✅ 转录完成！共生成 {len(cues)} 条字幕（耗时 {format_duration(elapsed_time)}）"

            state_cues = [{"start": c.start, "end": c.end, "text": c.text} for c in cues]
            q.put(("done", (table_data, preview, str(out_path), str(out_path), state_cues, status_summary, render_report_panel(report_text), final_progress)))
        except Exception as exc:
            q.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    try:
        while True:
            try:
                item = q.get(timeout=0.1)
            except queue.Empty:
                if not thread.is_alive():
                    break
                continue

            tag = item[0]
            if tag == "progress":
                ratio, msg = item[1], item[2]
                pct = int(max(0.0, min(1.0, ratio)) * 100)
                status_html = f"⏳ **处理进度 [{pct}%]**：{msg}"
                yield (
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    status_html,
                )
            elif tag == "done":
                table_data, preview, p1, p2, state_cues, status_summary, report_text, final_progress = item[1]
                yield (
                    table_data,
                    preview,
                    p1,
                    p2,
                    state_cues,
                    status_summary,
                    report_text,
                    final_progress,
                )
                break
            elif tag == "error":
                exc = item[1]
                gr.Warning(f"⚠️ 处理异常：{exc}")
                yield (
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    f"❌ 处理异常：{exc}",
                )
                return
    finally:
        # 核心防卡死保护：若前端刷新、断开连接（触发 GeneratorExit），立即向后台线程发送中止信号
        if thread.is_alive():
            CANCEL_EVENT.set()


def clean_ellipsis_subtitles(cues, output_format, media_file, engine_name, save_beside):
    cues_obj = _coerce_cues(cues)
    if not cues_obj:
        gr.Warning("请先完成一次转写，再进行标点清理。")
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), "请先完成一次转写，再进行标点清理。"
    if media_file is None:
        gr.Warning("找不到原始媒体文件。")
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), "找不到原始媒体文件。"

    cleaned = remove_ellipsis_only_cues(cues_obj)
    removed_count = len(cues_obj) - len(cleaned)
    if removed_count == 0:
        gr.Info("未发现纯标点或纯省略号的空条目。")
        new_state = [{"start": c.start, "end": c.end, "text": c.text} for c in cues_obj]
        return cues_to_table(cues_obj), gr.update(), gr.update(), gr.update(), new_state, "未发现纯标点或纯省略号的空条目。"

    text, ext = render_subtitles(cleaned, output_format)
    media_path = Path(media_file)
    tag = output_suffix(engine_name) if engine_name else ""
    out_name = f"{media_path.stem}{tag}.clean{ext}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / out_name
    write_text_atomic(out_path, text)

    if save_beside:
        beside = media_path.with_name(out_name)
        try:
            beside.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(beside, text)
            out_path = beside
        except OSError:
            pass

    preview = "\n".join(f"[{c.start:7.2f} → {c.end:7.2f}] {c.text}" for c in cleaned[:100])
    if len(cleaned) > 100:
        preview += f"\n\n… 共 {len(cleaned)} 条字幕（已展示前 100 条）"
    message = f"已移除 {removed_count} 条纯标点空条目，剩余 {len(cleaned)} 条有效字幕并重新编号。"
    gr.Info(f"🧹 已成功清理 {removed_count} 条纯标点空行，生成 clean 版本字幕！")

    table_data = cues_to_table(cleaned)
    new_state = [{"start": c.start, "end": c.end, "text": c.text} for c in cleaned]
    return table_data, preview, str(out_path), str(out_path), new_state, message


# ==============================================================================
# 补漏核对工作台：音频波形缓存、选区双向同步与基线状态管理
# ==============================================================================

PEAKS_CACHE_DIR = OUTPUT_DIR / ".cache" / "peaks"
MEDIA_PEAKS_CACHE: dict[str, tuple[float, list[float]]] = {}
MEDIA_PEAKS_CACHE_LIMIT = 8
PEAKS_DISK_LIMIT = 128


def _peaks_cache_key(media_path: Path) -> str:
    """与 audio_cache 同源的缓存键：绝对路径 + 体积 + mtime_ns + 响度档位。

    波形固定读 `loudnorm=False` 的 16k wav，所以这里也固定 False，
    两套缓存一一对应；重压制（mtime 变）或换文件都不会命中脏数据。
    """
    try:
        return audio_cache.cache_key(media_path, loudnorm=False)
    except Exception:
        try:
            size = media_path.stat().st_size if media_path.exists() else 0
        except OSError:
            size = 0
        return f"{media_path.resolve()}_{size}"


def _remember_peaks(key: str, value: tuple[float, list[float]]) -> None:
    # dict 保序：先 pop 再插入 = 移到末尾。命中时也走这里，才是真正的 LRU
    # （旧实现只按插入序淘汰，反复看同一部片时等同于随机淘汰）。
    MEDIA_PEAKS_CACHE.pop(key, None)
    MEDIA_PEAKS_CACHE[key] = value
    while len(MEDIA_PEAKS_CACHE) > MEDIA_PEAKS_CACHE_LIMIT:
        MEDIA_PEAKS_CACHE.pop(next(iter(MEDIA_PEAKS_CACHE)))


def _load_peaks_from_disk(key: str, bins: int) -> tuple[float, list[float]] | None:
    """读落盘波形包络；任何异常都当作"未命中"并删掉坏文件，绝不向上抛。"""
    path = PEAKS_CACHE_DIR / f"{key}.npz"
    if not path.exists():
        return None
    try:
        with np.load(path) as data:
            if int(data["bins"]) != int(bins):
                return None
            duration = float(data["duration"])
            # 存的是 float32，读回来会有 0.73000001 这种尾巴；包络本身只保留 2 位小数，
            # 这里重新取整，保证"磁盘命中"与"现算"的结果逐元素相等。
            peaks = [round(float(x), 2) for x in data["peaks"]]
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    if len(peaks) != int(bins):
        return None
    return duration, peaks


def _save_peaks_to_disk(key: str, duration: float, peaks: list[float]) -> None:
    """原子落盘 npz：崩溃只会留下临时文件，不会留下读不了的半截 npz。"""
    if not peaks:
        return
    path = PEAKS_CACHE_DIR / f"{key}.npz"
    tmp_name = ""
    try:
        PEAKS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(dir=str(PEAKS_CACHE_DIR), prefix=f".{key}.", suffix=".npz")
        os.close(handle)
        with open(tmp_name, "wb") as fh:
            np.savez(
                fh,
                duration=np.float64(duration),
                peaks=np.asarray(peaks, dtype=np.float32),
                bins=np.int32(len(peaks)),
            )
        os.replace(tmp_name, path)
        tmp_name = ""
    except Exception as exc:
        logging.warning("波形缓存落盘失败：%s", exc)
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    _prune_peaks_disk()


def _prune_peaks_disk(limit: int = PEAKS_DISK_LIMIT) -> None:
    """磁盘侧按 mtime 只留最近 limit 个（8000 bin ≈ 32KB/片，128 个约 4MB）。"""
    try:
        files = sorted(
            PEAKS_CACHE_DIR.glob("*.npz"), key=lambda p: p.stat().st_mtime, reverse=True
        )
    except OSError:
        return
    for path in files[limit:]:
        try:
            path.unlink()
        except OSError:
            pass


def _coerce_cues(raw_cues) -> list[SubtitleCue]:
    result: list[SubtitleCue] = []
    for cue in raw_cues or []:
        if isinstance(cue, SubtitleCue):
            result.append(cue)
        elif isinstance(cue, dict):
            try:
                result.append(SubtitleCue(float(cue["start"]), float(cue["end"]), str(cue.get("text", ""))))
            except (KeyError, TypeError, ValueError):
                continue
        elif isinstance(cue, (list, tuple)) and len(cue) >= 3:
            try:
                if len(cue) == 3:
                    s, e, t = cue
                elif len(cue) >= 4:
                    s, e, t = cue[1], cue[2], cue[-1]
                else:
                    continue
                s_val = parse_time_str(str(s)) if isinstance(s, str) else float(s)
                e_val = parse_time_str(str(e)) if isinstance(e, str) else float(e)
                if s_val is not None and e_val is not None:
                    result.append(SubtitleCue(s_val, e_val, str(t)))
            except (ValueError, TypeError):
                continue
    return result


def _unique_sorted_cues(raw_cues) -> list[SubtitleCue]:
    """按时间排序去重。

    时间区间完全相同的条目（典型场景：中日双语 SRT 的日语行 + 中文行）
    保持「导入时的原始先后顺序」，不按文本重新排序，否则双语/多语字幕
    的行序会随字符编码随机翻转，叠加显示时语序错乱。
    """
    seen: set[tuple[int, int, str]] = set()
    result: list[SubtitleCue] = []
    ordered = list(enumerate(_coerce_cues(raw_cues)))
    ordered.sort(key=lambda pair: (float(pair[1].start), float(pair[1].end), pair[0]))
    for _, cue in ordered:
        start = max(0.0, float(cue.start))
        end = max(start + 0.001, float(cue.end))
        text = cue.text.strip()
        if not text:
            continue
        key = (round(start * 1000), round(end * 1000), text)
        if key not in seen:
            seen.add(key)
            result.append(SubtitleCue(round(start, 3), round(end, 3), text))
    return result


def review_cues_to_table(cues) -> list[list]:
    return [
        [i, format_srt_timestamp(cue.start), format_srt_timestamp(cue.end), f"{cue.end - cue.start:.2f}s", cue.text]
        for i, cue in enumerate(_unique_sorted_cues(cues), start=1)
    ]


def _cues_to_dicts(cues) -> list[dict]:
    return [{"start": c.start, "end": c.end, "text": c.text} for c in _unique_sorted_cues(cues)]


# ---------------------------------------------------------------------------
# 浏览器兼容性检测与 M4 Pro 硬件加速监看代理
# ---------------------------------------------------------------------------
PROXIES_DIR = OUTPUT_DIR / "web_proxies"
PROXIES_DIR.mkdir(parents=True, exist_ok=True)


def get_existing_proxy(media_path: Path) -> Path | None:
    """检查是否已经存在压制好的轻量监看代理成片。"""
    file_size = media_path.stat().st_size if media_path.exists() else 0
    clean_stem = media_path.stem
    standard_proxy = PROXIES_DIR / f"{clean_stem}_{file_size}_preview.mp4"

    if standard_proxy.exists() and standard_proxy.stat().st_size > 50 * 1024:
        return standard_proxy

    legacy_candidates = sorted(
        PROXIES_DIR.glob(f"{clean_stem}_*_preview.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    for cand in legacy_candidates:
        if cand.stat().st_size > 50 * 1024:
            return cand
    return None


def get_web_friendly_video(media_path: Path) -> Path:
    """默认零等待直通原片。若已存在历史代理成片则直接复用，绝不自动阻塞转码。"""
    suffix = media_path.suffix.lower()
    if suffix in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}:
        return media_path

    proxy = get_existing_proxy(media_path)
    if proxy is not None:
        return proxy

    # 默认直接返回原片，供浏览器原生硬件解码（零等待）
    return media_path


def create_m4pro_hardware_proxy(media_path: Path) -> Path | None:
    """针对 Apple Silicon (M4 Pro) 硬件媒体引擎优化的 480p 代理极速压制器。"""
    file_size = media_path.stat().st_size if media_path.exists() else 0
    clean_stem = media_path.stem
    standard_proxy = PROXIES_DIR / f"{clean_stem}_{file_size}_preview.mp4"

    # 方案 1：Apple Silicon 全硬件流水线（VideoToolbox 硬件解码 + 硬件编码 + 硬件色彩空间转换）
    cmd_hw = [
        "ffmpeg", "-y",
        "-hwaccel", "videotoolbox",
        "-i", str(media_path),
        "-vf", "scale=-2:480,format=yuv420p",
        "-c:v", "h264_videotoolbox",
        "-b:v", "2200k",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(standard_proxy)
    ]

    try:
        logging.info("🚀 启动 Apple Silicon M4 硬件加速 (VideoToolbox) 压制监看代理…")
        res = subprocess.run(cmd_hw, capture_output=True, text=True, timeout=1200)
        if res.returncode == 0 and standard_proxy.exists() and standard_proxy.stat().st_size > 1024:
            return standard_proxy
    except Exception as exc:
        logging.warning(f"VideoToolbox 全硬件加速异常，尝试回退模式: {exc}")

    # 方案 2：若 8K 超规格导致硬解管线报错，使用多线程软解 + VideoToolbox 硬件编码
    cmd_hw_fallback = [
        "ffmpeg", "-y",
        "-threads", "0",
        "-i", str(media_path),
        "-vf", "scale=-2:480,format=yuv420p",
        "-c:v", "h264_videotoolbox",
        "-b:v", "2200k",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(standard_proxy)
    ]
    try:
        res = subprocess.run(cmd_hw_fallback, capture_output=True, text=True, timeout=1200)
        if res.returncode == 0 and standard_proxy.exists() and standard_proxy.stat().st_size > 1024:
            return standard_proxy
    except Exception as exc:
        logging.warning(f"硬件编码回退方案失败: {exc}")

    # 方案 3：通用多线程 CPU 兜底
    cmd_cpu = [
        "ffmpeg", "-y",
        "-threads", "0",
        "-i", str(media_path),
        "-vf", "scale=-2:480",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "ultrafast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(standard_proxy)
    ]
    try:
        res = subprocess.run(cmd_cpu, capture_output=True, text=True, timeout=1800)
        if res.returncode == 0 and standard_proxy.exists():
            return standard_proxy
    except Exception:
        pass

    return None


def _media_url(path: Path) -> str:
    return "/gradio_api/file=" + quote(path.resolve().as_posix(), safe="/:")


def _media_duration_and_peaks(media_path: Path, bins: int | None = None) -> tuple[float, list[float]]:
    cache_key = _peaks_cache_key(media_path)
    cached = MEDIA_PEAKS_CACHE.get(cache_key)
    if cached is not None:
        _remember_peaks(cache_key, cached)
        return cached

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(media_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        duration = max(0.0, float(probe.stdout.strip()))
    except ValueError:
        duration = 0.0

    if bins is None or bins <= 0:
        target_bins = int(duration * 4) if duration > 0 else 3200
        bins = max(2400, min(8000, target_bins))

    # 落盘缓存：进程重启后免去一次全片读盘 + 包络扫描
    disk = _load_peaks_from_disk(cache_key, bins)
    if disk is not None:
        _remember_peaks(cache_key, disk)
        return disk

    # 波形固定使用 loudnorm=False 的原始 16k wav：真实响度不被动态归一化压平
    if audio_cache.enabled():
        try:
            wav_path = audio_cache.ensure_wav(media_path, loudnorm=False)
            wav_duration, peaks = audio_cache.peaks(wav_path, bins)
            if duration <= 0:
                duration = wav_duration
            res = (duration, peaks)
            _remember_peaks(cache_key, res)
            _save_peaks_to_disk(cache_key, res[0], res[1])
            return res
        except Exception as exc:
            logging.warning("缓存波形不可用，回退为 ffmpeg 直读：%s", exc)

    audio = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(media_path), "-map", "0:a:0?", "-ac", "1", "-ar", "1000", "-f", "f32le", "pipe:1"],
        capture_output=True,
        timeout=180,
    )
    if audio.returncode != 0 or not audio.stdout:
        res = (duration, [])
        _remember_peaks(cache_key, res)
        return res

    samples = np.frombuffer(audio.stdout, dtype=np.float32)
    if not samples.size:
        res = (duration, [])
        _remember_peaks(cache_key, res)
        return res

    bins = min(bins, len(samples))

    edges = np.linspace(0, len(samples), bins + 1, dtype=int)
    peaks = [float(np.max(np.abs(samples[edges[i] : edges[i + 1]]))) if edges[i] < edges[i + 1] else 0.0 for i in range(bins)]
    maximum = max(peaks, default=0.0)
    norm_peaks = [round(min(1.0, peak / maximum), 2) if maximum else 0.0 for peak in peaks]
    res = (duration, norm_peaks)
    _remember_peaks(cache_key, res)
    _save_peaks_to_disk(cache_key, res[0], res[1])
    return res


def build_review_payload(media_file, review_cues, include_peaks=True) -> str:
    cues_dicts = _cues_to_dicts(review_cues)
    if not media_file:
        return json.dumps({
            "src": "", "name": "", "duration": 0.0, "peaks": [], "cues": cues_dicts,
            "error": "请先在上方上传需要核对的音视频文件。"
        }, ensure_ascii=False)
    
    media_path = Path(media_file)
    if not media_path.exists():
        return json.dumps({
            "src": "", "name": "", "duration": 0.0, "peaks": [], "cues": cues_dicts,
            "error": "媒体临时文件已不存在，请重新上传。"
        }, ensure_ascii=False)

    duration = 0.0
    peaks = []
    error = ""
    
    if include_peaks:
        try:
            duration, peaks = _media_duration_and_peaks(media_path)
        except Exception as exc:
            error = f"读取音频波形异常：{exc}"
    
    web_media_path = get_web_friendly_video(media_path)
    return json.dumps({
        "src": _media_url(web_media_path),
        "name": media_path.name,
        "duration": duration,
        "peaks": peaks,
        "cues": cues_dicts,
        "error": error,
        "is_patch_only": not include_peaks,  # 告知前端只更新字幕
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 监看画面独立装载：手动导入 / 复用历史代理 / 关闭 / 恢复自动跟随
# ---------------------------------------------------------------------------
MONITOR_META_FILE = OUTPUT_DIR / "monitor_last.json"
MONITOR_VIDEO_SUFFIXES = {
    ".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi",
    ".ts", ".flv", ".wmv", ".mpg", ".mpeg", ".ogv",
}

_MONITOR_IDLE_TIP = (
    "🎞️ 媒体监看待机中。导入音视频后将自动载入画面；"
    "也可点「📂 导入监看画面」手动指定任意本地片源。"
)


def _monitor_empty_html(icon: str, title: str, desc: str) -> str:
    return (
        '<div class="reviewer-empty">'
        f'<div class="rw-empty-icon">{icon}</div>'
        f'<div class="rw-empty-title">{title}</div>'
        f'<div class="rw-empty-desc">{desc}</div>'
        "</div>"
    )


def _coerce_upload_path(value) -> str:
    """把 gr.File / gr.UploadButton 的各类返回值统一成字符串路径。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            resolved = _coerce_upload_path(item)
            if resolved:
                return resolved
        return ""
    if isinstance(value, dict):
        for key in ("path", "name", "orig_name"):
            if value.get(key):
                return str(value[key])
        return ""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    for attr in ("path", "name"):
        candidate = getattr(value, attr, None)
        if isinstance(candidate, str) and candidate:
            return candidate
    return ""


def _format_file_size(num_bytes: int) -> str:
    size = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in {"B", "KB"} else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _save_monitor_meta(monitor_path: Path) -> None:
    """记录最近一次手动指定的监看片源，便于下次打开工作台时自动恢复。"""
    try:
        MONITOR_META_FILE.write_text(
            json.dumps(
                {
                    "path": str(monitor_path.resolve()),
                    "name": monitor_path.name,
                    "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_monitor_meta() -> tuple[Path | None, str]:
    """返回 (仍然存在的片源路径, 记录中的文件名)。路径失效时第一项为 None。"""
    try:
        data = json.loads(MONITOR_META_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None, ""
    remembered = str(data.get("name") or "")
    candidate = Path(str(data.get("path") or ""))
    if candidate.is_file():
        return candidate, remembered or candidate.name
    return None, remembered


def _clear_monitor_meta() -> None:
    try:
        MONITOR_META_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _ensure_monitor_servable(monitor_path: Path) -> None:
    """把片源所在目录动态加入 Gradio 白名单，避免手动指定的片源 403 黑屏。"""
    try:
        parent = str(monitor_path.resolve().parent)
        blocks = globals().get("demo")
        allowed = getattr(blocks, "allowed_paths", None)
        if isinstance(allowed, list) and parent not in allowed:
            allowed.append(parent)
    except Exception:
        pass


def build_monitor_payload(monitor_path: Path, review_cues, origin: str = "manual") -> str:
    """用任意本地片源构建监看负载：画面与波形取自该片源，字幕沿用当前核对基线。"""
    cues_dicts = _cues_to_dicts(review_cues)
    if not monitor_path.is_file():
        return json.dumps(
            {
                "src": "",
                "name": "",
                "duration": 0.0,
                "peaks": [],
                "cues": cues_dicts,
                "error": _monitor_empty_html(
                    "⚠️",
                    "监看片源不可用",
                    f"找不到文件：<code>{monitor_path}</code><br>它可能已被移动或重命名，请重新指定。",
                ),
            },
            ensure_ascii=False,
        )

    duration, peaks = 0.0, []
    error = ""
    try:
        duration, peaks = _media_duration_and_peaks(monitor_path)
    except Exception as exc:
        error = f"读取监看片源波形异常：{exc}"

    _ensure_monitor_servable(monitor_path)
    return json.dumps(
        {
            "src": _media_url(monitor_path),
            "name": monitor_path.name,
            "duration": duration,
            "peaks": peaks,
            "cues": cues_dicts,
            "error": error,
            "is_patch_only": False,
            "origin": origin,
        },
        ensure_ascii=False,
    )


def load_manual_monitor(upload_value, review_cues):
    """📂 手动导入监看画面：只切换画面/波形片源，绝不改动转录源与字幕基线。"""
    raw_path = _coerce_upload_path(upload_value)
    if not raw_path:
        return gr.update(), "⚠️ 尚未选择文件。点「📂 导入监看画面」从磁盘挑选一个视频文件。"

    monitor_path = Path(raw_path)
    if not monitor_path.is_file():
        return gr.update(), f"⚠️ 文件不存在：`{monitor_path}`"

    suffix = monitor_path.suffix.lower()
    if suffix in {".srt", ".ass", ".ssa", ".vtt", ".txt", ".json"}:
        return gr.update(), f"⚠️ `{suffix}` 不是视频文件，请选择 mp4 / mkv / mov 等片源。"

    payload = build_monitor_payload(monitor_path, review_cues, origin="manual")
    _save_monitor_meta(monitor_path)
    note = "" if suffix in MONITOR_VIDEO_SUFFIXES else "（该文件不含画面，只会显示波形）"
    return (
        payload,
        f"🎞️ 已手动载入监看片源「{monitor_path.name}」｜{_format_file_size(monitor_path.stat().st_size)}{note}。"
        "此操作不影响上方转录源，字幕基线保持不变。",
    )


def close_monitor(review_cues):
    """✕ 关闭监看画面：清空画面与波形，但完整保留字幕基线。"""
    # 关闭即视为不再需要该片源，同步清除记忆，避免下次打开又被自动拉起
    _clear_monitor_meta()
    payload = json.dumps(
        {
            "src": "",
            "name": "",
            "duration": 0.0,
            "peaks": [],
            "cues": _cues_to_dicts(review_cues),
            "error": _monitor_empty_html(
                "🎬",
                "监看画面已关闭",
                "字幕与波形数据仍然保留。<br>点「📂 导入监看画面」选择新的片源，或点「↺ 恢复自动」跟随当前导入的媒体。",
            ),
            "closed": True,
            "is_patch_only": False,
        },
        ensure_ascii=False,
    )
    return (
        payload,
        "🎬 监看画面已关闭（字幕与波形数据均保留）。"
        "可点「📂 导入监看画面」换片源，或「↺ 恢复自动」跟随当前媒体。",
    )


def restore_auto_monitor(media_file, review_cues):
    """↺ 恢复自动：重新跟随上方导入的媒体文件（原片或历史代理）。"""
    if not media_file:
        # 没有转录源时不要清掉当前画面，只做提示，避免误操作丢画面
        return gr.update(), "⚠️ 尚未导入媒体文件，无法恢复自动监看。可点「📂 导入监看画面」直接指定片源。"

    payload, status = prepare_review_workspace(media_file, review_cues)
    return payload, "↺ " + status


def list_proxy_choices() -> list[tuple[str, str]]:
    """列出 outputs/web_proxies 里可零拷贝复用的历史 480p 代理。"""
    try:
        files = [
            p for p in PROXIES_DIR.glob("*.mp4")
            if p.is_file() and p.stat().st_size > 50 * 1024
        ]
    except Exception:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    choices: list[tuple[str, str]] = []
    for item in files[:40]:
        stat = item.stat()
        stamp = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M")
        choices.append((f"{item.name}  ·  {stat.st_size / (1024 * 1024):.0f} MB  ·  {stamp}", str(item)))
    return choices


def refresh_monitor_proxy_choices():
    choices = list_proxy_choices()
    return gr.update(choices=choices, visible=bool(choices))


def load_proxy_as_monitor(proxy_value, review_cues):
    """选中历史代理后立即载入（零拷贝，直接复用磁盘上的成片）。"""
    if not proxy_value:
        return gr.update(), gr.update(), gr.update()

    proxy_path = Path(str(proxy_value))
    if not proxy_path.is_file():
        return gr.update(), f"⚠️ 代理文件已不存在：`{proxy_path}`", gr.update(value=None)

    payload = build_monitor_payload(proxy_path, review_cues, origin="proxy")
    _save_monitor_meta(proxy_path)
    return (
        payload,
        f"📦 已载入历史 480p 代理「{proxy_path.name}」（零拷贝直接复用，无需重新压制）。",
        gr.update(value=None),
    )


def restore_monitor_on_load(review_cues):
    """页面打开时自动恢复上次使用的监看片源，失效则给出明确提示。"""
    last, remembered = _load_monitor_meta()
    if last is None:
        if remembered:
            return (
                gr.update(),
                f"⚠️ 上次使用的监看片源「{remembered}」已不在原路径（可能被移动）。"
                "请点「📂 导入监看画面」重新指定。",
            )
        return gr.update(), _MONITOR_IDLE_TIP

    payload = build_monitor_payload(last, review_cues, origin="restore")
    return (
        payload,
        f"↺ 已自动恢复上次使用的监看片源「{last.name}」。"
        "如需更换请点「📂 导入监看画面」，点「✕ 关闭监看」可清空画面。",
    )


def prepare_review_workspace(media_file, review_cues):
    # 导入新媒体即回到「自动跟随」模式，清掉上次手动指定的监看片源记忆
    _clear_monitor_meta()
    payload = build_review_payload(media_file, review_cues, include_peaks=True)
    data = json.loads(payload)
    if data.get("error") and not data.get("src"):
        return payload, f"⚠️ {data['error']}"
    wave_state = "音频波形与时间轴已同步就绪，可在波形上拖拽框选漏句范围。" if data.get("peaks") else data.get("error", "媒体预览已就绪。")
    status = f"🎞️ 已载入「{data['name']}」｜{wave_state}"

    missed: list[dict] = []
    if media_file:
        try:
            missed = load_missed_spans(Path(media_file).stem)
        except Exception:
            missed = []
    if missed:
        visible = _visible_missed_spans(missed)
        hidden = len(missed) - len(visible)
        if visible:
            total = sum(float(span.get("dur", 0.0) or 0.0) for span in visible)
            status += (
                f"\n\n⚠️ 有 {len(visible)} 处疑似漏句（共 {total:.1f} 秒），"
                "可在波形上框选后「识别并直接入轨」"
            )
        if hidden:
            status += f"（另有 {hidden} 处近静音段已隐藏）"
    return payload, status

# ==============================================================================
# 校对断点进度管理 (Auto-Save Progress)
# ==============================================================================

def _get_progress_file(media_file: str | None = None, srt_file: str | None = None) -> Path | None:
    stem = ""
    if srt_file:
        stem = Path(srt_file).stem
    elif media_file:
        stem = Path(media_file).stem
    if not stem:
        return None
    # 去除常见草稿后缀，统一绑定到主干名称（如 HJMO-320.HD）
    clean_stem = re.sub(r"(\.autosave_draft|\.reviewed|\.clean|\.part_cancelled)$", "", stem)
    return OUTPUT_DIR / f"{clean_stem}.progress.json"


def _save_draft_and_progress(
    media_file: str | None,
    cues: list[SubtitleCue],
    reviewed_idx: int | None = None,
    start_str: str | None = None,
    end_str: str | None = None,
    text: str | None = None,
) -> None:
    """自动写盘草稿 SRT 并记录最后编辑的进度元数据。"""
    if not cues:
        return
    stem = Path(media_file).stem if media_file else "subtitles"
    clean_stem = re.sub(r"(\.autosave_draft|\.reviewed|\.clean|\.part_cancelled)$", "", stem)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 保存 .autosave_draft.srt 草稿
    try:
        draft_path = OUTPUT_DIR / f"{clean_stem}.autosave_draft.srt"
        write_text_atomic(draft_path, cues_to_srt(cues))
    except Exception:
        pass

    # 2. 保存伴生断点进度 .progress.json
    if reviewed_idx is not None:
        prog_file = OUTPUT_DIR / f"{clean_stem}.progress.json"
        prog_data = {
            "media_name": Path(media_file).name if media_file else "",
            "last_reviewed_idx": int(reviewed_idx),
            "last_time_str": str(start_str or ""),
            "end_time_str": str(end_str or ""),
            "last_text": str(text or ""),
            "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            write_text_atomic(prog_file, json.dumps(prog_data, ensure_ascii=False, indent=2))
        except Exception:
            pass


def _load_review_progress(media_file: str | None = None, srt_file: str | None = None) -> dict | None:
    """尝试加载历史校对断点进度。"""
    prog_file = _get_progress_file(media_file, srt_file)
    if prog_file and prog_file.exists():
        try:
            return json.loads(prog_file.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

def import_review_srt(srt_file, media_file, current_cues=None, undo_stack=None, redo_stack=None):
    existing = _unique_sorted_cues(current_cues)
    fallback_dicts = _cues_to_dicts(existing)
    fallback_table = review_cues_to_table(existing)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    fallback_ret = (
        fallback_dicts,
        fallback_table,
        gr.update(),
        "⚠️ 未能载入字幕，已有核对字幕保持完好。",
        u_stack,
        r_stack,
        gr.update(),
        gr.update(),
        gr.update(),
        gr.update(),
    )

    if srt_file is None:
        gr.Warning("⚠️ 请先在上方选择需要导入的 SRT 字幕文件。")
        return fallback_ret
    path = Path(srt_file)
    if not path.exists():
        gr.Warning("⚠️ 指定的 SRT 文件不存在。")
        return fallback_ret

    try:
        raw_text = path.read_text(encoding="utf-8-sig")
        cues = _unique_sorted_cues(srt_to_cues(raw_text))
    except Exception as exc:
        gr.Warning(f"⚠️ 读取 SRT 文件失败：{exc}")
        return fallback_ret

    if not cues:
        gr.Warning("⚠️ 未从该文件中读取到有效 SRT 条目，请检查文件编码与格式。")
        return fallback_ret

    new_undo, new_redo = _push_history(u_stack, existing)
    cues_dicts = _cues_to_dicts(cues)
    table_rows = review_cues_to_table(cues)
    payload = build_review_payload(media_file, cues, include_peaks=False)

    # 尝试自动读取断点校对进度
    progress_info = _load_review_progress(media_file=media_file, srt_file=srt_file)
    target_idx = 1
    has_history = False

    if progress_info:
        saved_idx = progress_info.get("last_reviewed_idx", 1)
        if 1 <= saved_idx <= len(cues):
            target_idx = saved_idx
            has_history = True
        elif saved_idx > len(cues):
            target_idx = len(cues)
            has_history = True

    target_cue = cues[target_idx - 1] if cues else None
    target_start = format_srt_timestamp(target_cue.start) if target_cue else ""
    target_end = format_srt_timestamp(target_cue.end) if target_cue else ""
    target_text = target_cue.text if target_cue else ""

    if has_history:
        up_time = progress_info.get("update_time", "")
        status_msg = (
            f"✅ **已导入字幕并恢复断点进度**：共 {len(cues)} 条字幕 ｜ "
            f"💡 检测到上次于 `{up_time}` 校对至第 **{target_idx}** 行（`{target_start}`）。"
            f"已为您自动定位至该处，画面与播放头已对齐！"
        )
        gr.Info(f"📍 已自动恢复校对进度：定位至第 {target_idx} 行（{target_start}）")
    else:
        status_msg = f"✅ 已成功导入并设为基线：共 {len(cues)} 条字幕。播放视频时字幕将实时浮现在画面底部。"
        gr.Info(f"📥 成功载入基线字幕：共 {len(cues)} 条。(如误操作可按 Cmd+Z 撤回)")

    return (
        cues_dicts,
        table_rows,
        payload,
        status_msg,
        new_undo,
        new_redo,
        target_idx,
        target_start,
        target_end,
        target_text,
    )


def use_latest_as_review_base(latest_cues, media_file, current_cues=None, undo_stack=None, redo_stack=None):
    existing = _unique_sorted_cues(current_cues)
    fallback_dicts = _cues_to_dicts(existing)
    fallback_table = review_cues_to_table(existing)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    cues = _unique_sorted_cues(latest_cues)
    if not cues:
        gr.Warning("⚠️ 当前尚无转写完成的字幕，无法设为基线。请先在上方执行一次转写。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 当前无可用转写结果，核对台保持不变。", u_stack, r_stack

    new_undo, new_redo = _push_history(u_stack, existing)
    cues_dicts = _cues_to_dicts(cues)
    table_rows = review_cues_to_table(cues)
    # 纯字幕基线覆盖，不重复传输波形
    payload = build_review_payload(media_file, cues, include_peaks=False)
    gr.Info(f"📌 已将本次转写的 {len(cues)} 条字幕设为核对基线。(可按 Cmd+Z 撤回)")
    return cues_dicts, table_rows, payload, f"✅ 已将本次转写的 {len(cues)} 条字幕设为核对基线。", new_undo, new_redo


def append_latest_patch(review_cues, latest_cues, media_file, undo_stack=None, redo_stack=None):
    before = _unique_sorted_cues(review_cues)
    fallback_dicts = _cues_to_dicts(before)
    fallback_table = review_cues_to_table(before)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    patch = _unique_sorted_cues(latest_cues)
    if not patch:
        gr.Warning("⚠️ 暂无新的转写结果可供追加。请先框选波形并在上方点击「开始转写」。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 未检测到新转写字幕，核对台保持不变。", u_stack, r_stack

    combined = _unique_sorted_cues([*before, *patch])
    added = len(combined) - len(before)
    if added > 0:
        new_undo, new_redo = _push_history(u_stack, before)
        message = f"✅ 已添加 {added} 条本次局部转写字幕；核对时间轴现有 {len(combined)} 条。(可按 Cmd+Z 撤回)"
        gr.Info(f"➕ 成功追加 {added} 条字幕！核对台现有 {len(combined)} 条。")
    else:
        new_undo, new_redo = u_stack, r_stack
        message = "ℹ️ 本次结果与核对时间轴完全重复，未重复添加。"
        gr.Info("ℹ️ 本次转写字幕与已有时间轴完全重复，已自动去重。")

    cues_dicts = _cues_to_dicts(combined)
    table_rows = review_cues_to_table(combined)
    # 纯字幕追加，零波形负担，秒级入轨
    payload = build_review_payload(media_file, combined, include_peaks=False)
    return cues_dicts, table_rows, payload, message, new_undo, new_redo


def export_reviewed_srt(review_cues, media_file):
    cues = _unique_sorted_cues(review_cues)
    if not cues:
        gr.Warning("⚠️ 核对时间轴当前为空，无法导出。请先导入或转写字幕。")
        return gr.update(visible=False), "⚠️ 核对时间轴为空，未生成导出文件。"
    stem = Path(media_file).stem if media_file else "subtitles"
    path = OUTPUT_DIR / f"{stem}.reviewed.srt"
    try:
        write_text_atomic(path, cues_to_srt(cues))
    except Exception as exc:
        gr.Warning(f"⚠️ 写出字幕文件失败：{exc}")
        return gr.update(visible=False), f"⚠️ 导出失败：{exc}"
    gr.Info(f"🎉 字幕已成功导出：{path.name}（共 {len(cues)} 条）")
    return gr.update(value=str(path), visible=True), f"🎉 已导出已核对的最终字幕：`{path.name}`（共 {len(cues)} 条）。"


def sync_selection_to_transcribe_inputs(slice_start_str, slice_end_str):
    s = (slice_start_str or "").strip()
    e = (slice_end_str or "").strip()
    msg = f"⚡ 已同步框选时间至转录区：`{s}` 至 `{e}`。"
    # 彻底杜绝 gr.update(open=True) 导致 Accordion 循环锁死的 Bug，只更新数据框和提示
    return s, e, msg


def transcribe_selection_to_editor(
    media_file,
    engine_name,
    start_str,
    end_str,
    review_cues,
    undo_stack=None,
    redo_stack=None,
    *values,
):
    """就地识别选区语音，直接将新字幕插入核对时间轴，并自动聚焦选中该行供精修。"""
    existing = _unique_sorted_cues(review_cues)
    fallback_dicts = _cues_to_dicts(existing)
    fallback_table = review_cues_to_table(existing)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    if not media_file:
        gr.Warning("⚠️ 请先在上方上传音视频文件。")
        return fallback_dicts, fallback_table, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), "⚠️ 请先上传音视频文件。", u_stack, r_stack

    media_path = Path(media_file)
    if not media_path.exists():
        gr.Warning("⚠️ 媒体临时文件已失效，请重新上传。")
        return fallback_dicts, fallback_table, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), "⚠️ 媒体文件失效。", u_stack, r_stack

    s_val = parse_time_str(start_str)
    e_val = parse_time_str(end_str)
    if s_val is None or e_val is None or e_val <= s_val:
        gr.Warning("⚠️ 选区起止时间无效，请在波形上重新拖拽框选。")
        return fallback_dicts, fallback_table, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), "⚠️ 选区时间不合法。", u_stack, r_stack

    engine = resolve_engine(engine_name)
    is_qwen = (engine is QWEN)

    try:
        if is_qwen:
            config = QwenCtcConfig(**config_kwargs("qwen", values))
            use_alignment = bool(passthrough_kwargs("qwen", values).get("use_alignment", True))
            cues = engine.transcribe_file(
                media_path,
                use_alignment=use_alignment,
                config=config,
                start_time_s=s_val,
                end_time_s=e_val,
                time_offset=s_val,
            )
        else:
            config = build_whisper_config(**config_kwargs("whisper", values))
            gen = passthrough_kwargs("whisper", values)
            ngram = int(gen.get("no_repeat_ngram_size", 5))
            penalty = float(gen.get("repetition_penalty", 1.15))
            cues = ENGINE.transcribe_file(
                media_path,
                config=config,
                no_repeat_ngram_size=ngram,
                repetition_penalty=penalty,
                start_time_s=s_val,
                end_time_s=e_val,
                time_offset=s_val,
            )

        s_out = format_srt_timestamp(s_val)
        e_out = format_srt_timestamp(e_val)

        if not cues:
            gr.Warning("⚠️ 该选区内未检测到清晰语音。已为您填入起止时间，可手动输入文本后点击「➕ 插入为新句」。")
            return (
                fallback_dicts,
                fallback_table,
                gr.update(),
                gr.update(),
                s_out,
                e_out,
                "",
                f"⚠️ [{s_out} → {e_out}] 未检出语音，已填入时间，可输入文本后点「➕ 插入为新句」。",
                u_stack,
                r_stack,
            )

        res_text = " ".join(c.text.strip() for c in cues if c.text.strip())
        actual_start = min(c.start for c in cues)
        actual_end = max(c.end for c in cues)
        final_start = actual_start if abs(actual_start - s_val) < 2.0 else s_val
        final_end = actual_end if abs(actual_end - e_val) < 2.0 else e_val
        if final_end <= final_start:
            final_start, final_end = s_val, e_val

        # 核心：自动入轨并进入撤销栈
        new_cue = SubtitleCue(round(final_start, 3), round(final_end, 3), res_text)
        new_undo, new_redo = _push_history(u_stack, existing)
        sorted_cues = _unique_sorted_cues([*existing, new_cue])

        # 找到这句新字幕在时间轴排序后的准确行号
        new_idx = 1
        for i, c in enumerate(sorted_cues, start=1):
            if c.start == round(final_start, 3) and c.end == round(final_end, 3) and c.text == res_text:
                new_idx = i
                break

        cues_dicts = _cues_to_dicts(sorted_cues)
        table_rows = review_cues_to_table(sorted_cues)
        # 轻量入轨，不带巨型波形
        payload = build_review_payload(media_file, sorted_cues, include_peaks=False)

        final_s_out = format_srt_timestamp(final_start)
        final_e_out = format_srt_timestamp(final_end)
        
        # 静默自动写入草稿与断点进度
        _save_draft_and_progress(media_file, sorted_cues, new_idx, final_s_out, final_e_out, res_text)

        msg = f"⚡ 选区已成功转录并直接入轨（已定位至第 {new_idx} 行）！可直接编辑文字后点「✏️ 更新此行」。"
        gr.Info(f"⚡ 选区识别成功！已直接插入时间轴第 {new_idx} 行。(按 Cmd+Z 可撤销)")

        return (
            cues_dicts,
            table_rows,
            payload,
            new_idx,
            final_s_out,
            final_e_out,
            res_text,
            msg,
            new_undo,
            new_redo,
        )
    except Exception as exc:
        gr.Warning(f"⚠️ 局部转录异常：{exc}")
        return (
            fallback_dicts,
            fallback_table,
            gr.update(),
            gr.update(),
            format_srt_timestamp(s_val) if s_val is not None else "",
            format_srt_timestamp(e_val) if e_val is not None else "",
            "",
            f"⚠️ 局部转写失败：{exc}",
            u_stack,
            r_stack,
        )


def table_to_cues(table_data) -> list[SubtitleCue]:
    cues = []
    rows = []
    if hasattr(table_data, "values"):
        rows = table_data.values.tolist()
    elif isinstance(table_data, list):
        rows = table_data
    elif isinstance(table_data, dict) and "data" in table_data:
        rows = table_data["data"]

    for row in rows:
        if not row or len(row) < 4:
            continue
        if len(row) >= 5:
            _, s_str, e_str, _, text = row[:5]
        else:
            _, s_str, e_str, text = row[:4]

        text = str(text or "").strip()
        if not text:
            continue

        s = parse_time_str(str(s_str))
        e = parse_time_str(str(e_str))
        if s is not None and e is not None and e > s:
            cues.append(SubtitleCue(round(s, 3), round(e, 3), text))
    return _unique_sorted_cues(cues)


def on_select_review_row(evt: gr.SelectData, review_cues):
    cues = _unique_sorted_cues(review_cues)
    if not cues or not evt or evt.index is None:
        return 1, "", "", "", "未选中有效行"
    row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else int(evt.index)
    if 0 <= row_idx < len(cues):
        target = cues[row_idx]
        return (
            row_idx + 1,
            format_srt_timestamp(target.start),
            format_srt_timestamp(target.end),
            target.text,
            f"📌 已选中第 {row_idx + 1} 行（{format_srt_timestamp(target.start)} → {format_srt_timestamp(target.end)}）",
        )
    return 1, "", "", "", "未选中有效行"


def navigate_review_cue_prev(current_idx, review_cues):
    """跳转至上一行基线字幕。"""
    cues = _unique_sorted_cues(review_cues)
    if not cues:
        gr.Warning("⚠️ 核对时间轴为空，暂无字幕可跳转。")
        return gr.update(), gr.update(), gr.update(), gr.update(), "⚠️ 核对时间轴为空"
    try:
        idx = int(current_idx) - 1
    except (ValueError, TypeError):
        idx = 0

    if idx <= 0:
        target_idx = 0
        gr.Info("ℹ️ 已经是第一行字幕。")
    else:
        target_idx = idx - 1

    target = cues[target_idx]
    s_str = format_srt_timestamp(target.start)
    e_str = format_srt_timestamp(target.end)
    return (
        target_idx + 1,
        s_str,
        e_str,
        target.text,
        f"📌 已定位至第 {target_idx + 1}/{len(cues)} 行（{s_str} → {e_str}）",
    )


def navigate_review_cue_next(current_idx, review_cues):
    """跳转至下一行基线字幕。"""
    cues = _unique_sorted_cues(review_cues)
    if not cues:
        gr.Warning("⚠️ 核对时间轴为空，暂无字幕可跳转。")
        return gr.update(), gr.update(), gr.update(), gr.update(), "⚠️ 核对时间轴为空"
    try:
        idx = int(current_idx) - 1
    except (ValueError, TypeError):
        idx = -1

    if idx >= len(cues) - 1:
        target_idx = len(cues) - 1
        gr.Info("ℹ️ 已经是最后一行字幕。")
    else:
        target_idx = idx + 1

    target = cues[target_idx]
    s_str = format_srt_timestamp(target.start)
    e_str = format_srt_timestamp(target.end)
    return (
        target_idx + 1,
        s_str,
        e_str,
        target.text,
        f"📌 已定位至第 {target_idx + 1}/{len(cues)} 行（{s_str} → {e_str}）",
    )


MAX_HISTORY_STEPS = 50


def _push_history(undo_stack, current_cues) -> tuple[list, list]:
    stack = list(undo_stack or [])
    stack.append(_cues_to_dicts(current_cues))
    if len(stack) > MAX_HISTORY_STEPS:
        stack = stack[-MAX_HISTORY_STEPS:]
    return stack, []


def undo_review_action(undo_stack, redo_stack, current_cues, media_file):
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])
    curr = _unique_sorted_cues(current_cues)
    fallback_dicts = _cues_to_dicts(curr)
    fallback_table = review_cues_to_table(curr)

    if not u_stack:
        gr.Warning("⚠️ 已是最初状态，没有可撤销的操作。")
        return (
            fallback_dicts,
            fallback_table,
            gr.update(),
            "⚠️ 没有可撤销的历史操作，字幕保持完好。",
            u_stack,
            r_stack,
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )

    previous_snapshot = u_stack.pop()
    r_stack.append(fallback_dicts)
    if len(r_stack) > MAX_HISTORY_STEPS:
        r_stack = r_stack[-MAX_HISTORY_STEPS:]

    cues = _unique_sorted_cues(previous_snapshot)
    cues_dicts = _cues_to_dicts(cues)
    table_rows = review_cues_to_table(cues)
    # 纯字幕撤销，不传波形
    payload = build_review_payload(media_file, cues, include_peaks=False)
    gr.Info(f"↩️ 已成功撤销！核对轴现有 {len(cues)} 条字幕。")

    first_cue = cues[0] if cues else None
    return (
        cues_dicts,
        table_rows,
        payload,
        f"↩️ 已撤销上一步操作，当前核对轴共 {len(cues)} 条字幕。",
        u_stack,
        r_stack,
        1,
        format_srt_timestamp(first_cue.start) if first_cue else "",
        format_srt_timestamp(first_cue.end) if first_cue else "",
        first_cue.text if first_cue else "",
    )


def redo_review_action(undo_stack, redo_stack, current_cues, media_file):
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])
    curr = _unique_sorted_cues(current_cues)
    fallback_dicts = _cues_to_dicts(curr)
    fallback_table = review_cues_to_table(curr)

    if not r_stack:
        gr.Warning("⚠️ 没有可重做的操作。")
        return (
            fallback_dicts,
            fallback_table,
            gr.update(),
            "⚠️ 没有可重做的历史操作，字幕保持完好。",
            u_stack,
            r_stack,
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )

    next_snapshot = r_stack.pop()
    u_stack.append(fallback_dicts)
    if len(u_stack) > MAX_HISTORY_STEPS:
        u_stack = u_stack[-MAX_HISTORY_STEPS:]

    cues = _unique_sorted_cues(next_snapshot)
    cues_dicts = _cues_to_dicts(cues)
    table_rows = review_cues_to_table(cues)
    # 纯字幕重做，不传波形
    payload = build_review_payload(media_file, cues, include_peaks=False)
    gr.Info(f"↪️ 已成功重做！核对轴现有 {len(cues)} 条字幕。")

    first_cue = cues[0] if cues else None
    return (
        cues_dicts,
        table_rows,
        payload,
        f"↪️ 已重做操作，当前核对轴共 {len(cues)} 条字幕。",
        u_stack,
        r_stack,
        1,
        format_srt_timestamp(first_cue.start) if first_cue else "",
        format_srt_timestamp(first_cue.end) if first_cue else "",
        first_cue.text if first_cue else "",
    )


def update_single_review_cue(row_num, start_str, end_str, text, review_cues, media_file, undo_stack=None, redo_stack=None):
    cues = _unique_sorted_cues(review_cues)
    fallback_dicts = _cues_to_dicts(cues)
    fallback_table = review_cues_to_table(cues)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    if not cues:
        gr.Warning("⚠️ 核对时间轴当前为空，请先导入或转写字幕。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 当前时间轴为空，无法修改。", u_stack, r_stack

    try:
        idx = int(row_num) - 1
    except (ValueError, TypeError):
        gr.Warning("⚠️ 条目序号无效，请输入整数序号（例如 1）。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 序号格式无效，已有字幕保持完好。", u_stack, r_stack

    if not (0 <= idx < len(cues)):
        gr.Warning(f"⚠️ 条目序号 {row_num} 超出有效范围 (当前共 {len(cues)} 行)。")
        return fallback_dicts, fallback_table, gr.update(), f"⚠️ 序号超出范围 (1 ~ {len(cues)})，已有字幕保持完好。", u_stack, r_stack

    s = parse_time_str(start_str)
    e = parse_time_str(end_str)
    if s is None or e is None:
        gr.Warning("⚠️ 时间格式不正确，请输入形如 00:01:23,456 或纯秒数。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 时间格式无效，已有字幕保持完好。", u_stack, r_stack
    if e <= s:
        gr.Warning("⚠️ 结束时间必须大于起始时间！")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 结束时间早于或等于起始时间，修改未保存。", u_stack, r_stack

    new_text = (text or "").strip()
    if not new_text:
        gr.Warning("⚠️ 字幕内容不能为空。如需移除该行，请点击「🗑️ 删除」。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 字幕文本为空，已有字幕保持完好。", u_stack, r_stack

    try:
        new_undo, new_redo = _push_history(u_stack, cues)
        cues[idx] = SubtitleCue(round(s, 3), round(e, 3), new_text)
        sorted_cues = _unique_sorted_cues(cues)
        # 单行更新，include_peaks=False，杜绝转圈卡顿
        payload = build_review_payload(media_file, sorted_cues, include_peaks=False)
        table_rows = review_cues_to_table(sorted_cues)
        cues_dicts = _cues_to_dicts(sorted_cues)
        # === 新增：自动写盘草稿并记录进度 ===
        _save_draft_and_progress(media_file, sorted_cues, row_num, format_srt_timestamp(s), format_srt_timestamp(e), new_text)
        gr.Info(f"✏️ 成功更新第 {row_num} 行字幕内容！(可按 Cmd+Z 随时撤销)")
        return cues_dicts, table_rows, payload, f"✅ 已成功更新第 {row_num} 行字幕并重新对齐时间轴！", new_undo, new_redo
    except Exception as exc:
        gr.Warning(f"⚠️ 更新失败：{exc}")
        return fallback_dicts, fallback_table, gr.update(), f"⚠️ 更新异常：{exc}", u_stack, r_stack


def delete_single_review_cue(row_num, review_cues, media_file, undo_stack=None, redo_stack=None):
    cues = _unique_sorted_cues(review_cues)
    fallback_dicts = _cues_to_dicts(cues)
    fallback_table = review_cues_to_table(cues)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    if not cues:
        gr.Warning("⚠️ 核对时间轴当前为空，无需删除。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 时间轴为空，无需删除。", gr.update(), gr.update(), gr.update(), gr.update(), u_stack, r_stack

    try:
        idx = int(row_num) - 1
    except (ValueError, TypeError):
        gr.Warning("⚠️ 请指定要删除的有效条目序号。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 序号无效，未执行删除。", gr.update(), gr.update(), gr.update(), gr.update(), u_stack, r_stack

    if not (0 <= idx < len(cues)):
        gr.Warning(f"⚠️ 条目序号 {row_num} 超出有效范围 (共 {len(cues)} 行)。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 序号超出范围，未执行删除。", gr.update(), gr.update(), gr.update(), gr.update(), u_stack, r_stack

    try:
        new_undo, new_redo = _push_history(u_stack, cues)
        removed = cues.pop(idx)
        sorted_cues = _unique_sorted_cues(cues)
        # 单行删除，include_peaks=False
        payload = build_review_payload(media_file, sorted_cues, include_peaks=False)
        table_rows = review_cues_to_table(sorted_cues)
        cues_dicts = _cues_to_dicts(sorted_cues)

        next_idx = max(1, min(idx + 1, len(sorted_cues)))
        next_cue = sorted_cues[next_idx - 1] if sorted_cues else None
        next_start = format_srt_timestamp(next_cue.start) if next_cue else ""
        next_end = format_srt_timestamp(next_cue.end) if next_cue else ""
        next_text = next_cue.text if next_cue else ""

        gr.Info(f"🗑️ 已成功删除第 {row_num} 行字幕！(如误删可按 Cmd+Z 随时撤销恢复)")
        return (
            cues_dicts,
            table_rows,
            payload,
            f"🗑️ 已成功删除第 {row_num} 行字幕「{removed.text}」，剩余 {len(sorted_cues)} 条。(支持 Cmd+Z 撤销恢复)",
            next_idx,
            next_start,
            next_end,
            next_text,
            new_undo,
            new_redo,
        )
    except Exception as exc:
        gr.Warning(f"⚠️ 删除失败：{exc}")
        return fallback_dicts, fallback_table, gr.update(), f"⚠️ 删除异常：{exc}", gr.update(), gr.update(), gr.update(), gr.update(), u_stack, r_stack


def insert_new_review_cue(start_str, end_str, text, review_cues, media_file, undo_stack=None, redo_stack=None):
    cues = _unique_sorted_cues(review_cues)
    fallback_dicts = _cues_to_dicts(cues)
    fallback_table = review_cues_to_table(cues)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    s_clean = (start_str or "").strip()
    e_clean = (end_str or "").strip()
    if not s_clean or not e_clean:
        gr.Warning("⚠️ 请先填写起始时间与结束时间（例如 00:01:20,000 或纯秒数 80.0）。\n若您刚框选了波形，可先在波形工具条点击「⚡ 识别此段送入精修」自动获取时间。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 未填写起止时间，插入未执行，已有字幕完好无损。", u_stack, r_stack

    s = parse_time_str(s_clean)
    e = parse_time_str(e_clean)
    if s is None or e is None:
        gr.Warning("⚠️ 时间格式无法解析，请检查输入（支持 00:01:23,456 或 83.456）。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 时间格式无效，插入未执行，已有字幕完好无损。", u_stack, r_stack

    if e <= s:
        gr.Warning(f"⚠️ 结束时间 ({e_clean}) 必须大于起始时间 ({s_clean})！")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 结束时间不合法，插入未执行，已有字幕完好无损。", u_stack, r_stack

    new_text = (text or "").strip()
    if not new_text:
        gr.Warning("⚠️ 请输入字幕文本内容后再点击「插入为新字幕」。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 字幕文本为空，插入未执行，已有字幕完好无损。", u_stack, r_stack

    try:
        new_undo, new_redo = _push_history(u_stack, cues)
        cues.append(SubtitleCue(round(s, 3), round(e, 3), new_text))
        sorted_cues = _unique_sorted_cues(cues)
        # 单行插入，include_peaks=False
        payload = build_review_payload(media_file, sorted_cues, include_peaks=False)
        table_rows = review_cues_to_table(sorted_cues)
        cues_dicts = _cues_to_dicts(sorted_cues)
        # 建议加上这行：手动插入新句时也自动保存草稿和进度
        _save_draft_and_progress(media_file, sorted_cues, len(sorted_cues), format_srt_timestamp(s), format_srt_timestamp(e), new_text)
        gr.Info(f"➕ 成功插入新字幕：[{format_srt_timestamp(s)} → {format_srt_timestamp(e)}]！(可按 Cmd+Z 撤回)")
        return cues_dicts, table_rows, payload, f"➕ 已成功插入新字幕并重新排序，当前核对台共 {len(sorted_cues)} 条字幕。", new_undo, new_redo
    except Exception as exc:
        gr.Warning(f"⚠️ 插入异常：{exc}")
        return fallback_dicts, fallback_table, gr.update(), f"⚠️ 插入失败：{exc}", u_stack, r_stack


def apply_table_edits(table_data, media_file, current_cues=None, undo_stack=None, redo_stack=None):
    existing_cues = _unique_sorted_cues(current_cues)
    fallback_dicts = _cues_to_dicts(existing_cues)
    fallback_table = review_cues_to_table(existing_cues)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    try:
        cues = table_to_cues(table_data)
    except Exception as exc:
        gr.Warning(f"⚠️ 表格解析异常：{exc}，已恢复原数据。")
        return fallback_dicts, fallback_table, gr.update(), f"⚠️ 表格数据无效：{exc}", u_stack, r_stack

    if not cues:
        gr.Warning("⚠️ 表格中未检测到有效字幕内容。若表格暂未完成编辑，请检查后重试。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 表格中未读取到有效字幕，未覆盖已有数据。", u_stack, r_stack

    try:
        new_undo, new_redo = _push_history(u_stack, existing_cues)
        # 保存表格全量编辑，include_peaks=False
        payload = build_review_payload(media_file, cues, include_peaks=False)
        table_rows = review_cues_to_table(cues)
        cues_dicts = _cues_to_dicts(cues)

        try:
            stem = Path(media_file).stem if media_file else "subtitles"
            draft_path = OUTPUT_DIR / f"{stem}.autosave_draft.srt"
            write_text_atomic(draft_path, cues_to_srt(cues))
            saved_tip = f"（已自动写盘备份至 outputs/{draft_path.name}）"
        except Exception:
            saved_tip = ""

        gr.Info(f"💾 表格全量修改已成功保存！当前共 {len(cues)} 条字幕。{saved_tip}(可按 Cmd+Z 撤回)")
        return cues_dicts, table_rows, payload, f"💾 已成功应用表格全部修改：当前时间轴共 {len(cues)} 条有效字幕！{saved_tip}", new_undo, new_redo
    except Exception as exc:
        gr.Warning(f"⚠️ 保存表格异常：{exc}")
        return fallback_dicts, fallback_table, gr.update(), f"⚠️ 保存失败：{exc}", u_stack, r_stack


def clean_review_cues(review_cues, media_file, undo_stack=None, redo_stack=None):
    cues = _unique_sorted_cues(review_cues)
    fallback_dicts = _cues_to_dicts(cues)
    fallback_table = review_cues_to_table(cues)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    if not cues:
        gr.Warning("⚠️ 核对台字幕为空，无需清理。")
        return fallback_dicts, fallback_table, gr.update(), "核对台字幕为空。", u_stack, r_stack

    try:
        cleaned = remove_ellipsis_only_cues(cues)
        removed_count = len(cues) - len(cleaned)
        if removed_count == 0:
            gr.Info("ℹ️ 核对台中未发现纯标点或纯省略号的空条目。")
            return fallback_dicts, fallback_table, gr.update(), "核对台中未发现纯标点或纯省略号的空条目。", u_stack, r_stack
        new_undo, new_redo = _push_history(u_stack, cues)
        # 清理标点，include_peaks=False
        payload = build_review_payload(media_file, cleaned, include_peaks=False)
        table_rows = review_cues_to_table(cleaned)
        cues_dicts = _cues_to_dicts(cleaned)
        gr.Info(f"🧹 已成功清理 {removed_count} 条纯标点空行！(可按 Cmd+Z 撤回)")
        return cues_dicts, table_rows, payload, f"🧹 已成功清理 {removed_count} 条纯标点空条目，剩余 {len(cleaned)} 条有效字幕！", new_undo, new_redo
    except Exception as exc:
        gr.Warning(f"⚠️ 清理失败：{exc}")
        return fallback_dicts, fallback_table, gr.update(), f"⚠️ 清理异常：{exc}", u_stack, r_stack


def clear_all_review_cues(media_file, current_cues=None, undo_stack=None, redo_stack=None):
    existing_cues = _unique_sorted_cues(current_cues)
    fallback_dicts = _cues_to_dicts(existing_cues)
    fallback_table = review_cues_to_table(existing_cues)
    u_stack = list(undo_stack or [])
    r_stack = list(redo_stack or [])

    if not existing_cues:
        gr.Warning("⚠️ 核对台字幕已经为空，无需清空。")
        return fallback_dicts, fallback_table, gr.update(), "⚠️ 核对台字幕已为空。", u_stack, r_stack

    try:
        new_undo, new_redo = _push_history(u_stack, existing_cues)
        # 清空字幕，include_peaks=False
        payload = build_review_payload(media_file, [], include_peaks=False)
        gr.Info("🧹 已成功清空核对台字幕。(可按 Cmd+Z 撤回恢复)")
        return [], [], payload, "🧹 已清空核对台全部字幕，可随时按 Cmd+Z 撤销恢复。", new_undo, new_redo
    except Exception as exc:
        gr.Warning(f"⚠️ 清空操作异常：{exc}")
        return fallback_dicts, fallback_table, gr.update(), f"⚠️ 清空异常：{exc}", u_stack, r_stack


REVIEWER_HTML = """
<section id="reviewer-shell" class="reviewer-shell">
  <div class="reviewer-empty">上传媒体后，这里会自动载入视频监看画面与精确时间轴波形轨。</div>
</section>
"""

REVIEWER_CLIENT_JS = r"""
(payloadText) => {
  try {
    const shell = document.querySelector('#reviewer-shell');
    if (!shell) return;
    let data;
    try { data = JSON.parse(payloadText || '{}'); } catch (_) { return; }

    if (data.is_patch_only) {
      // 纯字幕补丁：只更新字幕轨，绝不重建画面（关闭监看后也不该被顶掉）
      if (window.__reviewerInstance) {
        window.__reviewerInstance.updateCues(data.cues || []);
      }
      return;
    }

    if (!data.src) {
      // 关闭监看 / 片源不可用：销毁旧播放器实例，避免残留快捷键与悬空引用
      window.__reviewerInstance = null;
      if (window.__reviewerKeyHandler) {
        window.removeEventListener('keydown', window.__reviewerKeyHandler);
        window.__reviewerKeyHandler = null;
      }
      window.onbeforeunload = null;
      shell.innerHTML = data.error || '<div class="reviewer-empty">上传媒体后，这里会自动载入视频监看画面与精确时间轴波形轨。</div>';
      return;
    }
    const existingVideo = shell.querySelector('.reviewer-video');
    if (existingVideo && existingVideo.getAttribute('src') === data.src && window.__reviewerInstance) {
      window.__reviewerInstance.updateCues(data.cues || []);
      return;
    }
    const esc = (text) => String(text || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    
    let duration = Number(data.duration || 0);
    const peaks = data.peaks || [];
    const cues = data.cues || [];

    shell.innerHTML = `
      <div class="reviewer-stage" id="rw-stage">
        <video class="reviewer-video" preload="metadata" src="${data.src}"></video>
        <div class="reviewer-caption" id="reviewer-caption"></div>
        
        <div class="rw-center-play-indicator" id="rw-center-play" style="display:none;">
          <div class="rw-center-play-icon">▶</div>
        </div>

        <div class="reviewer-custom-controls" id="rw-custom-controls">
          <div class="rw-scrub-track-wrap">
            <input type="range" class="rw-scrubber-slider" id="rw-scrubber-slider" min="0" max="${Number(data.duration || 0) || 100}" step="0.04" value="0">
            <div class="rw-scrub-hover-tip" id="rw-scrub-tip" style="display:none;">00:00:00.000</div>
          </div>

          <div class="rw-controls-row">
            <div class="rw-ctrl-left">
              <button type="button" class="rw-ctrl-btn rw-btn-main-play" id="rw-btn-play-toggle" title="播放/暂停 (空格)">▶</button>
              <button type="button" class="rw-ctrl-btn" id="rw-btn-step-prev" title="后退 1 帧 (←)">⏮ 1F</button>
              <button type="button" class="rw-ctrl-btn" id="rw-btn-step-next" title="前进 1 帧 (→)">⏭ 1F</button>
              
              <div class="rw-ctrl-time-display">
                <span class="rw-time-cur" id="rw-ctrl-current">00:00:00.000</span>
                <span class="rw-time-sep">/</span>
                <span class="rw-time-dur" id="rw-ctrl-total">00:00:00.000</span>
              </div>
            </div>

            <div class="rw-ctrl-right">
              <button type="button" class="rw-ctrl-btn" id="rw-btn-mute" title="静音切换">🔊</button>
              <input type="range" class="rw-vol-slider" id="rw-vol-slider" min="0" max="1" step="0.05" value="1" title="调节音量">
              <button type="button" class="rw-ctrl-btn" id="rw-btn-fullscreen" title="全屏画面">⛶</button>
            </div>
          </div>
        </div>
      </div>

      <div class="reviewer-wave-header">
        <div class="reviewer-clock">
          <span class="reviewer-playhead-time" id="rw-current-time">00:00:00.000</span>
          <span class="reviewer-divider">/</span>
          <span class="reviewer-total-time" id="rw-total-time">00:00:00.000</span>
        </div>

        <div class="reviewer-selection-bar" id="rw-selection-bar" style="display:none;">
          <span class="rw-sel-icon">✂️</span>
          <span class="rw-sel-info" id="rw-selection-info">已选: 00:00:00.000 → 00:00:00.000 (0.00s)</span>
          <button type="button" class="rw-btn rw-btn-play-sel" id="rw-play-sel-btn" title="试听当前框选声音">▶ 试听</button>
          <button type="button" class="rw-btn rw-btn-transcribe-sel" id="rw-transcribe-sel-btn" title="立即识别当前选区并直接插入时间轴">⚡ 识别并直接入轨</button>
          <button type="button" class="rw-btn rw-btn-sync" id="rw-sync-btn" title="仅同步起止时间到顶部时间切片输入框">⏱ 同步时间到顶部</button>
          <button type="button" class="rw-btn rw-btn-clear" id="rw-clear-sel-btn">✕</button>
        </div>

        <div class="reviewer-zoom-controls">
          <button type="button" class="rw-tool-btn" id="rw-zoom-out" title="缩小轨道">🔍 -</button>
          <input type="range" class="rw-zoom-slider" id="rw-zoom-slider" min="1" max="50" step="0.5" value="1" title="水平缩放轨道">
          <button type="button" class="rw-tool-btn" id="rw-zoom-in" title="放大轨道">🔍 +</button>
          <button type="button" class="rw-tool-btn" id="rw-zoom-fit" title="显示全片视图">100% 全景</button>
          <button type="button" class="rw-tool-btn" id="rw-center-playhead" title="聚焦到当前播放头并放大50倍">🎯 聚焦</button>
          <button type="button" class="rw-tool-btn is-on" id="rw-follow-toggle" title="播放时自动跟随播放头（字幕始终同步）">🧲 跟随</button>
          <span class="reviewer-zoom-level" id="rw-zoom-level">1.0×</span>
        </div>
      </div>

      <div class="reviewer-canvas-wrap" id="rw-canvas-wrap">
        <canvas class="reviewer-ruler-canvas" id="rw-ruler-canvas" height="24"></canvas>
        <canvas class="reviewer-wave-canvas" id="rw-wave-canvas" height="110" aria-label="音频波形时间轴"></canvas>
        <div class="reviewer-playhead-line" id="rw-playhead-line" style="display:none;">
          <div class="rw-playhead-flag">▼</div>
        </div>
      </div>

      <div class="reviewer-wave-hint">
        <div class="rw-hint-row">⌨️ <strong>快捷键：</strong><span>【<strong>空格</strong>】播放/暂停</span> ｜ <span>【<strong>← / →</strong>】1 帧微调（约 0.042s）</span> ｜ <span>【<strong>Shift + ← / →</strong>】5 帧快速定位</span> ｜ <span>【<strong>Cmd/Ctrl + Z</strong>】撤销</span> ｜ <span>【<strong>Cmd/Ctrl + Shift + Z</strong>】重做</span></div>
        <div class="rw-hint-row">💡 <strong>手势：</strong><span>Mac 触控板在波形上<strong>双指横滑平移</strong>，<strong>双指垂直/捏合无级缩放</strong> ｜ 拖拽框选后点击<strong>「⚡ 识别此段送入精修」</strong>即可零位移秒出字幕！</span></div>
      </div>
    `;

    const stage = shell.querySelector('#rw-stage');
    const video = shell.querySelector('.reviewer-video');
    const caption = shell.querySelector('#reviewer-caption');
    const waveCanvas = shell.querySelector('#rw-wave-canvas');
    const rulerCanvas = shell.querySelector('#rw-ruler-canvas');
    const canvasWrap = shell.querySelector('#rw-canvas-wrap');
    const playheadLine = shell.querySelector('#rw-playhead-line');
    const currentTimeText = shell.querySelector('#rw-current-time');
    const totalTimeText = shell.querySelector('#rw-total-time');
    const selectionBar = shell.querySelector('#rw-selection-bar');
    const selectionInfo = shell.querySelector('#rw-selection-info');
    const syncBtn = shell.querySelector('#rw-sync-btn');
    const transcribeSelBtn = shell.querySelector('#rw-transcribe-sel-btn');
    const playSelBtn = shell.querySelector('#rw-play-sel-btn');
    const clearSelBtn = shell.querySelector('#rw-clear-sel-btn');
    const zoomInBtn = shell.querySelector('#rw-zoom-in');
    const zoomOutBtn = shell.querySelector('#rw-zoom-out');
    const zoomFitBtn = shell.querySelector('#rw-zoom-fit');
    const centerPlayheadBtn = shell.querySelector('#rw-center-playhead');
    const followToggleBtn = shell.querySelector('#rw-follow-toggle');
    const zoomSlider = shell.querySelector('#rw-zoom-slider');
    const zoomLevelText = shell.querySelector('#rw-zoom-level');

    const scrubberSlider = shell.querySelector('#rw-scrubber-slider');
    const scrubTip = shell.querySelector('#rw-scrub-tip');
    const playToggleBtn = shell.querySelector('#rw-btn-play-toggle');
    const stepPrevBtn = shell.querySelector('#rw-btn-step-prev');
    const stepNextBtn = shell.querySelector('#rw-btn-step-next');
    const ctrlCurrentTime = shell.querySelector('#rw-ctrl-current');
    const ctrlTotalTime = shell.querySelector('#rw-ctrl-total');
    const muteBtn = shell.querySelector('#rw-btn-mute');
    const volSlider = shell.querySelector('#rw-vol-slider');
    const fullscreenBtn = shell.querySelector('#rw-btn-fullscreen');

    const waveCtx = waveCanvas.getContext('2d');
    const rulerCtx = rulerCanvas.getContext('2d');

    let viewStart = 0;
    let viewSpan = duration || 1;
    let selected = null;
    let isDragging = false;
    let dragAnchor = null;
    let isPlayingSelection = false;
    let lastSyncedCueIndex = -1;
    let isScrubbingSlider = false;
    let followPlayhead = true;
    let followUserLocked = false;
    let hideControlsTimer = null;

    window.__isTranscribing = false;
    let syncInputDebounceTimer = null;

    const format = sec => {
      sec = Math.max(0, Number(sec) || 0);
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${s.toFixed(3).padStart(6,'0')}`;
    };

    if (duration > 0) {
      totalTimeText.textContent = format(duration);
      if (ctrlTotalTime) ctrlTotalTime.textContent = format(duration);
      if (scrubberSlider) scrubberSlider.max = String(duration);
    }

    // ── 字幕叠加层索引 ───────────────────────────────────────────────
    // 关键点 1：同一时间区间内的多条字幕（中日双语 SRT 通常把日语行和
    // 中文行拆成两条、起止时间完全相同）必须聚合成一个「字幕块」多行显示，
    // 不能用 find() 只取第一条，否则永远只显示一行。
    // 关键点 2：字幕显示与下方波形的缩放视窗完全解耦，任何时间点都要更新。
    let captionGroups = [];
    let lastCaptionText = null;

    const rebuildCaptionIndex = () => {
      const buckets = new Map();
      const groups = [];
      for (const cue of cues) {
        const start = Number(cue.start) || 0;
        const end = Number(cue.end) || 0;
        const key = `${Math.round(start * 1000)}|${Math.round(end * 1000)}`;
        let group = buckets.get(key);
        if (!group) {
          group = { start, end, lines: [], seen: new Set() };
          buckets.set(key, group);
          groups.push(group);
        }
        const text = String(cue.text == null ? '' : cue.text).trim();
        if (!text || group.seen.has(text)) continue;
        group.seen.add(text);
        group.lines.push(text);
      }
      groups.sort((a, b) => (a.start - b.start) || (a.end - b.end));
      captionGroups = groups;
      lastCaptionText = null;
    };

    const findCaptionGroup = (time) => {
      const groups = captionGroups;
      if (!groups.length) return null;
      let lo = 0;
      let hi = groups.length - 1;
      let idx = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (groups[mid].start <= time + 0.0005) { idx = mid; lo = mid + 1; }
        else { hi = mid - 1; }
      }
      if (idx === -1) return null;
      for (let i = idx; i >= 0 && i > idx - 64; i--) {
        if (groups[i].end + 0.0005 >= time) return groups[i];
        if (groups[i].end < time - 60) break;
      }
      return null;
    };

    const updateCaption = (time) => {
      if (!caption) return;
      const group = findCaptionGroup(time);
      const text = group ? group.lines.join('\n') : '';
      if (text === lastCaptionText) return;
      lastCaptionText = text;
      if (!text) {
        caption.textContent = '';
        caption.style.display = 'none';
      } else {
        caption.textContent = text;
        caption.style.display = 'block';
      }
    };

    rebuildCaptionIndex();

    const clampView = () => {
      const minSpan = Math.min(duration || 1, 0.4);
      const maxSpan = duration || 1;
      viewSpan = Math.max(minSpan, Math.min(maxSpan, viewSpan));
      viewStart = Math.max(0, Math.min(Math.max(0, duration - viewSpan), viewStart));
      const ratio = duration ? (duration / viewSpan) : 1;
      zoomSlider.value = Math.min(50, Math.max(1, ratio));
      zoomLevelText.textContent = `${ratio.toFixed(1)}×`;
    };

    const drawRuler = () => {
      const rect = rulerCanvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      rulerCanvas.width = Math.max(1, Math.floor(rect.width * ratio));
      rulerCanvas.height = Math.max(1, Math.floor(rect.height * ratio));
      rulerCtx.setTransform(ratio, 0, 0, ratio, 0, 0);

      const w = rect.width;
      const h = rect.height;

      rulerCtx.fillStyle = '#0f172a';
      rulerCtx.fillRect(0, 0, w, h);

      if (!duration) return;

      const targetDivs = w / 90;
      const rawStep = viewSpan / targetDivs;
      const niceSteps = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];
      let step = niceSteps[niceSteps.length - 1];
      for (const ns of niceSteps) {
        if (ns >= rawStep) { step = ns; break; }
      }

      rulerCtx.strokeStyle = 'rgba(148, 163, 184, 0.35)';
      rulerCtx.fillStyle = '#94a3b8';
      rulerCtx.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
      rulerCtx.textBaseline = 'bottom';

      const firstMark = Math.floor(viewStart / step) * step;
      for (let t = firstMark; t <= viewStart + viewSpan; t += step) {
        if (t < viewStart) continue;
        const x = ((t - viewStart) / viewSpan) * w;
        rulerCtx.beginPath();
        rulerCtx.moveTo(x, h);
        rulerCtx.lineTo(x, h - 8);
        rulerCtx.stroke();

        const subStep = step / 5;
        for (let s = 1; s < 5; s++) {
          const subT = t + s * subStep;
          if (subT > viewStart && subT < viewStart + viewSpan) {
            const subX = ((subT - viewStart) / viewSpan) * w;
            rulerCtx.beginPath();
            rulerCtx.moveTo(subX, h);
            rulerCtx.lineTo(subX, h - 4);
            rulerCtx.stroke();
          }
        }

        const label = step < 1 ? t.toFixed(2) + 's' : (t >= 60 ? `${Math.floor(t/60)}m${(t%60).toFixed(0)}s` : t.toFixed(0) + 's');
        rulerCtx.fillText(label, x + 3, h - 3);
      }

      rulerCtx.strokeStyle = 'rgba(99, 102, 241, 0.4)';
      rulerCtx.beginPath();
      rulerCtx.moveTo(0, h - 0.5);
      rulerCtx.lineTo(w, h - 0.5);
      rulerCtx.stroke();
    };

    const drawWave = () => {
      const rect = waveCanvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      waveCanvas.width = Math.max(1, Math.floor(rect.width * ratio));
      waveCanvas.height = Math.max(1, Math.floor(rect.height * ratio));
      waveCtx.setTransform(ratio, 0, 0, ratio, 0, 0);

      const w = rect.width;
      const h = rect.height;
      const mid = h / 2;

      waveCtx.fillStyle = '#090d16';
      waveCtx.fillRect(0, 0, w, h);

      waveCtx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
      waveCtx.lineWidth = 1;
      waveCtx.beginPath();
      waveCtx.moveTo(0, mid);
      waveCtx.lineTo(w, mid);
      waveCtx.stroke();

      if (!duration) return;

      if (cues && cues.length > 0) {
        waveCtx.fillStyle = 'rgba(56, 189, 248, 0.12)';
        for (const cue of cues) {
          if (cue.end < viewStart || cue.start > viewStart + viewSpan) continue;
          const x1 = ((cue.start - viewStart) / viewSpan) * w;
          const x2 = ((cue.end - viewStart) / viewSpan) * w;
          waveCtx.fillRect(Math.max(0, x1), 0, Math.min(w, x2) - Math.max(0, x1), h);
          
          waveCtx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
          waveCtx.beginPath();
          waveCtx.moveTo(Math.max(0, x1), 2);
          waveCtx.lineTo(Math.min(w, x2), 2);
          waveCtx.stroke();
        }
      }

      if (peaks.length > 0) {
        const firstIdx = Math.max(0, Math.floor((viewStart / duration) * peaks.length));
        const lastIdx = Math.min(peaks.length, Math.ceil(((viewStart + viewSpan) / duration) * peaks.length));

        const pts = [];
        for (let i = firstIdx; i < lastIdx; i++) {
          const t = (i / Math.max(1, peaks.length - 1)) * duration;
          const x = ((t - viewStart) / viewSpan) * w;
          const amp = Math.max(1.5, peaks[i] * (h * 0.44));
          pts.push({ x, amp });
        }

        if (pts.length > 0) {
          waveCtx.fillStyle = 'rgba(129, 140, 248, 0.45)';
          waveCtx.beginPath();
          waveCtx.moveTo(pts[0].x, mid - pts[0].amp);
          for (let j = 1; j < pts.length; j++) {
            waveCtx.lineTo(pts[j].x, mid - pts[j].amp);
          }
          for (let j = pts.length - 1; j >= 0; j--) {
            waveCtx.lineTo(pts[j].x, mid + pts[j].amp);
          }
          waveCtx.closePath();
          waveCtx.fill();

          waveCtx.strokeStyle = '#a5b4fc';
          waveCtx.lineWidth = 1.2;
          waveCtx.beginPath();
          for (let j = 0; j < pts.length; j++) {
            if (j === 0) waveCtx.moveTo(pts[j].x, mid - pts[j].amp);
            else waveCtx.lineTo(pts[j].x, mid - pts[j].amp);
          }
          waveCtx.stroke();

          waveCtx.beginPath();
          for (let j = 0; j < pts.length; j++) {
            if (j === 0) waveCtx.moveTo(pts[j].x, mid + pts[j].amp);
            else waveCtx.lineTo(pts[j].x, mid + pts[j].amp);
          }
          waveCtx.stroke();
        }
      }

      if (selected && duration) {
        const s0 = Math.min(selected[0], selected[1]);
        const s1 = Math.max(selected[0], selected[1]);
        const x1 = ((s0 - viewStart) / viewSpan) * w;
        const x2 = ((s1 - viewStart) / viewSpan) * w;

        if (x2 >= 0 && x1 <= w) {
          waveCtx.fillStyle = 'rgba(99, 102, 241, 0.38)';
          waveCtx.fillRect(Math.max(0, x1), 0, Math.min(w, x2) - Math.max(0, x1), h);

          waveCtx.strokeStyle = '#a5b4fc';
          waveCtx.lineWidth = 2;
          if (x1 >= 0 && x1 <= w) {
            waveCtx.beginPath();
            waveCtx.moveTo(x1, 0);
            waveCtx.lineTo(x1, h);
            waveCtx.stroke();
          }
          if (x2 >= 0 && x2 <= w) {
            waveCtx.beginPath();
            waveCtx.moveTo(x2, 0);
            waveCtx.lineTo(x2, h);
            waveCtx.stroke();
          }
        }
      }
    };

    const setGradioValue = (elemId, value, triggerEvents = true) => {
      const container = document.getElementById(elemId);
      if (!container) return false;
      const input = container.querySelector('input') || container.querySelector('textarea');
      if (!input) return false;
      const nativeSetter = Object.getOwnPropertyDescriptor(
        input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
        'value'
      ).set;
      nativeSetter.call(input, value);

      if (triggerEvents && !window.__isTranscribing) {
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      return true;
    };

    const safeSeekVideo = (targetSec) => {
      targetSec = Math.max(0, Math.min(duration || Infinity, Number(targetSec) || 0));
      if (typeof video.fastSeek === 'function') {
        try { video.fastSeek(targetSec); } catch (_) { video.currentTime = targetSec; }
      } else {
        video.currentTime = targetSec;
      }
    };

    // 播放头跑出可视范围时，把视窗整页平移到播放头附近（默认落在左侧 15% 处），
    // 保证放大后长时间播放也不会「看不见播放头」。返回是否真的移动了视窗。
    const ensurePlayheadVisible = (cur) => {
      if (!followPlayhead || !duration) return false;
      if (isDragging || isScrubbingSlider) return false;
      if (cur >= viewStart && cur <= viewStart + viewSpan) return false;
      const maxStart = Math.max(0, duration - viewSpan);
      const next = Math.max(0, Math.min(maxStart, cur - viewSpan * 0.15));
      if (Math.abs(next - viewStart) < 1e-6) return false;
      viewStart = next;
      return true;
    };

    const updatePlayhead = (syncInputBoxes = false) => {
      const cur = video.currentTime;
      currentTimeText.textContent = format(cur);
      if (ctrlCurrentTime && !isScrubbingSlider) {
        ctrlCurrentTime.textContent = format(cur);
      }
      if (scrubberSlider && !isScrubbingSlider && duration > 0) {
        scrubberSlider.value = String(cur);
      }

      if (isPlayingSelection && selected) {
        const endLimit = Math.max(selected[0], selected[1]);
        if (cur >= endLimit) {
          video.pause();
          isPlayingSelection = false;
          playSelBtn.textContent = '▶ 试听';
        }
      }

      const canSyncToGradio = syncInputBoxes && !window.__isTranscribing && !isEditingText() && cues.length > 0;
      if (canSyncToGradio) {
        let matchedIdx = -1;
        for (let i = cues.length - 1; i >= 0; i--) {
          if (cur >= cues[i].start) {
            matchedIdx = i;
            break;
          }
        }
        if (matchedIdx === -1 && cur < cues[0].start) {
          matchedIdx = 0;
        }
        if (matchedIdx !== -1 && matchedIdx !== lastSyncedCueIndex) {
          lastSyncedCueIndex = matchedIdx;
          const target = cues[matchedIdx];
          const srtFmt = (t) => {
            const s = Math.max(0, Number(t) || 0);
            const hh = String(Math.floor(s / 3600)).padStart(2, '0');
            const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
            const ss = (s % 60).toFixed(3).padStart(6, '0').replace('.', ',');
            return `${hh}:${mm}:${ss}`;
          };
          clearTimeout(syncInputDebounceTimer);
          syncInputDebounceTimer = setTimeout(() => {
            if (!window.__isTranscribing) {
              setGradioValue('cue-edit-idx', matchedIdx + 1, true);
              setGradioValue('cue-edit-start', srtFmt(target.start), true);
              setGradioValue('cue-edit-end', srtFmt(target.end), true);
              setGradioValue('cue-edit-text', target.text, true);
            }
          }, 250);
        }
      }

      // ① 字幕永远优先更新：与缩放视窗、光标位置、是否拖动进度条无关，
      //    避免播放头一旦跑出可视范围就「卡住不动」。
      updateCaption(cur);

      // ② 播放时自动跟随播放头（整页平移，不做连续滚动，避免干扰框选）
      if (duration && !video.paused && !video.ended && ensurePlayheadVisible(cur)) {
        drawRuler();
        drawWave();
      }

      // ③ 播放头时间游标
      if (!duration || cur < viewStart || cur > viewStart + viewSpan) {
        playheadLine.style.display = 'none';
        return;
      }

      const rect = waveCanvas.getBoundingClientRect();
      const x = ((cur - viewStart) / viewSpan) * rect.width;

      playheadLine.style.display = 'block';
      playheadLine.style.left = `${x}px`;
    };

    const renderAll = () => {
      drawRuler();
      drawWave();
      updatePlayhead(false);
    };

    let animId = null;
    const loop = () => {
      if (!video.paused && !video.ended) {
        updatePlayhead(true);
        animId = requestAnimationFrame(loop);
      }
    };

    const togglePlay = () => {
      if (video.paused || video.ended) {
        video.play();
      } else {
        video.pause();
      }
    };

    video.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePlay();
    });

    if (playToggleBtn) {
      playToggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        togglePlay();
      });
    }

    const onPlayStateChanged = () => {
      const isPaused = video.paused || video.ended;
      if (playToggleBtn) {
        playToggleBtn.textContent = isPaused ? '▶' : '⏸';
      }
      if (stage) {
        if (isPaused) {
          stage.classList.remove('is-playing', 'is-inactive');
        } else {
          stage.classList.add('is-playing');
        }
      }
    };

    video.addEventListener('play', () => {
      onPlayStateChanged();
      if (!followUserLocked) setFollow(true);
      cancelAnimationFrame(animId);
      animId = requestAnimationFrame(loop);
    });
    video.addEventListener('pause', () => {
      onPlayStateChanged();
      cancelAnimationFrame(animId);
      updatePlayhead(true);
    });
    video.addEventListener('seeked', () => updatePlayhead(true));
    video.addEventListener('timeupdate', () => updatePlayhead(!video.paused));
    video.addEventListener('loadedmetadata', () => {
      if (video.duration && !duration) {
        duration = video.duration;
        viewSpan = duration;
        totalTimeText.textContent = format(duration);
        if (ctrlTotalTime) ctrlTotalTime.textContent = format(duration);
        if (scrubberSlider) scrubberSlider.max = String(duration);
        renderAll();
      }
    });

    const resetHideControlsTimer = () => {
      if (!stage) return;
      stage.classList.remove('is-inactive');
      clearTimeout(hideControlsTimer);
      if (!video.paused && !video.ended) {
        hideControlsTimer = setTimeout(() => {
          if (!isScrubbingSlider) {
            stage.classList.add('is-inactive');
          }
        }, 2500);
      }
    };
    if (stage) {
      stage.addEventListener('mousemove', resetHideControlsTimer);
      stage.addEventListener('mouseleave', () => {
        if (!video.paused && !video.ended && !isScrubbingSlider) {
          stage.classList.add('is-inactive');
        }
      });
    }

    if (stepPrevBtn) {
      stepPrevBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        safeSeekVideo(video.currentTime - (1 / 24.0));
        updatePlayhead(true);
      });
    }
    if (stepNextBtn) {
      stepNextBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        safeSeekVideo(video.currentTime + (1 / 24.0));
        updatePlayhead(true);
      });
    }

    if (volSlider && muteBtn) {
      volSlider.addEventListener('input', (e) => {
        e.stopPropagation();
        video.volume = Number(e.target.value);
        video.muted = (video.volume === 0);
        muteBtn.textContent = video.muted ? '🔇' : (video.volume < 0.5 ? '🔉' : '🔊');
      });

      muteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        video.muted = !video.muted;
        muteBtn.textContent = video.muted ? '🔇' : (video.volume < 0.5 ? '🔉' : '🔊');
        volSlider.value = video.muted ? '0' : String(video.volume || 1);
      });
    }

    if (fullscreenBtn) {
      fullscreenBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!document.fullscreenElement) {
          if (stage.requestFullscreen) stage.requestFullscreen();
          else if (video.requestFullscreen) video.requestFullscreen();
        } else {
          if (document.exitFullscreen) document.exitFullscreen();
        }
      });
    }

    if (scrubberSlider) {
      scrubberSlider.addEventListener('input', (e) => {
        isScrubbingSlider = true;
        const targetSec = Number(e.target.value);
        currentTimeText.textContent = format(targetSec);
        if (ctrlCurrentTime) ctrlCurrentTime.textContent = format(targetSec);
        updateCaption(targetSec);   // 拖动进度条时字幕实时预览
        if (scrubTip) {
          scrubTip.style.display = 'block';
          scrubTip.textContent = format(targetSec);
          const pct = (targetSec / (duration || 1)) * 100;
          scrubTip.style.left = `${pct}%`;
        }
      });

      const commitScrub = (e) => {
        if (!isScrubbingSlider) return;
        isScrubbingSlider = false;
        if (scrubTip) scrubTip.style.display = 'none';
        const targetSec = Number(scrubberSlider.value);
        safeSeekVideo(targetSec);
        updatePlayhead(true);
        resetHideControlsTimer();
      };
      scrubberSlider.addEventListener('change', commitScrub);
      scrubberSlider.addEventListener('pointerup', commitScrub);
      scrubberSlider.addEventListener('touchend', commitScrub);

      // 兜底：无论指针在哪里松开，都复位拖动状态，
      // 避免 isScrubbingSlider 卡在 true 导致进度条/时间读数不再跟随播放。
      window.addEventListener('pointerup', () => {
        if (!isScrubbingSlider) return;
        isScrubbingSlider = false;
        if (scrubTip) scrubTip.style.display = 'none';
        safeSeekVideo(Number(scrubberSlider.value));
        updatePlayhead(true);
      });
    }

    const xToTime = (clientX) => {
      const rect = waveCanvas.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
      return Math.max(0, Math.min(duration, viewStart + ratio * viewSpan));
    };

    let downScreenX = 0;
    let downScreenY = 0;

    const onPointerDown = (e) => {
      if (!duration) return;
      noteManualViewChange();
      downScreenX = e.clientX;
      downScreenY = e.clientY;
      dragAnchor = xToTime(e.clientX);
      selected = [dragAnchor, dragAnchor];
      isDragging = true;
      waveCanvas.setPointerCapture(e.pointerId);
      renderAll();
    };

    const onPointerMove = (e) => {
      if (!isDragging || dragAnchor === null) return;
      const curTime = xToTime(e.clientX);
      selected = [Math.min(dragAnchor, curTime), Math.max(dragAnchor, curTime)];

      const span = selected[1] - selected[0];
      const moveDistance = Math.hypot(e.clientX - downScreenX, e.clientY - downScreenY);
      if (moveDistance > 5 && span > 0.05) {
        selectionBar.style.display = 'flex';
        selectionInfo.textContent = `已选: ${format(selected[0])} → ${format(selected[1])} (${span.toFixed(2)}s)`;
      }
      renderAll();
    };

    const onPointerUp = (e) => {
      if (!isDragging) return;
      isDragging = false;
      dragAnchor = null;
      try { waveCanvas.releasePointerCapture(e.pointerId); } catch (_) {}

      const moveDistance = Math.hypot(e.clientX - downScreenX, e.clientY - downScreenY);
      const span = selected ? (selected[1] - selected[0]) : 0;

      if (moveDistance > 5 && span > 0.05) {
        selectionBar.style.display = 'flex';
        selectionInfo.textContent = `已选: ${format(selected[0])} → ${format(selected[1])} (${span.toFixed(2)}s)`;
        safeSeekVideo(selected[0]);
        updatePlayhead(true);
      } else {
        selected = null;
        selectionBar.style.display = 'none';
        const targetTime = xToTime(e.clientX);
        safeSeekVideo(targetTime);
        updatePlayhead(true);
      }
      renderAll();
    };

    waveCanvas.addEventListener('pointerdown', onPointerDown);
    waveCanvas.addEventListener('pointermove', onPointerMove);
    waveCanvas.addEventListener('pointerup', onPointerUp);

    waveCanvas.addEventListener('dblclick', (e) => {
      if (!duration) return;
      const targetTime = xToTime(e.clientX);
      safeSeekVideo(targetTime);
      video.play();
    });

    rulerCanvas.addEventListener('click', (e) => {
      if (!duration) return;
      const targetTime = xToTime(e.clientX);
      safeSeekVideo(targetTime);
      updatePlayhead(true);
    });

    const onWheelZoomPan = (e) => {
      if (!duration) return;
      e.preventDefault();
      noteManualViewChange();

      const isMacPinch = e.ctrlKey || e.metaKey;
      const isHorizontal = Math.abs(e.deltaX) > Math.abs(e.deltaY) && !isMacPinch;

      if (isHorizontal) {
        const panDelta = (e.deltaX / Math.max(1, waveCanvas.clientWidth)) * viewSpan;
        viewStart += panDelta;
        clampView();
        renderAll();
        return;
      }

      const mouseTime = xToTime(e.clientX);
      const zoomFactor = isMacPinch ? Math.exp(e.deltaY * 0.015) : Math.exp(e.deltaY * 0.003);
      const nextSpan = Math.max(Math.min(duration, 0.4), Math.min(duration, viewSpan * zoomFactor));

      const timeRatio = (mouseTime - viewStart) / Math.max(0.001, viewSpan);
      viewStart = mouseTime - timeRatio * nextSpan;
      viewSpan = nextSpan;

      clampView();
      renderAll();
    };

    waveCanvas.addEventListener('wheel', onWheelZoomPan, { passive: false });
    rulerCanvas.addEventListener('wheel', onWheelZoomPan, { passive: false });

    zoomInBtn.addEventListener('click', () => {
      noteManualViewChange();
      const centerTime = viewStart + viewSpan / 2;
      viewSpan = Math.max(0.4, viewSpan * 0.65);
      viewStart = centerTime - viewSpan / 2;
      clampView();
      renderAll();
    });

    zoomOutBtn.addEventListener('click', () => {
      noteManualViewChange();
      const centerTime = viewStart + viewSpan / 2;
      viewSpan = Math.min(duration, viewSpan * 1.5);
      viewStart = centerTime - viewSpan / 2;
      clampView();
      renderAll();
    });

    zoomFitBtn.addEventListener('click', () => {
      viewStart = 0;
      viewSpan = duration || 1;
      clampView();
      renderAll();
    });

    centerPlayheadBtn.addEventListener('click', () => {
      const maxZoom = 50;
      viewSpan = (duration || 1) / maxZoom;
      viewStart = video.currentTime - viewSpan / 2;
      clampView();
      renderAll();
    });

    const syncFollowBtn = () => {
      if (!followToggleBtn) return;
      followToggleBtn.classList.toggle('is-on', followPlayhead);
      followToggleBtn.textContent = followPlayhead ? '🧲 跟随' : '🧲 不跟随';
      followToggleBtn.title = followPlayhead
        ? '播放时自动跟随播放头（点击关闭）'
        : '已关闭自动跟随（点击开启）';
    };

    const setFollow = (on) => {
      followPlayhead = !!on;
      syncFollowBtn();
    };

    if (followToggleBtn) {
      followToggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const next = !followPlayhead;
        followUserLocked = !next;
        setFollow(next);
      });
      syncFollowBtn();
    }

    // 播放中用户主动拖动/缩放波形时，暂停自动跟随，避免画面被强行拽走
    const noteManualViewChange = () => {
      if (followPlayhead && !video.paused && !video.ended) setFollow(false);
    };

    zoomSlider.addEventListener('input', () => {
      noteManualViewChange();
      const zoomLevel = Number(zoomSlider.value);
      const nextSpan = duration / zoomLevel;
      const centerTime = viewStart + viewSpan / 2;
      viewSpan = nextSpan;
      viewStart = centerTime - viewSpan / 2;
      clampView();
      renderAll();
    });

    playSelBtn.addEventListener('click', () => {
      if (!selected) return;
      if (isPlayingSelection) {
        video.pause();
        isPlayingSelection = false;
        playSelBtn.textContent = '▶ 试听';
      } else {
        safeSeekVideo(selected[0]);
        video.play();
        isPlayingSelection = true;
        playSelBtn.textContent = '⏸ 停止';
      }
    });

    clearSelBtn.addEventListener('click', () => {
      selected = null;
      selectionBar.style.display = 'none';
      renderAll();
    });

    syncBtn.addEventListener('click', () => {
      if (!selected) return;
      const startStr = format(selected[0]);
      const endStr = format(selected[1]);

      setGradioValue('slice-start', startStr);
      setGradioValue('slice-end', endStr);
      setGradioValue('hidden-sync-start', startStr);
      setGradioValue('hidden-sync-end', endStr);

      const startElem = document.getElementById('slice-start');
      if (startElem) {
        const details = startElem.closest('details');
        if (details) { details.open = true; }
      }

      const bridgeBtn = document.getElementById('btn-hidden-bridge-sync');
      if (bridgeBtn) { bridgeBtn.click(); }

      syncBtn.textContent = '✅ 已同步！';
      setTimeout(() => {
        syncBtn.textContent = '⏱ 同步时间到顶部';
      }, 1500);
    });

    transcribeSelBtn.addEventListener('click', () => {
      if (!selected) return;
      const startStr = format(selected[0]);
      const endStr = format(selected[1]);

      setGradioValue('hidden-sync-start', startStr);
      setGradioValue('hidden-sync-end', endStr);

      transcribeSelBtn.textContent = '⏳ 正在转写…';
      transcribeSelBtn.disabled = true;

      const patchBtn = document.getElementById('btn-hidden-bridge-transcribe');
      if (patchBtn) {
        patchBtn.click();
      }
    });

    const isEditingText = () => {
      const active = document.activeElement;
      if (!active) return false;
      const tag = active.tagName.toLowerCase();
      if (tag === 'input' || tag === 'textarea') return true;
      if (active.isContentEditable) return true;
      return false;
    };

    const handleKeyDown = (e) => {
      if (isEditingText()) return;

      if (e.code === 'Space' || e.key === ' ' || e.keyCode === 32) {
        e.preventDefault();
        togglePlay();
        return;
      }

      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        const frameRate = 24.0;
        const frameCount = e.shiftKey ? 5 : 1;
        const stepSeconds = frameCount / frameRate;

        if (!video.paused) {
          video.pause();
        }

        if (e.key === 'ArrowLeft') {
          safeSeekVideo(Math.max(0, video.currentTime - stepSeconds));
        } else {
          const maxTime = duration || video.duration || Infinity;
          safeSeekVideo(Math.min(maxTime, video.currentTime + stepSeconds));
        }

        updatePlayhead(true);

        if (duration && (video.currentTime < viewStart || video.currentTime > viewStart + viewSpan)) {
          viewStart = Math.max(0, Math.min(duration - viewSpan, video.currentTime - viewSpan / 2));
          renderAll();
        }
        return;
      }

      const isZKey = e.key === 'z' || e.key === 'Z';
      const isYKey = e.key === 'y' || e.key === 'Y';
      const isMod = e.metaKey || e.ctrlKey;

      if (isMod && (isZKey || isYKey)) {
        e.preventDefault();
        const isRedo = (isZKey && e.shiftKey) || (isYKey && !e.shiftKey);
        if (isRedo) {
          const redoBtn = document.querySelector('#btn-reviewer-redo button') || document.getElementById('btn-reviewer-redo');
          if (redoBtn) {
            redoBtn.click();
          }
        } else {
          const undoBtn = document.querySelector('#btn-reviewer-undo button') || document.getElementById('btn-reviewer-undo');
          if (undoBtn) {
            undoBtn.click();
          }
        }
        return;
      }
    };

    if (window.__reviewerKeyHandler) {
      window.removeEventListener('keydown', window.__reviewerKeyHandler);
    }
    window.__reviewerKeyHandler = handleKeyDown;
    window.addEventListener('keydown', window.__reviewerKeyHandler);

    window.onbeforeunload = (e) => {
      if (cues && cues.length > 0) {
        e.preventDefault();
        e.returnValue = '';
        return '';
      }
    };

    new ResizeObserver(renderAll).observe(canvasWrap);
    clampView();
    window.__reviewerInstance = {
      updateCues: (newCues) => {
        cues.length = 0;
        cues.push(...newCues);
        lastSyncedCueIndex = -1;
        rebuildCaptionIndex();
        renderAll();
      },
      seekAndCenter: (targetTime) => {
        safeSeekVideo(targetTime);
        if (duration && (targetTime < viewStart || targetTime > viewStart + viewSpan)) {
          viewStart = Math.max(0, Math.min(duration - viewSpan, targetTime - viewSpan / 2));
        }
        renderAll();
      }
    };
    renderAll();
  } catch (err) {
    console.error('❌ [Reviewer] 渲染异常:', err);
  }
}
"""

CSS_CUSTOM = """
footer {visibility: hidden !important; display: none !important;}
.show-api {display: none !important;}
a[href*="/api"] {display: none !important;}

.gradio-container {
    max-width: 100% !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 8px 16px !important;
    box-sizing: border-box !important;
    font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
        "Noto Sans SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
    -webkit-font-smoothing: antialiased !important;
}

.bridge-hidden,
#bridge-hidden-row {
    position: fixed !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    z-index: -9999 !important;
}

/* ============ 顶部标题栏 + 运行环境胶囊 ============ */
.app-header {
    align-items: center !important;
    gap: 10px !important;
    margin-bottom: 10px !important;
    flex-wrap: wrap !important;
}
.app-title-col {
    padding: 0 !important;
    min-width: 0 !important;
}
.app-title-col .prose,
.app-title-col .markdown {
    padding: 0 !important;
    margin: 0 !important;
}
.app-title-col h3 {
    margin: 0 !important;
    padding: 0 !important;
    font-size: 20px !important;
    line-height: 1.3 !important;
    font-weight: 700 !important;
    letter-spacing: 0.01em !important;
    color: #0f172a !important;
    white-space: nowrap !important;
}
.app-status-col {
    padding: 0 !important;
    min-width: 0 !important;
    justify-content: center !important;
}
.device-header {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    margin: 0 !important;
    box-shadow: none !important;
    min-height: 0 !important;
}
.device-header .html-container,
.device-header .prose {
    padding: 0 !important;
    margin: 0 !important;
}
.device-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
    justify-content: flex-end;
    align-items: center;
}
.device-chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    height: 30px;
    padding: 0 12px;
    border-radius: 999px;
    background: #f8fafc;
    border: 1px solid #e6ebf3;
    font-size: 12px;
    line-height: 1;
    white-space: nowrap;
    transition: border-color 0.15s ease, background 0.15s ease;
}
.device-chip:hover {
    background: #f4f7fd;
    border-color: #d9e2f2;
}
.device-chip .chip-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #22c55e;
    box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.14);
    flex: none;
}
.device-chip.is-pending .chip-dot {
    background: #f59e0b;
    box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.16);
}
.device-chip .chip-label {
    color: #64748b;
    font-weight: 500;
    letter-spacing: 0.01em;
}
.device-chip .chip-value {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 700;
    font-size: 11.5px;
    color: #1e293b;
    letter-spacing: 0.02em;
}
.device-chip.is-accent {
    background: #eef2ff;
    border-color: #dde4ff;
}
.device-chip.is-accent .chip-value {
    color: #4338ca;
}

/* ============ 参数配置面板（导入 / 预设 / 执行） ============ */
.setup-panel {
    padding: 16px 18px 14px 18px !important;
}
.setup-row {
    gap: 0 !important;
    align-items: flex-start !important;
}
.setup-col {
    padding: 0 18px !important;
    min-width: 0 !important;
}
.setup-col:first-child {
    padding-left: 0 !important;
}
.setup-col:last-child {
    padding-right: 0 !important;
}
.setup-col + .setup-col {
    border-left: 1px solid #eef2f8 !important;
}
.setup-head {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: #334155;
    padding-bottom: 8px;
    margin-bottom: 10px;
    border-bottom: 1px solid #eef2f8;
}
.setup-head .step {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #eef2ff;
    color: #4f46e5;
    font-size: 10px;
    font-weight: 700;
    font-family: ui-monospace, monospace;
}

/* ============ 媒体上传区（空态紧凑化） ============ */
.media-upload {
    border: 1.5px dashed #c7d2fe !important;
    border-radius: 12px !important;
    background: #f9faff !important;
    box-shadow: none !important;
    flex: 0 0 auto !important;
    align-self: flex-start !important;
    height: auto !important;
    min-height: 0 !important;
    width: 100% !important;
    transition: border-color 0.18s ease, background 0.18s ease !important;
}
.media-upload:hover {
    border-color: #818cf8 !important;
    background: #f4f7ff !important;
}
.media-upload .block,
.media-upload > div {
    background: transparent !important;
}
.media-upload button[aria-dropeffect] {
    height: 96px !important;
    min-height: 96px !important;
    max-height: 96px !important;
    padding: 10px !important;
    border: none !important;
    background: transparent !important;
}
.media-upload .wrap {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 0 !important;
    font-size: 0 !important;
    line-height: 1.45 !important;
    color: #4338ca !important;
}
.media-upload .wrap .icon-wrap {
    width: 26px !important;
    height: 26px !important;
    color: #6366f1 !important;
    opacity: 0.85 !important;
    margin-bottom: 6px !important;
}
.media-upload .wrap .or {
    display: none !important;
}
.media-upload .wrap::after {
    content: "点击选择 或 拖拽音视频到此处";
    font-size: 13px !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em;
}.upload-hint {
    margin: 8px 2px 0 2px;
    font-size: 11px;
    line-height: 1.6;
    color: #94a3b8;
}
.upload-hint b {
    color: #64748b;
    font-weight: 600;
}
/* 已导入文件后：上传区收缩为一条「更换文件」操作条 */
.media-upload:has(.file-preview-holder) button[aria-dropeffect] {
    height: 44px !important;
    min-height: 44px !important;
    max-height: 44px !important;
    padding: 0 12px !important;
}
.media-upload:has(.file-preview-holder) .wrap {
    flex-direction: row !important;
    gap: 8px !important;
}
.media-upload:has(.file-preview-holder) .wrap .icon-wrap {
    width: 15px !important;
    height: 15px !important;
    margin-bottom: 0 !important;
}
.media-upload:has(.file-preview-holder) .wrap::after {
    content: "点击更换文件";
    font-size: 12px !important;
    color: #6366f1 !important;
}
.media-upload .file-preview-holder {
    padding: 0 !important;
}
.media-upload .file-preview {
    margin: 0 !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}
.media-upload .file-preview td {
    font-size: 12px !important;
    padding: 6px 8px !important;
    border-color: #eef2f8 !important;
}
.media-upload .file-preview .filename {
    font-weight: 600 !important;
    color: #1e293b !important;
}

/* ============ 预设区按钮 ============ */
.setup-col .wrap-inner input,
.setup-col .secondary-wrap input {
    font-size: 12.5px !important;
    text-overflow: ellipsis !important;
}
.preset-btn-row {
    gap: 6px !important;
}
.preset-btn-row button {
    min-width: 0 !important;
    flex: 1 1 0 !important;
    min-height: 32px !important;
    height: 32px !important;
    padding: 0 8px !important;
    font-size: 12px !important;
    line-height: 1 !important;
    border-radius: 8px !important;
}

/* ============ 折叠面板（时间片段 / VAD 参数） ============ */
.clean-accordion.block {
    margin-top: 10px !important;
    border: 1px solid #e6ebf3 !important;
    border-radius: 12px !important;
    background: #ffffff !important;
    box-shadow: none !important;
    padding: 0 !important;
    overflow: hidden !important;
    transition: border-color 0.16s ease, box-shadow 0.16s ease !important;
}
.clean-accordion.block:hover {
    border-color: #d5ddf7 !important;
}
.clean-accordion > button.label-wrap {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 10px !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 11px 14px !important;
    background: #fbfcfe !important;
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em !important;
    color: #1e293b !important;
    text-align: left !important;
    cursor: pointer !important;
    transition: background 0.16s ease, color 0.16s ease !important;
}
.clean-accordion > button.label-wrap:hover {
    background: #f3f6ff !important;
    color: #3730a3 !important;
}
.clean-accordion > button.label-wrap > span:first-child {
    flex: 1 1 auto !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    line-height: 1.4 !important;
    color: inherit !important;
}
.clean-accordion > button.label-wrap .icon {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 20px !important;
    height: 20px !important;
    flex: none !important;
    border-radius: 50% !important;
    background: #eef2ff !important;
    color: #6366f1 !important;
    font-size: 0 !important;
    transform: none !important;
    transition: background 0.16s ease !important;
}
.clean-accordion > button.label-wrap .icon::before {
    content: "";
    display: block;
    width: 6px;
    height: 6px;
    margin-top: -3px;
    border-right: 1.8px solid currentColor;
    border-bottom: 1.8px solid currentColor;
    transform: rotate(45deg);
    transition: transform 0.2s ease, margin 0.2s ease;
}
.clean-accordion:has([data-testid="accordion-content"]:not([style*="display: none"])) > button.label-wrap .icon {
    background: #e0e7ff !important;
}
.clean-accordion:has([data-testid="accordion-content"]:not([style*="display: none"])) > button.label-wrap .icon::before {
    transform: rotate(-135deg);
    margin-top: 2px;
}
.clean-accordion [data-testid="accordion-content"] {
    padding: 12px 14px 14px 14px !important;
    border-top: 1px solid #f1f5f9 !important;
}
.acc-hint {
    display: block;
    font-size: 11.5px;
    line-height: 1.75;
    color: #64748b;
    background: #f8fafc;
    border: 1px solid #eef2f8;
    border-radius: 8px;
    padding: 7px 10px;
    margin-bottom: 10px;
}
.acc-hint b {
    color: #4338ca;
    font-weight: 600;
}
.clean-accordion .form,
.clean-accordion fieldset {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
}

/* ============ 当前生效参数条 ============ */
.active-params-banner {
    padding: 0 !important;
    margin: 0 !important;
    background: transparent !important;
    border: none !important;
    min-height: 0 !important;
}
.params-strip {
    border: 1px solid #e6ebf3;
    border-radius: 10px;
    background: #fbfcff;
    padding: 10px 12px;
}
.params-strip-head {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    font-size: 12px;
    color: #475569;
    margin-bottom: 8px;
}
.params-strip-head .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #6366f1;
    flex: none;
}
.params-strip-head b {
    color: #1e293b;
    font-size: 12.5px;
    font-weight: 700;
}
.params-strip-head .engine-tag {
    font-size: 11px;
    font-weight: 600;
    color: #4338ca;
    background: #eef2ff;
    border: 1px solid #dfe5ff;
    border-radius: 999px;
    padding: 2px 9px;
}
.params-strip-head .ts {
    margin-left: auto;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    color: #94a3b8;
}
.params-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
.params-chips .p-chip {
    display: inline-flex;
    align-items: baseline;
    gap: 5px;
    padding: 3px 9px;
    border-radius: 7px;
    background: #ffffff;
    border: 1px solid #eaeff8;
    font-size: 11.5px;
    line-height: 1.5;
}
.params-chips .p-chip i {
    font-style: normal;
    color: #64748b;
}
.params-chips .p-chip b {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-weight: 700;
    color: #4338ca;
}
.params-chips .p-chip.is-flag b {
    color: #0f766e;
}

.preset-action-col {
    display: flex !important;
    flex-direction: column !important;
    justify-content: flex-end !important;
    gap: 4px !important;
    padding: 0 !important;
    margin: 0 !important;
}
.preset-action-col button {
    height: 34px !important;
    min-height: 34px !important;
    padding: 2px 6px !important;
    font-size: 12px !important;
    line-height: 1 !important;
    margin: 0 !important;
}

button.btn-primary-action {
    background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important;
    border: none !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.32) !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
button.btn-primary-action:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 18px rgba(79, 70, 229, 0.45) !important;
}

button:hover:is([id*="delete"], [id*="clear"]) {
    border-color: #f87171 !important;
    color: #fca5a5 !important;
}

div[data-testid="radio-group"] label,
.gr-radio label,
fieldset label:has(input[type="radio"]) {
    transition: all 0.15s ease !important;
    border-radius: 8px !important;
    font-size: 13px !important;
}

div[data-testid="radio-group"] label:has(input:checked),
div[data-testid="radio-group"] label.selected,
.gr-radio label.selected,
.gr-radio label:has(input[type="radio"]:checked),
fieldset label:has(input[type="radio"]:checked) {
    background: #e0e7ff !important;
    border-color: #6366f1 !important;
    box-shadow: 0 1px 4px rgba(99, 102, 241, 0.18) !important;
}

div[data-testid="radio-group"] label:has(input:checked) *,
div[data-testid="radio-group"] label.selected *,
.gr-radio label.selected *,
.gr-radio label:has(input[type="radio"]:checked) *,
fieldset label:has(input[type="radio"]:checked) * {
    color: #1e1b4b !important;
    font-weight: 600 !important;
}

.reviewer-stage {
    position: relative;
    background: #000;
    border-radius: 10px;
    overflow: hidden;
    height: 480px;
    display: flex;
    justify-content: center;
    align-items: center;
    box-shadow: inset 0 0 40px rgba(0, 0, 0, 0.85);
    cursor: pointer;
}
.reviewer-stage:hover .reviewer-custom-controls {
    opacity: 1;
    transform: translateY(0);
}
.rw-center-play-indicator {
    position: absolute;
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.65);
    backdrop-filter: blur(4px);
    border: 2px solid rgba(255, 255, 255, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
    z-index: 15;
    animation: rwPulse 0.3s ease-out;
}
.rw-center-play-icon {
    color: #ffffff;
    font-size: 24px;
    margin-left: 3px;
}
@keyframes rwPulse {
    from { transform: scale(0.8); opacity: 0; }
    to { transform: scale(1); opacity: 1; }
}

.reviewer-custom-controls {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(to top, rgba(0, 0, 0, 0.9) 0%, rgba(0, 0, 0, 0.4) 60%, transparent 100%);
    padding: 24px 16px 10px 16px;
    z-index: 20;
    opacity: 1;
    transform: translateY(0);
    transition: opacity 0.25s ease, transform 0.25s ease;
    cursor: default;
}
.reviewer-stage.is-playing.is-inactive .reviewer-custom-controls {
    opacity: 0;
    transform: translateY(8px);
    pointer-events: none;
}
.rw-scrub-track-wrap {
    position: relative;
    width: 100%;
    height: 12px;
    display: flex;
    align-items: center;
    cursor: pointer;
}
.rw-scrubber-slider {
    width: 100%;
    height: 4px;
    border-radius: 2px;
    background: rgba(255, 255, 255, 0.25);
    accent-color: #6366f1;
    cursor: pointer;
    transition: height 0.15s ease;
}
.rw-scrub-track-wrap:hover .rw-scrubber-slider {
    height: 6px;
    background: rgba(255, 255, 255, 0.35);
}
.rw-scrub-hover-tip {
    position: absolute;
    top: -26px;
    background: rgba(15, 23, 42, 0.95);
    border: 1px solid #6366f1;
    color: #e0e7ff;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 4px;
    pointer-events: none;
    transform: translateX(-50%);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
    white-space: nowrap;
}

.rw-controls-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 6px;
    gap: 12px;
}
.rw-ctrl-left, .rw-ctrl-right {
    display: flex;
    align-items: center;
    gap: 8px;
}
.rw-ctrl-btn {
    background: transparent;
    border: none;
    color: #ffffff;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s ease, transform 0.1s ease;
}
.rw-ctrl-btn:hover {
    background: rgba(255, 255, 255, 0.15);
}
.rw-btn-main-play {
    font-size: 16px;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
}
.rw-ctrl-time-display {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    font-weight: 600;
    margin-left: 6px;
}
.rw-time-cur { color: #fbbf24; }
.rw-time-sep { color: #64748b; margin: 0 4px; }
.rw-time-dur { color: #94a3b8; }

.rw-vol-slider {
    width: 55px;
    height: 4px;
    accent-color: #6366f1;
    cursor: pointer;
}

.proxy-status-box {
    margin: 4px 0 6px 0 !important;
    padding: 8px 12px !important;
    border-radius: 8px !important;
    background: rgba(99, 102, 241, 0.06) !important;
    border: 1px solid rgba(99, 102, 241, 0.2) !important;
    font-size: 12px !important;
    min-height: 38px !important;
    /* 纵向排列：Gradio 原生进度追踪器一旦被渲染进这个容器，只会在卡片上方另起一块，
       绝不会把卡片横向挤压变形（历史上 display:flex + align-items:center 就干过这事）。 */
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
}

/* 480p 代理压制进度卡片：全部使用 div/b/em，不碰 p/span，
   以免被下方 .proxy-status-box span{color:...!important} 覆盖掉配色。 */
.proxy-progress-card { display: block !important; width: 100% !important; }
.ppc-head,
.ppc-foot {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    gap: 8px !important;
}
.ppc-head { margin-bottom: 5px !important; }
.ppc-foot { margin-top: 5px !important; }
.ppc-stage {
    font-size: 12px !important;
    font-weight: 600 !important;
    color: #1e1b4b !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}
.ppc-right {
    display: flex !important;
    align-items: baseline !important;
    gap: 4px !important;
    white-space: nowrap !important;
}
.ppc-pct {
    font-family: ui-monospace, SFMono-Regular, monospace !important;
    font-size: 12px !important;
    font-weight: 700 !important;
    color: #4338ca !important;
}
.ppc-speed {
    font-family: ui-monospace, SFMono-Regular, monospace !important;
    font-size: 10px !important;
    font-style: normal !important;
    color: #64748b !important;
}
.ppc-track {
    position: relative !important;
    width: 100% !important;
    height: 6px !important;
    background: rgba(99, 102, 241, 0.15) !important;
    border-radius: 3px !important;
    overflow: hidden !important;
}
.ppc-fill {
    height: 100% !important;
    border-radius: 3px !important;
    background: linear-gradient(90deg, #6366f1 0%, #38bdf8 100%) !important;
    transition: width 0.25s ease !important;
}
.ppc-time,
.ppc-note {
    font-family: ui-monospace, SFMono-Regular, monospace !important;
    font-size: 11px !important;
    color: #64748b !important;
}
@keyframes ppc-indet-slide {
    0% { transform: translateX(-110%); }
    100% { transform: translateX(340%); }
}
.ppc-indet {
    position: absolute !important;
    top: 0 !important;
    left: 0 !important;
    width: 30% !important;
    height: 100% !important;
    border-radius: 3px !important;
    background: linear-gradient(90deg, #6366f1 0%, #38bdf8 100%) !important;
    animation: ppc-indet-slide 1.1s ease-in-out infinite !important;
}

/* 监看画面工具栏：说明 + 导入 / 压制 / 历史代理 / 关闭 / 恢复 */
.monitor-toolbar {
    align-items: stretch !important;
    gap: 8px !important;
    margin-bottom: 2px !important;
}
.monitor-toolbar > * { min-width: 0 !important; }
.monitor-toolbar button {
    height: 100% !important;
    min-height: 40px !important;
    white-space: nowrap !important;
    font-size: 12px !important;
}
.monitor-toolbar .block,
.monitor-toolbar .form { min-width: 0 !important; }
#monitor-proxy-pick label span { font-size: 11px !important; }
#btn-monitor-close,
#btn-monitor-close button { color: #b91c1c !important; }
#btn-monitor-close:hover,
#btn-monitor-close button:hover { background: rgba(185, 28, 28, 0.08) !important; }

/* 监看画面空态（已关闭 / 片源失效 / 尚未导入） */
.reviewer-empty {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 6px !important;
    min-height: 240px !important;
    padding: 28px 20px !important;
    border: 1px dashed rgba(99, 102, 241, 0.35) !important;
    border-radius: 12px !important;
    background: rgba(99, 102, 241, 0.04) !important;
    text-align: center !important;
}
.reviewer-empty .rw-empty-icon { font-size: 30px; line-height: 1.1; }
.reviewer-empty .rw-empty-title {
    font-size: 15px !important;
    font-weight: 700 !important;
    color: #1e1b4b !important;
}
.reviewer-empty .rw-empty-desc {
    font-size: 12px !important;
    line-height: 1.75 !important;
    color: #64748b !important;
}
.reviewer-empty .rw-empty-desc code {
    font-size: 11px !important;
    background: rgba(15, 23, 42, 0.06) !important;
    padding: 1px 5px !important;
    border-radius: 4px !important;
    word-break: break-all !important;
}
.proxy-status-box p,
.proxy-status-box span {
    margin: 0 !important;
    color: #334155 !important;
    font-size: 12px !important;
    line-height: 1.4 !important;
}
.proxy-status-box strong,
.proxy-status-box code {
    color: #4338ca !important;
    font-weight: 700 !important;
}
.reviewer-video { width: 100%; height: 100%; object-fit: contain; background: #000; }
.reviewer-caption {
    position: absolute;
    left: 5%;
    right: 5%;
    bottom: 90px;
    text-align: center;
    color: #ffffff;
    font-size: clamp(16px, 1.8vw, 24px);
    font-weight: 700;
    line-height: 1.4;
    text-shadow: 0 2px 4px #000, 0 0 10px rgba(0, 0, 0, 0.9);
    pointer-events: none;
    background: rgba(0, 0, 0, 0.65);
    padding: 6px 14px;
    border-radius: 8px;
    backdrop-filter: blur(4px);
    display: none;
    z-index: 10;
    /* 中日双语 / 多语字幕：同一时间区间聚合为多行显示 */
    white-space: pre-line;
    word-break: break-word;
    max-height: 55%;
    overflow: hidden;
    transition: bottom 0.25s ease;
}
.reviewer-stage.is-playing.is-inactive .reviewer-caption { bottom: 34px; }

.reviewer-wave-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 10px;
    padding: 4px 2px;
    gap: 8px;
    flex-wrap: wrap;
}
.reviewer-clock { font-family: ui-monospace, monospace; font-size: 13px; font-weight: 600; }
.reviewer-playhead-time { color: #fbbf24; }
.reviewer-divider { color: #475569; margin: 0 4px; }
.reviewer-total-time { color: #94a3b8; }

.reviewer-selection-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    background: rgba(99, 102, 241, 0.18);
    border: 1px solid rgba(99, 102, 241, 0.4);
    padding: 3px 10px;
    border-radius: 16px;
}
.rw-sel-info { font-family: ui-monospace, monospace; font-size: 12px; color: #c7d2fe; font-weight: 600; }
.rw-btn { border: none; border-radius: 12px; padding: 2px 8px; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.15s ease; }
.rw-btn-play-sel { background: #0284c7; color: #fff; }
.rw-btn-transcribe-sel { 
    background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important; 
    color: #fff !important; 
    box-shadow: 0 2px 8px rgba(79, 70, 229, 0.35) !important;
}
.rw-btn-transcribe-sel:hover {
    transform: translateY(-1px);
    box-shadow: 0 3px 10px rgba(79, 70, 229, 0.5) !important;
}
.rw-btn-sync { background: #334155; color: #cbd5e1; }
.rw-btn-clear { background: transparent; color: #94a3b8; }

.reviewer-zoom-controls { display: flex; align-items: center; gap: 4px; }
.rw-tool-btn { background: #1e293b; border: 1px solid #334155; color: #cbd5e1; border-radius: 6px; padding: 3px 8px; font-size: 11px; cursor: pointer; }
.rw-tool-btn.is-on {
    background: rgba(99, 102, 241, 0.28);
    border-color: rgba(129, 140, 248, 0.85);
    color: #e0e7ff;
    font-weight: 700;
}
.rw-zoom-slider { width: 75px; cursor: pointer; accent-color: #6366f1; }
.reviewer-zoom-level { font-family: ui-monospace, monospace; font-size: 11px; color: #94a3b8; min-width: 34px; }

.reviewer-canvas-wrap {
    position: relative !important;
    border: 1px solid #1e293b !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    background: #090d16 !important;
    margin-top: 6px !important;
    width: 100% !important;
}
.reviewer-ruler-canvas { width: 100% !important; height: 24px !important; display: block !important; cursor: pointer !important; }
.reviewer-wave-canvas { width: 100% !important; height: 110px !important; display: block !important; cursor: crosshair !important; touch-action: none !important; }

.reviewer-playhead-line {
    position: absolute !important;
    top: 0 !important;
    bottom: 0 !important;
    width: 2px !important;
    background: #fbbf24 !important;
    box-shadow: 0 0 8px rgba(251, 191, 36, 0.85) !important;
    pointer-events: none !important;
    z-index: 10 !important;
    transform: translateX(-50%) !important;
}
.rw-playhead-flag { position: absolute !important; top: 0 !important; left: 50% !important; transform: translateX(-50%) !important; color: #fbbf24 !important; font-size: 10px; line-height: 1 !important; }
.reviewer-wave-hint { margin-top: 6px !important; font-size: 11px !important; color: #64748b !important; display: flex !important; flex-direction: column !important; gap: 2px !important; line-height: 1.4 !important; }

.cue-table table {
    width: 100% !important;
    table-layout: auto !important;
}
.cue-table table tr > *:nth-child(1) { width: 60px !important; min-width: 60px !important; text-align: center; }
.cue-table table tr > *:nth-child(2) { width: 120px !important; min-width: 120px !important; font-family: ui-monospace, monospace; }
.cue-table table tr > *:nth-child(3) { width: 120px !important; min-width: 120px !important; font-family: ui-monospace, monospace; }
.cue-table table tr > *:nth-child(4) { width: 80px !important; min-width: 80px !important; text-align: center; }
.cue-table table tr > *:nth-child(5) { width: auto !important; min-width: 350px !important; word-break: break-word !important; }
.reviewed-download-box { margin-top: 6px !important; border: 1px solid rgba(79, 70, 229, 0.4) !important; border-radius: 8px !important; background: rgba(79, 70, 229, 0.08) !important; }

.workbench-panel {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 12px !important;
    padding: 14px !important;
    box-shadow: 0 1px 4px 0 rgba(0, 0, 0, 0.04) !important;
    transition: all 0.2s ease !important;
}
.editor-header-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 8px;
    border-bottom: 1px solid #e2e8f0 !important;
    margin-bottom: 8px;
}
.workbench-panel h4,
.workbench-panel h3,
.workbench-panel strong {
    color: #0f172a !important;
}
.workbench-panel .markdown p,
.workbench-panel span:not(.rw-sel-info) {
    color: #334155 !important;
    font-size: 13px !important;
}
.workbench-panel button:not(.btn-primary-action) {
    background: #f1f5f9 !important;
    border: 1px solid #cbd5e1 !important;
    color: #1e293b !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    transition: all 0.15s ease !important;
}
.workbench-panel button:not(.btn-primary-action):hover {
    background: #e2e8f0 !important;
    border-color: #94a3b8 !important;
    color: #0f172a !important;
}
.cue-table {
    border: 1px solid #e2e8f0 !important;
    border-radius: 8px !important;
    background: #ffffff !important;
    overflow: hidden !important;
}
.cue-table th, .cue-table .thead th {
    background: #f8fafc !important;
    color: #475569 !important;
    font-weight: 600 !important;
    font-size: 12px !important;
    border-bottom: 1px solid #e2e8f0 !important;
}
.cue-table td, .cue-table tr td {
    background: #ffffff !important;
    color: #0f172a !important;
    font-size: 13px !important;
    border-bottom: 1px solid #f1f5f9 !important;
}
.cue-table tbody tr:hover td { background: #f8fafc !important; }
.cue-table td textarea, .cue-table td input { color: #0f172a !important; background: transparent !important; }
.cue-table-wrap .label-wrap span { color: #4f46e5 !important; font-weight: 600 !important; }
.progress-status-box {
    margin-top: 10px !important;
    padding: 9px 12px !important;
    border-radius: 9px !important;
    background: #f8fafc !important;
    border: 1px solid #e6ebf3 !important;
    border-left: 3px solid #a5b4fc !important;
    font-size: 12.5px !important;
    color: #475569 !important;
    min-height: 40px !important;
}
.progress-status-box p {
    margin: 0 !important;
    font-size: 12.5px !important;
    line-height: 1.55 !important;
    color: #475569 !important;
}
.progress-status-box strong {
    color: #4338ca !important;
}

/* ============ 统一字段标签：去掉默认的胶囊底色 ============ */
.gradio-container span[data-testid="block-info"] {
    background: transparent !important;
    border: none !important;
    padding: 0 !important;
    color: #475569 !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em !important;
}

/* ============ 顶部面板内的 HTML 小标题 / 提示行 ============ */
.setup-head-wrap,
.upload-hint-wrap,
.acc-hint-wrap {
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    min-height: 0 !important;
}
.setup-head-wrap .html-container,
.upload-hint-wrap .html-container,
.acc-hint-wrap .html-container,
.setup-head-wrap .prose,
.upload-hint-wrap .prose,
.acc-hint-wrap .prose {
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    background: transparent !important;
}

/* ============ 执行按钮 ============ */
button.btn-run {
    width: 100% !important;
    height: 42px !important;
    min-height: 42px !important;
    font-size: 14px !important;
    letter-spacing: 0.04em !important;
    border-radius: 9px !important;
    margin-top: 2px !important;
}
.run-secondary-row {
    gap: 6px !important;
    margin-top: 6px !important;
}
.run-secondary-row button {
    min-width: 0 !important;
    flex: 1 1 0 !important;
    height: 32px !important;
    min-height: 32px !important;
    padding: 0 6px !important;
    font-size: 12px !important;
    border-radius: 8px !important;
}

/* ============ 转录任务详报面板（与顶部设备胶囊同风格 · 自带滚动容器） ============ */
.report-panel-wrap {
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    min-height: 0 !important;
}
.report-panel-wrap .html-container,
.report-panel-wrap .prose {
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    background: transparent !important;
}
.report-panel {
    border: 1px solid #e6ebf3;
    border-left: 3px solid #a5b4fc;
    border-radius: 10px;
    background: #f8fafc;
    padding: 12px 14px 12px 14px;
}
.report-panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    flex-wrap: wrap;
    padding-bottom: 9px;
    margin-bottom: 10px;
    border-bottom: 1px solid #e9eef6;
}
.report-panel-title {
    font-size: 12.5px;
    font-weight: 700;
    letter-spacing: 0.01em;
    color: #334155;
}
.report-panel-hint {
    font-size: 11px;
    color: #94a3b8;
}
.report-metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
    margin-bottom: 12px;
}
.report-metrics .device-chip {
    height: 28px;
    padding: 0 11px;
    background: #ffffff;
}
.report-body {
    max-height: min(58vh, 520px);
    overflow-y: auto;
    overscroll-behavior: auto;
    padding-right: 8px;
    scrollbar-width: thin;
    scrollbar-color: #d3dced transparent;
}
.report-body::-webkit-scrollbar {
    width: 8px;
}
.report-body::-webkit-scrollbar-track {
    background: transparent;
}
.report-body::-webkit-scrollbar-thumb {
    background: #dbe3ee;
    border-radius: 4px;
}
.report-body::-webkit-scrollbar-thumb:hover {
    background: #c3cfe0;
}
.rp-sec {
    margin-bottom: 12px;
}
.rp-sec:last-child {
    margin-bottom: 2px;
}
.rp-sec-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    flex-wrap: wrap;
    padding-bottom: 6px;
    margin-bottom: 6px;
    border-bottom: 1px solid #e9eef6;
}
.rp-sec-head::before {
    content: "";
    width: 3px;
    height: 11px;
    border-radius: 2px;
    background: #a5b4fc;
    flex: none;
    align-self: center;
}
.rp-sec-title {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: #334155;
}
.rp-sec-note {
    font-size: 11.5px;
    color: #64748b;
}
.rp-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 3px 0;
    font-size: 12.5px;
    line-height: 1.6;
}
.rp-row + .rp-row {
    border-top: 1px dashed #e9eef6;
}
.rp-key {
    flex: 0 0 auto;
    min-width: 96px;
    max-width: 40%;
    color: #64748b;
}
.rp-val {
    flex: 1 1 auto;
    min-width: 0;
    color: #1e293b;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    word-break: break-word;
}
.rp-val.is-accent {
    color: #4338ca;
    font-weight: 600;
}
.rp-note {
    padding: 2px 0 6px 0;
    font-size: 12px;
    color: #475569;
}
.report-empty {
    padding: 16px 4px;
    font-size: 12.5px;
    color: #94a3b8;
}
.report-raw-src {
    display: none !important;
}
"""

try:
    CUSTOM_THEME = gr.themes.Soft(
        primary_hue="indigo",
        neutral_hue="slate",
        spacing_size="sm",
        radius_size="md",
    )
except Exception:
    CUSTOM_THEME = None


def _format_time_simple(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def _render_proxy_progress_card(
    pct: int | None,
    current_s: float,
    total_s: float,
    speed_str: str = "1.0x",
    stage_desc: str = "正在压制 480p 流畅监看代理…",
    note: str = "VideoToolbox 硬件加速中",
) -> str:
    """渲染左侧压制进度卡片。

    ``pct=None`` 时渲染「不确定进度」的流动条纹条（启动阶段、回退压制、时长未知时），
    这样无需凭空造一个百分比，也就不会出现 99% → 50% 这种倒退。
    """
    tot_str = _format_time_simple(total_s) if total_s and total_s > 0 else "--:--"
    cur_str = _format_time_simple(current_s)

    if pct is None:
        pct_html = '<b class="ppc-pct">处理中</b>'
        bar_html = '<div class="ppc-track"><div class="ppc-indet"></div></div>'
    else:
        pct_clamped = max(0, min(100, int(pct)))
        pct_html = f'<b class="ppc-pct">{pct_clamped}%</b>'
        bar_html = (
            '<div class="ppc-track">'
            f'<div class="ppc-fill" style="width:{pct_clamped}%;"></div>'
            "</div>"
        )

    return (
        '<div class="proxy-progress-card">'
        '<div class="ppc-head">'
        f'<div class="ppc-stage">⚡ {html.escape(stage_desc)}</div>'
        f'<div class="ppc-right">{pct_html}<em class="ppc-speed">({html.escape(speed_str)})</em></div>'
        "</div>"
        f"{bar_html}"
        '<div class="ppc-foot">'
        f'<div class="ppc-time">时间: {cur_str} / {tot_str}</div>'
        f'<div class="ppc-note">{html.escape(note)}</div>'
        "</div>"
        "</div>"
    )


_PROXY_JOB_LOCK = threading.Lock()
_PROXY_JOB_ACTIVE = False


def _drop_broken_proxy(path: Path) -> None:
    """压制失败时删掉半成品，否则下一次点击会把它当成「历史代理」秒级复用。"""
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def manual_transcode_proxy_generator(media_file, review_cues):
    """带实时精准进度条的 480p 监看代理压制器（流式刷新左侧状态卡片）。

    重要：这里**不要**再用 ``progress=gr.Progress()`` 或调用 ``progress()``。
    Gradio 原生进度追踪器会被渲染进 ``proxy_status`` 这个输出组件的容器里，而它的
    文字刷新被三重限制卡着（见 gradio statustracker：只在「每 10% 一档」跨档时才换文案、
    两次换文案至少间隔 5 秒、文案 1 秒后自动清空）。结果是同一个位置上有两个各自刷新的
    进度源：卡片按 0.3s 走真实百分比，原生追踪器却周期性地把 1 秒前的旧百分比贴上来，
    于是界面上就在两种形态之间反复横跳（19% ↔ 33%）。现在只保留卡片这一个进度源，
    事件侧用 ``show_progress="hidden"`` 彻底关掉原生追踪器。
    """
    if not media_file:
        gr.Warning("⚠️ 请先在上方上传音视频文件。")
        yield gr.update(), "⚠️ 请先在上方上传音视频文件。"
        return

    media_path = Path(media_file)
    if not media_path.exists():
        gr.Warning("⚠️ 媒体临时文件已失效，请重新上传。")
        yield gr.update(), "⚠️ 媒体临时文件已失效，请重新上传。"
        return

    file_size = media_path.stat().st_size if media_path.exists() else 0
    clean_stem = media_path.stem
    standard_proxy = PROXIES_DIR / f"{clean_stem}_{file_size}_preview.mp4"

    if standard_proxy.exists() and standard_proxy.stat().st_size > 50 * 1024:
        payload = build_review_payload(media_file, review_cues, include_peaks=True)
        gr.Info("⚡ 检测到已有历史压制代理，已秒级直接切换！")
        yield payload, f"🎉 **已秒级复用历史代理（{standard_proxy.name}）！** 画面已对齐，拖拽现已流畅秒开。"
        return

    # 同一时刻只允许一个压制任务，避免两个 ffmpeg 同时写同一个成片（会互相截断、进度互相打架）
    global _PROXY_JOB_ACTIVE
    with _PROXY_JOB_LOCK:
        if _PROXY_JOB_ACTIVE:
            gr.Warning("⚠️ 已有压制任务在运行，请等当前进度条走完再点。")
            yield gr.update(), "⏳ **已有压制任务在运行**，请等当前进度条走完再点。"
            return
        _PROXY_JOB_ACTIVE = True

    try:
        total_duration = 0.0
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(media_path)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            total_duration = max(0.0, float(probe.stdout.strip()))
        except Exception:
            total_duration = 0.0  # 探不到时长就走「不确定进度」，不要瞎猜 180 秒

        cmd_hw = [
            "ffmpeg", "-y",
            "-hwaccel", "videotoolbox",
            "-i", str(media_path),
            "-vf", "scale=-2:480,format=yuv420p",
            "-c:v", "h264_videotoolbox",
            "-b:v", "2200k",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            str(standard_proxy)
        ]

        yield gr.update(), _render_proxy_progress_card(
            None, 0, total_duration, "准备中…", "正在启动 VideoToolbox 硬件压制…", "初始化编码器"
        )

        proc = None
        ok = False
        max_out_s = 0.0
        current_speed = "1.0x"
        try:
            proc = subprocess.Popen(cmd_hw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            last_yield_time = time.time()
            last_pct = -1

            while True:
                line = proc.stdout.readline() if proc.stdout else ""
                if not line and proc.poll() is not None:
                    break
                line_str = line.strip()
                if "=" in line_str:
                    k, v = line_str.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k == "out_time_us":
                        try:
                            # 只认单调值：ffmpeg 偶发回退/重置时进度条绝不倒走
                            max_out_s = max(max_out_s, float(v) / 1000000.0)
                        except ValueError:
                            pass
                    elif k == "speed" and v.endswith("x"):
                        current_speed = v

                now = time.time()
                if now - last_yield_time < 0.3:
                    continue

                if total_duration > 0:
                    pct = int(min(99.0, max(0.0, (max_out_s / total_duration) * 100)))
                else:
                    pct = None

                # 百分比没变就不刷新（只偶尔补一次速度/时间），避免每 0.3s 无意义重绘造成闪烁
                if pct == last_pct and now - last_yield_time < 1.5:
                    continue
                last_pct = pct
                last_yield_time = now
                yield gr.update(), _render_proxy_progress_card(
                    pct, max_out_s, total_duration, current_speed
                )

            proc.wait(timeout=10)
            ok = proc.returncode == 0
        except Exception as exc:
            logging.warning(f"VideoToolbox 实时压制异常: {exc}")
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass

        if ok and standard_proxy.exists() and standard_proxy.stat().st_size > 50 * 1024:
            # 收尾阶段（算峰值、切画面）也占时间，先补一帧 100%，避免卡片停在 90% 看起来像卡死
            yield gr.update(), _render_proxy_progress_card(
                100 if total_duration > 0 else None,
                total_duration or max_out_s,
                total_duration,
                current_speed,
                "压制完成，正在载入监看画面…",
                "收尾：生成波形峰值",
            )
            payload = build_review_payload(media_file, review_cues, include_peaks=True)
            gr.Info(f"🎉 480p 监看代理压制成功（{standard_proxy.name}）！")
            yield payload, f"🎉 **480p 监看代理压制成功！** 已自动切换为轻量代理（`{standard_proxy.name}`），视频拖拽现已流畅秒开。"
            return

        # 硬解失败：删掉半成品再走回退链，避免下次点击复用到一个截断文件
        _drop_broken_proxy(standard_proxy)
        yield gr.update(), _render_proxy_progress_card(
            None, 0, total_duration, "回退模式", "VideoToolbox 直通失败，正在切换回退压制…", "软解 + 硬件编码（不确定进度）"
        )
        proxy_fallback = create_m4pro_hardware_proxy(media_path)
        if proxy_fallback and proxy_fallback.exists():
            payload = build_review_payload(media_file, review_cues, include_peaks=True)
            gr.Info(f"🎉 回退方案压制成功（{proxy_fallback.name}）！")
            yield payload, f"🎉 **480p 代理生成成功（回退方案）！** 已切换为轻量代理（`{proxy_fallback.name}`），拖拽现已流畅秒开。"
        else:
            gr.Warning("⚠️ 代理压制未能成功，继续保持原片监看。")
            yield gr.update(), "⚠️ 代理压制未能成功，继续保持原片监看。"
    finally:
        with _PROXY_JOB_LOCK:
            _PROXY_JOB_ACTIVE = False


with gr.Blocks(title="🎬 日语影视字幕转录工作台", theme=CUSTOM_THEME, css=CSS_CUSTOM) as demo:
    with gr.Row(elem_classes=["app-header"]):
        with gr.Column(scale=1, min_width=280, elem_classes=["app-title-col"]):
            gr.Markdown("### 🎬 日语影片字幕转录工作台")
        with gr.Column(scale=2, min_width=380, elem_classes=["app-status-col"]):
            gr.HTML(device_banner(), elem_classes=["device-header"])

    with gr.Row(elem_classes=["bridge-hidden"], elem_id="bridge-hidden-row"):
        hidden_sync_start = gr.Textbox(elem_id="hidden-sync-start", value="")
        hidden_sync_end = gr.Textbox(elem_id="hidden-sync-end", value="")
        btn_hidden_bridge_sync = gr.Button(elem_id="btn-hidden-bridge-sync")
        btn_hidden_bridge_transcribe = gr.Button(elem_id="btn-hidden-bridge-transcribe")

    with gr.Group(elem_classes=["workbench-panel", "setup-panel"]):
        with gr.Row(elem_classes=["setup-row"]):
            with gr.Column(scale=5, min_width=320, elem_classes=["setup-col"]):
                gr.HTML(
                    '<div class="setup-head"><span class="step">1</span>导入待转写媒体</div>',
                    elem_classes=["setup-head-wrap"],
                )
                media = gr.File(
                    label="📁 上传日语视频/音频文件",
                    file_types=sorted(SUPPORTED),
                    type="filepath",
                    show_label=False,
                    elem_classes=["media-upload"],
                )
                gr.HTML(
                    '<div class="upload-hint">支持 <b>MP4/MKV/MOV/WAV/MP3/FLAC</b> · 单文件 ≤ 10 GB</div>',
                    elem_classes=["upload-hint-wrap"],
                )
                engine_name = gr.Radio(
                    list(ENGINES),
                    value="Anime Whisper（litagin）",
                    label="🎯 识别引擎架构",
                    info="Anime Whisper 擅长连贯日常对话；Qwen3-ASR 搭载 CTC 逐字发声对齐，断句更精准。",
                )

            with gr.Column(scale=4, min_width=300, elem_classes=["setup-col"]):
                gr.HTML(
                    '<div class="setup-head"><span class="step">2</span>调优预设方案</div>',
                    elem_classes=["setup-head-wrap"],
                )
                preset_pick = gr.Dropdown(
                    choices=preset_choices_list(),
                    value=preset_choices_list()[0][1] if STORE.names() else None,
                    label="选择已保存的方案",
                )
                with gr.Row(elem_classes=["preset-btn-row"]):
                    load_btn = gr.Button("📥 载入", variant="secondary", elem_classes=["btn-subtle"])
                    reset_btn = gr.Button("🔄 恢复默认", variant="secondary", elem_classes=["btn-subtle"])
                preset_name = gr.Textbox(
                    label="另存为新预设",
                    placeholder="输入方案名称…",
                )
                with gr.Row(elem_classes=["preset-btn-row"]):
                    save_btn = gr.Button("💾 保存", variant="secondary", elem_classes=["btn-subtle"])
                    delete_btn = gr.Button("🗑️ 删除", variant="secondary", elem_classes=["btn-subtle"])

            with gr.Column(scale=4, min_width=300, elem_classes=["setup-col"]):
                gr.HTML(
                    '<div class="setup-head"><span class="step">3</span>输出与执行</div>',
                    elem_classes=["setup-head-wrap"],
                )
                output_format = gr.Radio(["SRT", "VTT", "TXT"], value="SRT", label="输出格式")
                save_beside = gr.Checkbox(value=False, label="保存至媒体同级目录")
                run_btn = gr.Button("🚀 开始转写", variant="primary", elem_classes=["btn-primary-action", "btn-run"])
                with gr.Row(elem_classes=["run-secondary-row"]):
                    stop_btn = gr.Button("⏹ 中途打断", variant="secondary", interactive=False, elem_classes=["btn-subtle"])
                    clean_btn = gr.Button("🧹 清理标点", variant="secondary", interactive=False, elem_classes=["btn-subtle"])
                transcribe_progress = gr.Markdown("⚡ 状态：就绪，点击「开始转写」即可执行。", elem_classes=["progress-status-box"])
                clean_status = gr.Markdown("")

        with gr.Accordion("⏱️ 时间片段截取与补转区间", open=False, elem_classes=["slice-accordion", "clean-accordion"]) as slice_acc:
            gr.HTML(
                '<div class="acc-hint">在下方波形上拖拽框选后点「⏱ 同步时间到顶部」即可自动填入；'
                "起始留空表示从头开始，终止留空表示转至片尾；开启<b>全局对齐</b>后生成的时间戳直接对应视频总进度。</div>",
                elem_classes=["acc-hint-wrap"],
            )
            with gr.Row():
                start_time_input = gr.Textbox(
                    label="起始时间点",
                    placeholder="留空从头开始。支持 00:05:00 或 300 (秒)",
                    scale=2,
                    elem_id="slice-start",
                )
                end_time_input = gr.Textbox(
                    label="终止时间点",
                    placeholder="留空转至片尾。支持 00:08:30 或 510 (秒)",
                    scale=2,
                    elem_id="slice-end",
                )
                keep_timeline_chk = gr.Checkbox(
                    value=True,
                    label="时间轴与原片全局对齐",
                    scale=2,
                )

        with gr.Accordion("⚙️ 声学分段与 VAD 参数精细调优", open=False, elem_classes=["clean-accordion"]):
            active_params_display = gr.HTML(elem_classes=["active-params-banner"])
            gr.HTML(
                '<div class="acc-hint">多列平铺展示全部可调参数：<b>调小</b>更灵敏、更容易切碎；'
                "<b>调大</b>更稳健、更容易吞掉短音。改动会即时同步到上方「当前生效参数」。</div>",
                elem_classes=["acc-hint-wrap"],
            )

            with gr.Group(visible=True) as whisper_params:
                with gr.Row():
                    enable_split = param(
                        "whisper.enable_sentence_split",
                        "智能句级分切",
                        gr.Checkbox(value=True, label="启用句级分切与平滑时间分配"),
                        "whisper",
                        "bool",
                        "enable_sentence_split",
                    )
                    enable_loudnorm = param(
                        "whisper.enable_loudnorm",
                        "动态响度归一化",
                        gr.Checkbox(value=False, label="启用动态响度归一化 (弱人声增强)"),
                        "whisper",
                        "bool",
                        "enable_loudnorm",
                    )
                with gr.Row():
                    vad_threshold = param(
                        "whisper.vad_threshold",
                        "VAD 语音判定阈值",
                        gr.Slider(0.05, 0.80, value=0.30, step=0.01, label="VAD 判定阈值", info="【调小】对微弱耳语更灵敏；【调大】抗噪更强，过滤背景音乐"),
                        "whisper",
                        "float",
                        "threshold",
                    )
                    vad_speech_pad_ms = param(
                        "whisper.vad_speech_pad_ms",
                        "语音留白缓冲 (ms)",
                        gr.Slider(0, 400, value=200, step=10, label="留白缓冲 (ms)", info="【调大】防吞头尾音与呼吸声；【调小】切除无效空白"),
                        "whisper",
                        "int",
                        "speech_pad_ms",
                    )
                    vad_min_silence_ms = param(
                        "whisper.vad_min_silence_ms",
                        "判定停顿静音 (ms)",
                        gr.Slider(50, 600, value=150, step=10, label="判定停顿静音 (ms)", info="【调小】频繁切成短句；【调大】连贯保留长句"),
                        "whisper",
                        "int",
                        "min_silence_ms",
                    )
                with gr.Row():
                    vad_min_speech_ms = param(
                        "whisper.vad_min_speech_ms",
                        "最短语音片段 (ms)",
                        gr.Slider(0, 500, value=120, step=10, label="最短语音 (ms)", info="【调小】捕获短叹词/呼声；【调大】过滤短促爆音与杂音"),
                        "whisper",
                        "int",
                        "min_speech_ms",
                    )
                    vad_merge_gap_s = param(
                        "whisper.vad_merge_gap_s",
                        "片段合并间隔 (s)",
                        gr.Slider(0.0, 2.0, value=0.30, step=0.05, label="片段合并间隔 (s)", info="【调大】相邻对话合并不拆碎；【调小】严格按停顿分段"),
                        "whisper",
                        "float",
                        "merge_gap_s",
                    )
                    vad_max_segment_s = param(
                        "whisper.vad_max_segment_s",
                        "单次送模最长 (s)",
                        gr.Slider(5.0, 28.0, value=12.0, step=1.0, label="单次送模最长 (s)", info="【调小】识别快且极少幻觉；【调大】上下文理解连贯"),
                        "whisper",
                        "float",
                        "max_segment_s",
                    )
                with gr.Row():
                    whisper_cue_pad = param(
                        "whisper.cue_pad_s",
                        "字幕显示留白 (s)",
                        gr.Slider(0.0, 0.3, value=0.02, step=0.01, label="字幕外扩留白 (s)", info="【调大】字幕提前出现并滞后消失，观影更舒适"),
                        "whisper",
                        "float",
                        "cue_pad_s",
                    )
                    ngram = param(
                        "whisper.no_repeat_ngram_size",
                        "重复幻觉抑制 n-gram",
                        gr.Slider(0, 10, value=5, step=1, label="重复词抑制 n-gram", info="【调大】强力杜绝自回归连续复读卡死现象；0 为关闭"),
                        "whisper",
                        "int",
                    )
                    penalty = param(
                        "whisper.repetition_penalty",
                        "重复惩罚因子",
                        gr.Slider(1.0, 1.4, value=1.15, step=0.05, label="重复惩罚因子", info="【调大】显著抑制重复输出词组，推荐 1.10~1.20"),
                        "whisper",
                        "float",
                    )
                    vad_min_speech_s = param(
                        "whisper.vad_min_speech_s",
                        "合并后最短片段 (s)",
                        gr.Slider(0.0, 0.5, value=0.08, step=0.01, label="合并后最短片段 (s)", info="过滤合并后仍过短的碎片音频"),
                        "whisper",
                        "float",
                        "min_speech_s",
                    )

            with gr.Group(visible=False) as qwen_params:
                with gr.Row():
                    qwen_loudnorm = param(
                        "qwen.enable_loudnorm",
                        "动态响度归一化",
                        gr.Checkbox(value=True, label="启用动态响度归一化 (弱人声强化)"),
                        "qwen",
                        "bool",
                        "enable_loudnorm",
                    )
                    use_alignment = param(
                        "qwen.use_alignment",
                        "启用逐字 CTC 对齐",
                        gr.Checkbox(value=True, label="启用 CTC 逐字发声帧时间轴高精对齐"),
                        "qwen",
                        "bool",
                    )
                with gr.Row():
                    qwen_vad_threshold = param(
                        "qwen.vad_threshold",
                        "VAD 判定阈值",
                        gr.Slider(0.05, 0.80, value=0.30, step=0.01, label="VAD 判定阈值", info="【调小】对低声耳语极灵敏；【调大】抗噪更强"),
                        "qwen",
                        "float",
                        "vad_threshold",
                    )
                    qwen_speech_pad = param(
                        "qwen.vad_speech_pad_ms",
                        "首尾留白 (ms)",
                        gr.Slider(0, 400, value=150, step=10, label="首尾留白 (ms)", info="【调大】防止句首辅音或句尾被意外切断"),
                        "qwen",
                        "int",
                        "vad_speech_pad_ms",
                    )
                    qwen_merge_gap = param(
                        "qwen.merge_gap_s",
                        "片段合并间隔 (s)",
                        gr.Slider(0.1, 1.5, value=0.5, step=0.05, label="合并间隔 (s)", info="【调大】相邻语音段合并为连贯大段送模"),
                        "qwen",
                        "float",
                        "merge_gap_s",
                    )
                with gr.Row():
                    min_pause_s = param(
                        "qwen.min_pause_s",
                        "断句停顿最小静音 (s)",
                        gr.Slider(0.04, 0.40, value=0.12, step=0.01, label="断句停顿静音 (s)", info="【调小】更易断句切片；【调大】只在明显停顿处断句"),
                        "qwen",
                        "float",
                        "min_pause_s",
                    )
                    max_cue_dur = param(
                        "qwen.max_cue_dur",
                        "单条字幕目标时长 (s)",
                        gr.Slider(2.0, 8.0, value=4.3, step=0.1, label="单条字幕目标时长 (s)", info="【调小】字幕紧凑切换；【调大】长句整体展示"),
                        "qwen",
                        "float",
                        "max_cue_dur",
                    )
                    max_cue_chars = param(
                        "qwen.max_cue_chars",
                        "单条最多字数",
                        gr.Slider(8, 35, value=21, step=1, label="单条最多字数", info="超出后根据日语语法助词进行平滑安全折断"),
                        "qwen",
                        "int",
                        "max_cue_chars",
                    )
                with gr.Row():
                    qwen_max_segment_s = param(
                        "qwen.max_segment_s",
                        "送模音频窗口 (s)",
                        gr.Slider(10.0, 25.0, value=16.0, step=1.0, label="送模音频窗口 (s)", info="12~18 秒为 Qwen 识别与 CTC 对齐的最佳平衡区间"),
                        "qwen",
                        "float",
                        "max_segment_s",
                    )
                    cue_pad = param(
                        "qwen.cue_pad_s",
                        "字幕前后留白 (s)",
                        gr.Slider(0.0, 0.30, value=0.12, step=0.01, label="字幕前后留白 (s)", info="字幕在画面停留的舒适缓冲"),
                        "qwen",
                        "float",
                        ("cue_pad_start_s", "cue_pad_end_s"),
                    )



    with gr.Row(elem_classes=["workbench-main-row"]):
        with gr.Column(scale=7, elem_classes=["workbench-panel"]):
            with gr.Row(elem_classes=["monitor-toolbar"]):
                monitor_upload = gr.UploadButton(
                    "📂 导入监看画面",
                    file_types=["video"],
                    size="sm",
                    variant="secondary",
                    min_width=120,
                    elem_id="btn-monitor-import",
                )
                manual_proxy_btn = gr.Button(
                    "⚡ 压制 480p 代理",
                    size="sm",
                    variant="secondary",
                    min_width=115,
                    elem_id="btn-monitor-proxy",
                )
                monitor_close_btn = gr.Button(
                    "✕ 关闭监看",
                    size="sm",
                    variant="secondary",
                    min_width=95,
                    elem_id="btn-monitor-close",
                )
                monitor_auto_btn = gr.Button(
                    "↺ 恢复自动",
                    size="sm",
                    variant="secondary",
                    min_width=95,
                    elem_id="btn-monitor-auto",
                )
            with gr.Row(elem_classes=["monitor-toolbar"]):
                monitor_proxy_pick = gr.Dropdown(
                    choices=list_proxy_choices(),
                    value=None,
                    label="📦 历史 480p 代理（点选即载入，零拷贝复用）",
                    interactive=True,
                    visible=bool(list_proxy_choices()),
                    elem_id="monitor-proxy-pick",
                )
            # 【核心新增】：左侧压制按钮下方的专属媒体状态与实时压制进度条
            proxy_status = gr.Markdown(
                "🎞️ 媒体监看待机中。导入音视频后会自动载入画面；"
                "若浏览器播放 10-bit/8K 卡顿或黑屏，点「⚡ 压制 480p 代理」即可。",
                elem_classes=["proxy-status-box"],
            )
            reviewer = gr.HTML(REVIEWER_HTML)
            review_payload = gr.Textbox(value="", visible=False, elem_id="review-payload")

        with gr.Column(scale=5, elem_classes=["workbench-panel"]):
            with gr.Row(elem_classes=["editor-header-bar"]):
                with gr.Column(scale=5):
                    gr.Markdown("#### 📋 字幕核对与精修工作台")
                with gr.Column(scale=7):
                    with gr.Row():
                        prev_cue_btn = gr.Button("⏮️ 上一行字幕", size="sm", variant="secondary")
                        next_cue_btn = gr.Button("⏭️ 下一行字幕", size="sm", variant="secondary")
                    with gr.Row():
                        with gr.Row(scale=1):
                            undo_cue_btn = gr.Button("↩️ 撤回", size="sm", variant="secondary", elem_id="btn-reviewer-undo")
                            redo_cue_btn = gr.Button("↪️ 重做", size="sm", variant="secondary", elem_id="btn-reviewer-redo")
                        clean_review_btn = gr.Button("🧹 清理标点", size="sm", variant="secondary", scale=1)
                    with gr.Row():
                        clear_review_btn = gr.Button("❌ 清空", size="sm", variant="secondary")

            review_status = gr.Markdown("📋 **字幕精修状态**：就绪。点击下方表格行或波形框选识别，字幕将在此同步供精修。")

            with gr.Row():
                latest_as_base_btn = gr.Button("📌 本次设为基线", variant="secondary", size="sm")
                append_patch_btn = gr.Button("➕ 添加本次局部转写", variant="primary", size="sm", elem_classes=["btn-primary-action"])
                export_review_btn = gr.Button("💾 导出最终已核对 SRT", variant="secondary", size="sm")

            reviewed_download = gr.File(label="📥 最终字幕已生成，点击下载：", visible=False, elem_classes=["reviewed-download-box"])

            with gr.Group():
                gr.Markdown("##### ✏️ 字幕单行精修与插入（选区识别或点击下方表格将自动填入此处）")
                with gr.Row():
                    cue_edit_idx = gr.Number(
                        label="选中行序号", 
                        value=1, 
                        precision=0, 
                        scale=1, 
                        min_width=75,
                        elem_id="cue-edit-idx"
                    )
                    cue_edit_start = gr.Textbox(
                        label="起始时间", 
                        placeholder="00:00:00,000", 
                        scale=2, 
                        min_width=110,
                        elem_id="cue-edit-start"
                    )
                    cue_edit_end = gr.Textbox(
                        label="结束时间", 
                        placeholder="00:00:00,000", 
                        scale=2, 
                        min_width=110,
                        elem_id="cue-edit-end"
                    )

                cue_edit_text = gr.Textbox(
                    label="字幕文本内容", 
                    placeholder="修改或核对识别出的字幕文本…", 
                    lines=2, 
                    max_lines=4,
                    elem_id="cue-edit-text"
                )

                with gr.Row():
                    play_cue_btn = gr.Button("▶ 跳转试听", size="sm", variant="secondary", scale=2)
                    update_cue_btn = gr.Button("✏️ 更新此行", size="sm", variant="primary", scale=3, elem_classes=["btn-primary-action"])
                    delete_cue_btn = gr.Button("🗑️ 删除此行", size="sm", variant="secondary", scale=2)

                with gr.Row():
                    insert_cue_btn = gr.Button("➕ 插入为新句", size="sm", variant="secondary", scale=1)
                    # === 新增复制按钮 ===
                    copy_cue_btn = gr.Button("📋 复制本句", size="sm", variant="secondary", scale=1, elem_id="btn-copy-cue")
                    apply_table_btn = gr.Button("📋 保存表格全量修改", size="sm", variant="secondary", scale=1)

            with gr.Accordion("📥 外部 SRT 字幕文件导入", open=False, elem_classes=["clean-accordion"]):
                with gr.Row():
                    review_srt_file = gr.File(label="选择要导入的 SRT 字幕文件", file_types=[".srt"], type="filepath", scale=3)
                    import_review_btn = gr.Button("📥 导入并设为基线", variant="secondary", scale=1)

    with gr.Group(elem_classes=["workbench-panel"]):
        review_table = gr.Dataframe(
            headers=["序号", "起始时间", "结束时间", "时长", "字幕内容"],
            datatype=["number", "str", "str", "str", "str"],
            label="📋 核对时间轴全景视图（通栏平铺展开 · 支持双击单元格原地编辑，点击任意行自动载入上方精修）",
            interactive=True,
            wrap=True,
            max_height=450,
            elem_classes=["cue-table", "cue-table-wrap"],
        )

    with gr.Accordion("📊 全片转录原始结果、表格与任务详报", open=True, elem_classes=["clean-accordion"]):
        status = gr.Markdown(
            "状态：就绪。上传音视频文件并点击「🚀 开始转写」即可执行。",
            elem_classes=["progress-status-box"],
        )
        with gr.Tabs():
            with gr.TabItem("📋 原始条目列表"):
                cue_table = gr.Dataframe(
                    headers=["序号", "起始时间", "结束时间", "字幕内容"],
                    datatype=["number", "str", "str", "str"],
                    interactive=False,
                    wrap=True,
                    elem_classes=["cue-table"],
                )
            with gr.TabItem("📝 SRT 纯文本预览"):
                preview = gr.Textbox(label="字幕内容文本", lines=10)
            with gr.TabItem("📊 转录任务详报与参数清单"):
                report_box = gr.HTML(
                    render_report_panel(""),
                    elem_classes=["report-panel-wrap"],
                )
                with gr.Row():
                    copy_report_btn = gr.Button("📋 一键复制转录详报与参数清单", variant="secondary", size="sm")
                    copy_status = gr.Markdown("")
        with gr.Row():
            download = gr.File(label="本次转写直接下载", scale=1)
            saved_path = gr.Textbox(label="本地生成完整路径", interactive=False, scale=2)

    validate_params()
    PARAM_COMPONENTS = [spec.component for spec in PARAMS]

    initial_defaults = [spec.default for spec in PARAMS]
    active_params_display.value = render_active_params_banner("Anime Whisper（litagin）", *initial_defaults)

    cues_state = gr.State([])
    review_cues_state = gr.State([])
    undo_stack_state = gr.State([])
    redo_stack_state = gr.State([])

    # 关键修复：去掉 slice_acc 更新，增加 queue=False，纯静默安全同步输入框变量
    btn_hidden_bridge_sync.click(
        sync_selection_to_transcribe_inputs,
        inputs=[hidden_sync_start, hidden_sync_end],
        outputs=[start_time_input, end_time_input, review_status],
        queue=False,
        api_name=False,
    )

    reset_transcribe_btn_js = """
    () => {
        const btn = document.querySelector('#rw-transcribe-sel-btn');
        if (btn) {
            btn.textContent = '⚡ 识别并直接入轨';
            btn.disabled = false;
        }
        const textElem = document.querySelector('#cue-edit-text textarea, #cue-edit-text input');
        if (textElem) {
            textElem.focus();
            textElem.select();
        }
    }
    """

    btn_hidden_bridge_transcribe.click(
        transcribe_selection_to_editor,
        inputs=[
            media,
            engine_name,
            hidden_sync_start,
            hidden_sync_end,
            review_cues_state,
            undo_stack_state,
            redo_stack_state,
            *PARAM_COMPONENTS,
        ],
        outputs=[
            review_cues_state,
            review_table,
            review_payload,
            cue_edit_idx,
            cue_edit_start,
            cue_edit_end,
            cue_edit_text,
            review_status,
            undo_stack_state,
            redo_stack_state,
        ],
        api_name=False,
    ).then(
        None,
        inputs=None,
        outputs=None,
        js=reset_transcribe_btn_js,
        api_name=False,
    )

    review_payload.change(
        None,
        inputs=review_payload,
        outputs=None,
        js=REVIEWER_CLIENT_JS,
        api_name=False,
    )
    # 核心改动：导入媒体时的正常载入提示 -> 输出到左侧 proxy_status
    media.change(
        prepare_review_workspace,
        inputs=[media, review_cues_state],
        outputs=[review_payload, proxy_status],
        api_name=False,
    )
    # 核心改动：点击压制后的进度条与切换提示 -> 实时流式输出到左侧 proxy_status
    # show_progress="hidden" 必须保留：否则 Gradio 原生进度追踪器会渲染进 proxy_status 容器，
    # 与卡片自身的进度条形成两个刷新节奏不同的进度源，导致百分比来回横跳。
    manual_proxy_btn.click(
        manual_transcode_proxy_generator,
        inputs=[media, review_cues_state],
        outputs=[review_payload, proxy_status],
        show_progress="hidden",
        concurrency_limit=1,
        api_name=False,
    ).then(
        refresh_monitor_proxy_choices,
        inputs=None,
        outputs=[monitor_proxy_pick],
        show_progress="hidden",
        api_name=False,
    )

    # 📂 手动导入监看画面：只换画面片源，不动转录源与字幕基线
    monitor_upload.upload(
        load_manual_monitor,
        inputs=[monitor_upload, review_cues_state],
        outputs=[review_payload, proxy_status],
        api_name=False,
    )
    # 📦 选中历史代理即载入（零拷贝复用 web_proxies 中的成片）
    monitor_proxy_pick.change(
        load_proxy_as_monitor,
        inputs=[monitor_proxy_pick, review_cues_state],
        outputs=[review_payload, proxy_status, monitor_proxy_pick],
        api_name=False,
    )
    # ✕ 关闭监看画面（字幕与波形数据保留）
    monitor_close_btn.click(
        close_monitor,
        inputs=[review_cues_state],
        outputs=[review_payload, proxy_status],
        api_name=False,
    )
    # ↺ 恢复自动跟随当前导入的媒体
    monitor_auto_btn.click(
        restore_auto_monitor,
        inputs=[media, review_cues_state],
        outputs=[review_payload, proxy_status],
        api_name=False,
    )
    # 页面打开时自动恢复上次使用的监看片源（失效则提示重新指定）
    demo.load(
        restore_monitor_on_load,
        inputs=[review_cues_state],
        outputs=[review_payload, proxy_status],
        api_name=False,
    ).then(
        refresh_monitor_proxy_choices,
        inputs=None,
        outputs=[monitor_proxy_pick],
        api_name=False,
    )

    seek_cue_js = """
    (startTimeStr) => {
        if (!startTimeStr) return;
        let sec = 0;
        const str = String(startTimeStr).trim();
        if (str.includes(':')) {
            const parts = str.replace(',', '.').split(':');
            if (parts.length === 3) {
                sec = parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
            } else if (parts.length === 2) {
                sec = parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
            }
        } else {
            sec = parseFloat(str);
        }
        if (!isNaN(sec) && sec >= 0) {
            if (window.__reviewerInstance && window.__reviewerInstance.seekAndCenter) {
                window.__reviewerInstance.seekAndCenter(sec);
            } else {
                const video = document.querySelector('.reviewer-video');
                if (video) {
                    video.currentTime = sec;
                }
            }
        }
    }
    """

    import_review_btn.click(
        import_review_srt,
        inputs=[review_srt_file, media, review_cues_state, undo_stack_state, redo_stack_state],
        outputs=[
            review_cues_state,
            review_table,
            review_payload,
            review_status,
            undo_stack_state,
            redo_stack_state,
            cue_edit_idx,
            cue_edit_start,
            cue_edit_end,
            cue_edit_text,
        ],
        api_name=False,
    ).then(
        None,
        inputs=cue_edit_start,
        outputs=None,
        js=seek_cue_js,
        api_name=False,
    )
    latest_as_base_btn.click(
        use_latest_as_review_base,
        inputs=[cues_state, media, review_cues_state, undo_stack_state, redo_stack_state],
        outputs=[review_cues_state, review_table, review_payload, review_status, undo_stack_state, redo_stack_state],
        api_name=False,
    )
    append_patch_btn.click(
        append_latest_patch,
        inputs=[review_cues_state, cues_state, media, undo_stack_state, redo_stack_state],
        outputs=[review_cues_state, review_table, review_payload, review_status, undo_stack_state, redo_stack_state],
        api_name=False,
    )
    export_review_btn.click(
        export_reviewed_srt,
        inputs=[review_cues_state, media],
        outputs=[reviewed_download, review_status],
        api_name=False,
    )

    review_table.select(
        on_select_review_row,
        inputs=[review_cues_state],
        outputs=[cue_edit_idx, cue_edit_start, cue_edit_end, cue_edit_text, review_status],
        api_name=False,
    )

    prev_cue_btn.click(
        navigate_review_cue_prev,
        inputs=[cue_edit_idx, review_cues_state],
        outputs=[cue_edit_idx, cue_edit_start, cue_edit_end, cue_edit_text, review_status],
        api_name=False,
    ).then(
        None,
        inputs=cue_edit_start,
        outputs=None,
        js=seek_cue_js,
        api_name=False,
    )

    next_cue_btn.click(
        navigate_review_cue_next,
        inputs=[cue_edit_idx, review_cues_state],
        outputs=[cue_edit_idx, cue_edit_start, cue_edit_end, cue_edit_text, review_status],
        api_name=False,
    ).then(
        None,
        inputs=cue_edit_start,
        outputs=None,
        js=seek_cue_js,
        api_name=False,
    )

    update_cue_btn.click(
        update_single_review_cue,
        inputs=[cue_edit_idx, cue_edit_start, cue_edit_end, cue_edit_text, review_cues_state, media, undo_stack_state, redo_stack_state],
        outputs=[review_cues_state, review_table, review_payload, review_status, undo_stack_state, redo_stack_state],
        api_name=False,
    )

    delete_cue_btn.click(
        delete_single_review_cue,
        inputs=[cue_edit_idx, review_cues_state, media, undo_stack_state, redo_stack_state],
        outputs=[
            review_cues_state,
            review_table,
            review_payload,
            review_status,
            cue_edit_idx,
            cue_edit_start,
            cue_edit_end,
            cue_edit_text,
            undo_stack_state,
            redo_stack_state,
        ],
        api_name=False,
    )

    undo_cue_btn.click(
        undo_review_action,
        inputs=[undo_stack_state, redo_stack_state, review_cues_state, media],
        outputs=[
            review_cues_state,
            review_table,
            review_payload,
            review_status,
            undo_stack_state,
            redo_stack_state,
            cue_edit_idx,
            cue_edit_start,
            cue_edit_end,
            cue_edit_text,
        ],
        api_name=False,
    )

    redo_cue_btn.click(
        redo_review_action,
        inputs=[undo_stack_state, redo_stack_state, review_cues_state, media],
        outputs=[
            review_cues_state,
            review_table,
            review_payload,
            review_status,
            undo_stack_state,
            redo_stack_state,
            cue_edit_idx,
            cue_edit_start,
            cue_edit_end,
            cue_edit_text,
        ],
        api_name=False,
    )

    insert_cue_btn.click(
        insert_new_review_cue,
        inputs=[cue_edit_start, cue_edit_end, cue_edit_text, review_cues_state, media, undo_stack_state, redo_stack_state],
        outputs=[review_cues_state, review_table, review_payload, review_status, undo_stack_state, redo_stack_state],
        api_name=False,
    )

    apply_table_btn.click(
        apply_table_edits,
        inputs=[review_table, media, review_cues_state, undo_stack_state, redo_stack_state],
        outputs=[review_cues_state, review_table, review_payload, review_status, undo_stack_state, redo_stack_state],
        api_name=False,
    )

    clean_review_btn.click(
        clean_review_cues,
        inputs=[review_cues_state, media, undo_stack_state, redo_stack_state],
        outputs=[review_cues_state, review_table, review_payload, review_status, undo_stack_state, redo_stack_state],
        api_name=False,
    )

    clear_review_btn.click(
        clear_all_review_cues,
        inputs=[media, review_cues_state, undo_stack_state, redo_stack_state],
        outputs=[review_cues_state, review_table, review_payload, review_status, undo_stack_state, redo_stack_state],
        api_name=False,
    )

    play_cue_js = """
    (startTimeStr) => {
        const video = document.querySelector('.reviewer-video');
        if (!video || !startTimeStr) return;
        let sec = 0;
        const str = String(startTimeStr).trim();
        if (str.includes(':')) {
            const parts = str.replace(',', '.').split(':');
            if (parts.length === 3) {
                sec = parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
            } else if (parts.length === 2) {
                sec = parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
            }
        } else {
            sec = parseFloat(str);
        }
        if (!isNaN(sec) && sec >= 0) {
            video.currentTime = sec;
            video.play();
        }
    }
    """
    play_cue_btn.click(
        None,
        inputs=cue_edit_start,
        outputs=None,
        js=play_cue_js,
        api_name=False,
    )

    copy_single_cue_js = """
    (startStr, endStr, textStr) => {
        const s = (startStr || '').trim();
        const e = (endStr || '').trim();
        const t = (textStr || '').trim();
        if (!t) {
            alert('当前字幕文本内容为空，无法复制。');
            return;
        }
        // 按照要求拼接格式："00:25:17,085","00:25:18,645",字幕文本
        const formatted = `"${s}","${e}",${t}`;

        const copyToClipboard = (text) => {
            if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
                return navigator.clipboard.writeText(text);
            }
            return new Promise((resolve, reject) => {
                try {
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    ta.style.position = 'fixed';
                    ta.style.opacity = '0';
                    document.body.appendChild(ta);
                    ta.focus();
                    ta.select();
                    const ok = document.execCommand('copy');
                    document.body.removeChild(ta);
                    if (ok) resolve(); else reject();
                } catch (err) {
                    reject(err);
                }
            });
        };

        copyToClipboard(formatted).then(() => {
            const btn = document.querySelector('#btn-copy-cue button') || document.getElementById('btn-copy-cue');
            if (btn) {
                const oldText = btn.textContent;
                btn.textContent = '✅ 已复制！';
                setTimeout(() => { btn.textContent = oldText; }, 1500);
            }
        }).catch(() => {
            prompt('自动复制权限受限，请按 Ctrl+C / Cmd+C 手动复制以下内容：', formatted);
        });
    }
    """
    copy_cue_btn.click(
        None,
        inputs=[cue_edit_start, cue_edit_end, cue_edit_text],
        outputs=None,
        js=copy_single_cue_js,
        api_name=False,
    )

    engine_name.change(
        lambda name: (
            gr.Group(visible=not name.startswith("Qwen3")),
            gr.Group(visible=name.startswith("Qwen3")),
        ),
        inputs=engine_name,
        outputs=[whisper_params, qwen_params],
        api_name=False,
    )

    for comp in PARAM_COMPONENTS:
        comp.change(
            render_active_params_banner,
            inputs=[engine_name, *PARAM_COMPONENTS],
            outputs=active_params_display,
            api_name=False,
        )
    engine_name.change(
        render_active_params_banner,
        inputs=[engine_name, *PARAM_COMPONENTS],
        outputs=active_params_display,
        api_name=False,
    )

    save_btn.click(
        save_preset,
        inputs=[preset_name, engine_name, *PARAM_COMPONENTS],
        outputs=[preset_pick, active_params_display],
        api_name=False,
    )
    load_btn.click(
        load_preset,
        inputs=preset_pick,
        outputs=[engine_name, *PARAM_COMPONENTS, preset_pick, active_params_display, whisper_params, qwen_params],
        api_name=False,
    )
    delete_btn.click(
        delete_preset,
        inputs=preset_pick,
        outputs=preset_pick,
        api_name=False,
    )
    reset_btn.click(
        reset_params,
        inputs=engine_name,
        outputs=[*PARAM_COMPONENTS, preset_pick, active_params_display],
        api_name=False,
    )
    preset_pick.change(pick_fills_name, inputs=preset_pick, outputs=preset_name, api_name=False)

    set_transcribing_start_js = "() => { window.__isTranscribing = true; }"
    set_transcribing_end_js = "() => { window.__isTranscribing = false; }"

    stop_btn.click(
        trigger_cancel,
        inputs=None,
        outputs=None,
        queue=False,
        api_name=False,
    ).then(
        lambda: gr.update(interactive=False, variant="secondary"),
        inputs=None,
        outputs=stop_btn,
        js=set_transcribing_end_js,
        queue=False,
        api_name=False,
    )

    run_btn.click(
        lambda: (
            gr.update(interactive=False),
            gr.update(interactive=True, variant="stop"),
            "⏳ 正在启动转写任务，准备音轨中…",
        ),
        inputs=None,
        outputs=[run_btn, stop_btn, transcribe_progress],
        js=set_transcribing_start_js,
        api_name=False,
    ).then(
        transcribe_media,
        inputs=[
            media,
            engine_name,
            output_format,
            save_beside,
            start_time_input,
            end_time_input,
            keep_timeline_chk,
            *PARAM_COMPONENTS,
        ],
        outputs=[cue_table, preview, download, saved_path, cues_state, status, report_box, transcribe_progress],
        show_progress="full",
        api_name=False,
    ).then(
        lambda: (
            gr.update(interactive=True),
            gr.update(interactive=False, variant="secondary"),
            gr.update(interactive=True),
        ),
        inputs=None,
        outputs=[run_btn, stop_btn, clean_btn],
        js=set_transcribing_end_js,
        api_name=False,
    )

    clean_btn.click(
        clean_ellipsis_subtitles,
        inputs=[cues_state, output_format, media, engine_name, save_beside],
        outputs=[cue_table, preview, download, saved_path, cues_state, clean_status],
        api_name=False,
    )

    # 详报面板是 HTML，纯文本原稿藏在 #report-raw-text 里，复制时直接读 DOM
    copy_js = """
    () => {
        const src = document.getElementById('report-raw-text');
        const text = src ? (src.textContent || '') : '';
        if (!text.trim()) {
            return '暂无转录详报内容可供复制。';
        }
        if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text);
            return '✅ 已成功将转录任务详报与全部参数复制到剪贴板！';
        }
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            return '✅ 已成功将转录任务详报与全部参数复制到剪贴板！';
        } catch (e) {
            return '复制失败，请手动选中面板内容复制。';
        }
    }
    """
    copy_report_btn.click(
        None,
        inputs=None,
        outputs=copy_status,
        js=copy_js,
        api_name=False,
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch(
        server_name="127.0.0.1",
        server_port=7860,
        inbrowser=True,
        show_error=True,
        max_file_size="10gb",
        allowed_paths=[str(ROOT.resolve()), str(Path(tempfile.gettempdir()).resolve())],
    )