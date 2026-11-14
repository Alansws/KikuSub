"""可调参数的规格表（无 UI 依赖）。

旧界面的参数面板是 22 个 `gr.Slider` / `gr.Checkbox` 堆出来的，标签、范围、
步长全散在 `app.py` 里。服务层与预设需要同一份定义，所以抽到这里：

- `GET /api/params` 直接把这张表吐给前端，由前端按 `kind` 渲染控件；
- 预设文件里的键（`whisper.vad_threshold` 之类）就是这里的 `key`，天然对齐；
- `config_kwargs()` 负责把界面上的键映射成引擎 dataclass 的字段名并转型。

**加参数时只改这个文件**，前端不用动（除非需要新的 `kind`）。
"""

from __future__ import annotations

from dataclasses import dataclass

WHISPER = "whisper"
QWEN = "qwen"
SENSEVOICE = "sensevoice"
FIRERED = "firered"

ENGINES = (WHISPER, QWEN, SENSEVOICE, FIRERED)


@dataclass(frozen=True, slots=True)
class ParamSpec:
    key: str  # 预设里用的键，形如 "whisper.vad_threshold"
    label: str  # 界面上的短标签
    engine: str
    kind: str  # bool | float | int
    default: bool | float | int
    group: str = "基础"
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    # 映射到引擎配置 dataclass 的字段；None 表示直接透传给 transcribe_file
    config_field: str | tuple[str, ...] | None = None
    help: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "engine": self.engine,
            "kind": self.kind,
            "default": self.default,
            "group": self.group,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "help": self.help,
            "is_config": self.config_field is not None,
        }


SPECS: tuple[ParamSpec, ...] = (
    # ---------------- Anime Whisper ----------------
    ParamSpec(
        "whisper.enable_sentence_split", "智能句级分切", WHISPER, "bool", True,
        group="基础", config_field="enable_sentence_split",
        help="按句法边界切分并平滑分配时间；关掉后按 VAD 段整段出字幕。",
    ),
    ParamSpec(
        "whisper.enable_loudnorm", "动态响度归一化", WHISPER, "bool", True,
        group="基础", config_field="enable_loudnorm",
        help="弱人声增强（dynaudnorm）。安静母带（整片峰值 < 0.1）不开会把大段台词识别成"
        "空段；实测开着能同时降低错字与漏句。",
    ),
    ParamSpec(
        "whisper.vad_threshold", "VAD 判定阈值", WHISPER, "float", 0.25,
        group="VAD", minimum=0.05, maximum=0.80, step=0.01, config_field="threshold",
        help="调小对耳语更灵敏；调大抗噪更强、能过滤背景音乐。VAD 已改成分窗检测，"
        "不再需要靠抬高阈值来压住误检。",
    ),
    ParamSpec(
        "whisper.vad_speech_pad_ms", "首尾留白 (ms)", WHISPER, "int", 250,
        group="VAD", minimum=0, maximum=400, step=10, config_field="speech_pad_ms",
        help="调大防吞头音（耳语的开头很容易被判成静音）；副作用是句尾喘气会被一起送模，"
        "已由「句首尾非台词发声自动剔除」兜底。",
    ),
    ParamSpec(
        "whisper.vad_onset_pad_ms", "句首提前 (ms)", WHISPER, "int", 0,
        group="VAD", minimum=0, maximum=600, step=20, config_field="onset_pad_ms",
        help="把 VAD 段起点整体向左扩。Silero 的起点系统性晚于真实发声，"
        "被吞的常是「す / そ / え」这类轻声起音的句首；0 = 关闭（与旧行为一致）。"
        "不调阈值：调低会换来更多强制切分与音乐误检。",
    ),
    ParamSpec(
        "whisper.vad_min_silence_ms", "判定停顿静音 (ms)", WHISPER, "int", 200,
        group="VAD", minimum=50, maximum=600, step=10, config_field="min_silence_ms",
        help="调小会频繁切成短句；调大连贯保留长句。",
    ),
    ParamSpec(
        "whisper.vad_min_speech_ms", "最短语音 (ms)", WHISPER, "int", 80,
        group="VAD", minimum=0, maximum=500, step=10, config_field="min_speech_ms",
        help="调小可捕获「ほら」这类半秒短句（它们单独送模常被判空，靠合并间隔并到下一句）；"
        "调大过滤短促爆音。",
    ),
    ParamSpec(
        "whisper.vad_merge_gap_s", "片段合并间隔 (s)", WHISPER, "float", 0.30,
        group="VAD", minimum=0.0, maximum=2.0, step=0.05, config_field="merge_gap_s",
        help="调大让相邻对话合并；调小严格按停顿分段。留白已经给到 250ms，"
        "合并间隔再放大在正常对话片上会把两句并进一个块，块准确率反而降。",
    ),
    ParamSpec(
        "whisper.vad_max_segment_s", "单次送模最长 (s)", WHISPER, "float", 9.0,
        group="VAD", minimum=5.0, maximum=28.0, step=1.0, config_field="max_segment_s",
        help="调小识别快且极少幻觉；调大上下文更连贯。9s 是长片回归后取的折中："
        "再大就会把两轮对话糊进同一块，字幕块准确率下降。",
    ),
    ParamSpec(
        "whisper.vad_min_speech_s", "合并后最短片段 (s)", WHISPER, "float", 0.08,
        group="VAD", minimum=0.0, maximum=0.5, step=0.01, config_field="min_speech_s",
        help="过滤合并后仍然过短的碎片音频。",
    ),
    ParamSpec(
        "whisper.cue_pad_s", "字幕外扩留白 (s)", WHISPER, "float", 0.02,
        group="字幕", minimum=0.0, maximum=0.3, step=0.01, config_field="cue_pad_s",
        help="调大让字幕提前出现、滞后消失，观影更舒适。",
    ),
    ParamSpec(
        "whisper.strip_nonverbal_edges", "剔除句首尾喘气/笑声", WHISPER, "bool", True,
        group="字幕", config_field="strip_nonverbal_edges",
        help="模型会如实转写「んふふ」「えへへ」这类非台词发声，它们几乎不该进字幕。"
        "开着只删句首尾、句中不动；整条只剩促音/长音符的碎片也不会占一条字幕。"
        "动画里角色的笑声算内容时，关掉即可原样保留。",
    ),
    ParamSpec(
        "whisper.use_ctc_alignment", "CTC 逐字对齐（借 Qwen 对齐头）", WHISPER, "bool", False,
        group="字幕", config_field="use_ctc_alignment",
        help="Anime Whisper 自己的时间靠字符比例猜，起点误差 p90 约 1.2s。打开后借用 Qwen "
        "引擎的 CTC 对齐头（要先装好 Qwen3-ASR 权重）拿逐字时间，切点落在真实发声上。"
        "代价是多常驻一份 Qwen 权重（实测峰值 5.1GB），低配机器别开。",
    ),
    ParamSpec(
        "whisper.no_repeat_ngram_size", "重复抑制 n-gram", WHISPER, "int", 5,
        group="重复抑制", minimum=0, maximum=10, step=1,
        help="强力杜绝自回归连续复读；0 为关闭。",
    ),
    ParamSpec(
        "whisper.repetition_penalty", "重复惩罚因子", WHISPER, "float", 1.15,
        group="重复抑制", minimum=1.0, maximum=1.4, step=0.05,
        help="推荐 1.10–1.20。过高会让输出变得生硬。",
    ),
    # ---------------- Qwen3-ASR ----------------
    ParamSpec(
        "qwen.enable_loudnorm", "动态响度归一化", QWEN, "bool", True,
        group="基础", config_field="enable_loudnorm",
        help="弱人声强化。",
    ),
    ParamSpec(
        "qwen.use_alignment", "逐字 CTC 对齐", QWEN, "bool", True,
        group="基础",
        help="用 CTC 头取逐字发声帧，句内时间精确到 ~40ms。关掉则按字数比例分配。",
    ),
    ParamSpec(
        "qwen.vad_threshold", "VAD 判定阈值", QWEN, "float", 0.30,
        group="VAD", minimum=0.05, maximum=0.80, step=0.01, config_field="vad_threshold",
        help="调小对低声耳语极灵敏；调大抗噪更强。",
    ),
    # 这两个旧界面没暴露，但 dataclass 里有、预设文件里也在用——
    # 补上之后「预设里的键必须都能在规格表找到」这条测试才成立。
    ParamSpec(
        "qwen.vad_min_speech_ms", "最短语音 (ms)", QWEN, "int", 100,
        group="VAD", minimum=0, maximum=500, step=10, config_field="vad_min_speech_ms",
        help="调小可捕获短叹词；调大过滤短促爆音。",
    ),
    ParamSpec(
        "qwen.vad_min_silence_ms", "判定停顿静音 (ms)", QWEN, "int", 200,
        group="VAD", minimum=50, maximum=600, step=10, config_field="vad_min_silence_ms",
        help="调小会频繁切成短句；调大连贯保留长句。",
    ),
    ParamSpec(
        "qwen.vad_speech_pad_ms", "首尾留白 (ms)", QWEN, "int", 250,
        group="VAD", minimum=0, maximum=400, step=10, config_field="vad_speech_pad_ms",
        help="调大防止句首辅音或句尾被切断。耳语片句首常被削掉半个词，250ms 与 Whisper 侧一致。",
    ),
    ParamSpec(
        "qwen.vad_onset_pad_ms", "句首提前 (ms)", QWEN, "int", 400,
        group="VAD", minimum=0, maximum=600, step=20, config_field="vad_onset_pad_ms",
        help="把 VAD 段起点整体向左扩，救回被吞的句首。默认 400 ms 来自 2026-11-13 的 A/B"
        "（Test 二 CER −1.95pt、句首缺字 −80%；Test 一 −0.75pt；长片不劣化）。"
        "0 = 回到旧行为。与 Whisper 侧同一条实现（transcribe.extend_segment_onsets）。",
    ),
    ParamSpec(
        "qwen.merge_gap_s", "合并间隔 (s)", QWEN, "float", 0.50,
        group="VAD", minimum=0.1, maximum=1.5, step=0.05, config_field="merge_gap_s",
        help="调大把相邻语音段合并成连贯大段送模。",
    ),
    ParamSpec(
        "qwen.max_segment_s", "送模音频窗口 (s)", QWEN, "float", 12.0,
        group="VAD", minimum=10.0, maximum=25.0, step=1.0, config_field="max_segment_s",
        help="10–14 秒是 Qwen 的平衡区间：再大就会把两三句合并送模，模型开始复读。",
    ),
    ParamSpec(
        "qwen.min_pause_s", "断句停顿静音 (s)", QWEN, "float", 0.12,
        group="断句与字幕", minimum=0.04, maximum=0.40, step=0.01, config_field="min_pause_s",
        help="调小更易断句；调大只在明显停顿处断句。",
    ),
    ParamSpec(
        "qwen.max_cue_dur", "单条目标时长 (s)", QWEN, "float", 4.30,
        group="断句与字幕", minimum=2.0, maximum=8.0, step=0.1, config_field="max_cue_dur",
        help="调小字幕切换紧凑；调大长句整体展示。",
    ),
    ParamSpec(
        "qwen.max_cue_chars", "单条最多字数", QWEN, "int", 21,
        group="断句与字幕", minimum=8, maximum=35, step=1, config_field="max_cue_chars",
        help="超出后按日语助词边界平滑折断。",
    ),
    # 起点与终点分开：人工核验版的惯例是「提前 0.2s 出现、句尾多停 0.45s」，
    # 用一个共用滑杆只能取折中，实测起点中位偏差会从 +0.03s 掉到 +0.11s。
    ParamSpec(
        "qwen.cue_pad_start_s", "字幕提前量 (s)", QWEN, "float", 0.20,
        group="断句与字幕", minimum=0.0, maximum=0.40, step=0.01,
        config_field="cue_pad_start_s",
        help="字幕比发声提前多少秒出现。0.2s 与人工核验版一致。",
    ),
    ParamSpec(
        "qwen.cue_pad_end_s", "字幕停留 (s)", QWEN, "float", 0.45,
        group="断句与字幕", minimum=0.0, maximum=0.80, step=0.01,
        config_field="cue_pad_end_s",
        help="最后一个字发声完再停留多久才消失。0.45s 与人工核验版一致；"
        "调小字幕切换更利落，调大留阅读余量（遇到下一条会截断）。",
    ),
    ParamSpec(
        "qwen.strip_nonverbal_edges", "剔除句首尾喘气/笑声", QWEN, "bool", True,
        group="断句与字幕", config_field="strip_nonverbal_edges",
        help="模型会如实转写「んふふ」「えへへ」这类非台词发声，人工整理版通常不留。"
        "开着只删句首尾、句中不动，并在对齐前就剔掉——字幕起点直接落在第一个真字上。"
        "动画里角色的笑声算内容时，关掉即可原样保留。",
    ),
    # ---------------- 中文：SenseVoice-Small ----------------
    ParamSpec(
        "sensevoice.enable_loudnorm", "动态响度归一化", SENSEVOICE, "bool", True,
        group="基础", config_field="enable_loudnorm",
        help="弱人声增强；会多花一次 ffmpeg 解码。",
    ),
    ParamSpec(
        "sensevoice.use_itn", "标点与数字归一化", SENSEVOICE, "bool", True,
        group="基础", config_field="use_itn",
        help="打开后输出带标点、数字转阿拉伯写法；关闭则是一串无标点的字。",
    ),
    ParamSpec(
        "sensevoice.num_threads", "CPU 线程数", SENSEVOICE, "int", 2,
        group="基础", minimum=1, maximum=8, step=1, config_field="num_threads",
        help="2–4 在 Apple Silicon 上性价比最高，再高收益递减。",
    ),
    ParamSpec(
        "sensevoice.vad_threshold", "VAD 判定阈值", SENSEVOICE, "float", 0.30,
        group="VAD", minimum=0.05, maximum=0.80, step=0.01, config_field="vad_threshold",
        help="调小对低声耳语更灵敏；调大抗噪更强。",
    ),
    ParamSpec(
        "sensevoice.vad_min_speech_ms", "最短语音 (ms)", SENSEVOICE, "int", 100,
        group="VAD", minimum=0, maximum=500, step=10, config_field="vad_min_speech_ms",
        help="调小可捕获短叹词；调大过滤短促爆音。",
    ),
    ParamSpec(
        "sensevoice.vad_min_silence_ms", "判定停顿静音 (ms)", SENSEVOICE, "int", 200,
        group="VAD", minimum=50, maximum=600, step=10, config_field="vad_min_silence_ms",
        help="调小会频繁切成短句；调大连贯保留长句。",
    ),
    ParamSpec(
        "sensevoice.vad_speech_pad_ms", "首尾留白 (ms)", SENSEVOICE, "int", 150,
        group="VAD", minimum=0, maximum=400, step=10, config_field="vad_speech_pad_ms",
        help="调大防止句首辅音或句尾被切断。耳语片句首常被削掉半个词，250ms 与 Whisper 侧一致。",
    ),
    ParamSpec(
        "sensevoice.merge_gap_s", "合并间隔 (s)", SENSEVOICE, "float", 0.50,
        group="VAD", minimum=0.1, maximum=1.5, step=0.05, config_field="merge_gap_s",
        help="调大把相邻语音段合并成连贯大段送模。",
    ),
    ParamSpec(
        "sensevoice.max_segment_s", "送模音频窗口 (s)", SENSEVOICE, "float", 16.0,
        group="VAD", minimum=5.0, maximum=25.0, step=1.0, config_field="max_segment_s",
        help="SenseVoice 适合 10–20 秒窗口；太长会明显变慢。",
    ),
    ParamSpec(
        "sensevoice.min_pause_s", "断句停顿 (s)", SENSEVOICE, "float", 0.20,
        group="断句与字幕", minimum=0.05, maximum=0.60, step=0.01, config_field="min_pause_s",
        help="无标点时靠它判断「这里可以换一条字幕」。",
    ),
    ParamSpec(
        "sensevoice.max_cue_dur", "单条目标时长 (s)", SENSEVOICE, "float", 4.3,
        group="断句与字幕", minimum=2.0, maximum=8.0, step=0.1, config_field="max_cue_dur",
        help="调小字幕切换紧凑；调大长句整体展示。",
    ),
    ParamSpec(
        "sensevoice.max_cue_chars", "单条最多字数", SENSEVOICE, "int", 18,
        group="断句与字幕", minimum=8, maximum=35, step=1, config_field="max_cue_chars",
        help="中文两行字幕通常 14–20 字；超出会按标点或停顿平滑折断。",
    ),
    ParamSpec(
        "sensevoice.cue_pad_s", "字幕前后留白 (s)", SENSEVOICE, "float", 0.10,
        group="断句与字幕", minimum=0.0, maximum=0.30, step=0.01, config_field="cue_pad_s",
        help="字幕在画面上停留的舒适缓冲。",
    ),
    # ---------------- 中文：FireRedASR2-AED ----------------
    # 与 SenseVoice 同一套配置 dataclass 字段，只是不做 ITN/语种选择（模型不支持）。
    ParamSpec(
        "firered.enable_loudnorm", "动态响度归一化", FIRERED, "bool", True,
        group="基础", config_field="enable_loudnorm",
        help="弱人声增强；会多花一次 ffmpeg 解码。",
    ),
    ParamSpec(
        "firered.use_punc", "标点恢复 (FireRedPunc)", FIRERED, "bool", True,
        group="基础", config_field="use_punc",
        help="FireRed 的原始输出没有标点；开启后用 FireRedPunc 在切字幕前补齐句读。"
        "首次启用会在下载引擎时一并下载标点模型（约 160 MB）。",
    ),
    ParamSpec(
        "firered.num_threads", "CPU 线程数", FIRERED, "int", 2,
        group="基础", minimum=1, maximum=8, step=1, config_field="num_threads",
        help="2–4 在 Apple Silicon 上性价比最高；AED 解码比轻量模型慢约 5 倍。",
    ),
    ParamSpec(
        "firered.vad_threshold", "VAD 判定阈值", FIRERED, "float", 0.30,
        group="VAD", minimum=0.05, maximum=0.80, step=0.01, config_field="vad_threshold",
        help="调小对低声耳语更灵敏；调大抗噪更强。",
    ),
    ParamSpec(
        "firered.vad_min_speech_ms", "最短语音 (ms)", FIRERED, "int", 100,
        group="VAD", minimum=0, maximum=500, step=10, config_field="vad_min_speech_ms",
        help="调小可捕获短叹词；调大过滤短促爆音。",
    ),
    ParamSpec(
        "firered.vad_min_silence_ms", "判定停顿静音 (ms)", FIRERED, "int", 200,
        group="VAD", minimum=50, maximum=600, step=10, config_field="vad_min_silence_ms",
        help="调小会频繁切成短句；调大连贯保留长句。",
    ),
    ParamSpec(
        "firered.vad_speech_pad_ms", "首尾留白 (ms)", FIRERED, "int", 150,
        group="VAD", minimum=0, maximum=400, step=10, config_field="vad_speech_pad_ms",
        help="调大防止句首辅音或句尾被切断。耳语片句首常被削掉半个词，250ms 与 Whisper 侧一致。",
    ),
    ParamSpec(
        "firered.merge_gap_s", "合并间隔 (s)", FIRERED, "float", 0.35,
        group="VAD", minimum=0.1, maximum=1.5, step=0.05, config_field="merge_gap_s",
        help="该模型不输出逐字时间戳；合并得短一些，字幕时间轴更贴停顿。",
    ),
    ParamSpec(
        "firered.max_segment_s", "送模音频窗口 (s)", FIRERED, "float", 14.0,
        group="VAD", minimum=5.0, maximum=25.0, step=1.0, config_field="max_segment_s",
        help="窗口越短、按字分时越准，但上下文更碎。",
    ),
    ParamSpec(
        "firered.min_pause_s", "断句停顿 (s)", FIRERED, "float", 0.24,
        group="断句与字幕", minimum=0.05, maximum=0.60, step=0.01, config_field="min_pause_s",
        help="无标点时靠它判断「这里可以换一条字幕」。",
    ),
    ParamSpec(
        "firered.max_cue_dur", "单条目标时长 (s)", FIRERED, "float", 4.3,
        group="断句与字幕", minimum=2.0, maximum=8.0, step=0.1, config_field="max_cue_dur",
        help="调小字幕切换紧凑；调大长句整体展示。",
    ),
    ParamSpec(
        "firered.max_cue_chars", "单条最多字数", FIRERED, "int", 18,
        group="断句与字幕", minimum=8, maximum=35, step=1, config_field="max_cue_chars",
        help="中文两行字幕通常 14–20 字；超出会按停顿平滑折断。",
    ),
    ParamSpec(
        "firered.cue_pad_s", "字幕前后留白 (s)", FIRERED, "float", 0.10,
        group="断句与字幕", minimum=0.0, maximum=0.30, step=0.01, config_field="cue_pad_s",
        help="字幕在画面上停留的舒适缓冲。",
    ),
)

BY_KEY: dict[str, ParamSpec] = {spec.key: spec for spec in SPECS}


def specs_for(engine: str) -> list[ParamSpec]:
    return [spec for spec in SPECS if spec.engine == engine]


def grouped(engine: str) -> list[dict]:
    """按 group 分组，供前端直接渲染成「基础 / VAD / 字幕…」几块。"""
    order: list[str] = []
    buckets: dict[str, list[ParamSpec]] = {}
    for spec in specs_for(engine):
        if spec.group not in buckets:
            buckets[spec.group] = []
            order.append(spec.group)
        buckets[spec.group].append(spec)
    return [{"group": name, "params": [s.to_dict() for s in buckets[name]]} for name in order]


def defaults_for(engine: str) -> dict:
    return {spec.key: spec.default for spec in specs_for(engine)}


def all_defaults() -> dict:
    return {spec.key: spec.default for spec in SPECS}


def coerce(spec: ParamSpec, raw) -> bool | float | int:
    if spec.kind == "bool":
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
    if spec.kind == "int":
        value = int(round(float(raw)))
    else:
        value = float(raw)
    if spec.minimum is not None:
        value = max(spec.minimum, value)
    if spec.maximum is not None:
        value = min(spec.maximum, value)
    return value


# 旧键 → 新键。改参数口径时旧预设不能失效：用户在 presets.json 里存的
# `qwen.cue_pad_s`（起点/终点共用一个留白）已拆成两个键，这里负责补上。
LEGACY_KEYS: dict[str, tuple[str, ...]] = {
    "qwen.cue_pad_s": ("qwen.cue_pad_start_s", "qwen.cue_pad_end_s"),
}


def normalize(engine: str, values: dict | None) -> dict:
    """把外部传进来的参数收敛成「该引擎的完整取值」。

    缺失的键补默认值，越界的值夹到区间内，多余的键丢掉；旧键按 LEGACY_KEYS 展开。
    """
    out = defaults_for(engine)
    expanded = dict(values or {})
    for legacy, targets in LEGACY_KEYS.items():
        if legacy in expanded:
            value = expanded.pop(legacy)
            for target in targets:
                expanded.setdefault(target, value)
    for key, raw in expanded.items():
        spec = BY_KEY.get(key)
        if spec is None or spec.engine != engine:
            continue
        try:
            out[key] = coerce(spec, raw)
        except (TypeError, ValueError):
            continue
    return out


def config_kwargs(engine: str, values: dict | None) -> dict:
    """映射成引擎配置 dataclass 的关键字参数。"""
    resolved = normalize(engine, values)
    kwargs: dict = {}
    for spec in specs_for(engine):
        if spec.config_field is None:
            continue
        kwargs[spec.config_field] = resolved[spec.key]
    return kwargs


def passthrough_kwargs(engine: str, values: dict | None) -> dict:
    """不落在 dataclass 上、直接传给 `transcribe_file` 的参数。"""
    resolved = normalize(engine, values)
    return {
        spec.key.split(".", 1)[1]: resolved[spec.key]
        for spec in specs_for(engine)
        if spec.config_field is None
    }


def schema() -> dict:
    """`GET /api/params` 的返回体。"""
    return {
        "engines": [
            {"key": engine, "groups": grouped(engine), "defaults": defaults_for(engine)}
            for engine in ENGINES
        ]
    }
