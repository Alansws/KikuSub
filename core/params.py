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

ENGINES = (WHISPER, QWEN)


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
        "whisper.enable_loudnorm", "动态响度归一化", WHISPER, "bool", False,
        group="基础", config_field="enable_loudnorm",
        help="弱人声增强。耳语、远景对话建议开启。",
    ),
    ParamSpec(
        "whisper.vad_threshold", "VAD 判定阈值", WHISPER, "float", 0.30,
        group="VAD", minimum=0.05, maximum=0.80, step=0.01, config_field="threshold",
        help="调小对耳语更灵敏；调大抗噪更强，能过滤背景音乐。",
    ),
    ParamSpec(
        "whisper.vad_speech_pad_ms", "首尾留白 (ms)", WHISPER, "int", 200,
        group="VAD", minimum=0, maximum=400, step=10, config_field="speech_pad_ms",
        help="调大防吞头尾音与呼吸声；调小切除无效空白。",
    ),
    ParamSpec(
        "whisper.vad_min_silence_ms", "判定停顿静音 (ms)", WHISPER, "int", 150,
        group="VAD", minimum=50, maximum=600, step=10, config_field="min_silence_ms",
        help="调小会频繁切成短句；调大连贯保留长句。",
    ),
    ParamSpec(
        "whisper.vad_min_speech_ms", "最短语音 (ms)", WHISPER, "int", 120,
        group="VAD", minimum=0, maximum=500, step=10, config_field="min_speech_ms",
        help="调小可捕获短叹词；调大过滤短促爆音。",
    ),
    ParamSpec(
        "whisper.vad_merge_gap_s", "片段合并间隔 (s)", WHISPER, "float", 0.30,
        group="VAD", minimum=0.0, maximum=2.0, step=0.05, config_field="merge_gap_s",
        help="调大让相邻对话合并；调小严格按停顿分段。",
    ),
    ParamSpec(
        "whisper.vad_max_segment_s", "单次送模最长 (s)", WHISPER, "float", 12.0,
        group="VAD", minimum=5.0, maximum=28.0, step=1.0, config_field="max_segment_s",
        help="调小识别快且极少幻觉；调大上下文更连贯。",
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
        "qwen.vad_speech_pad_ms", "首尾留白 (ms)", QWEN, "int", 150,
        group="VAD", minimum=0, maximum=400, step=10, config_field="vad_speech_pad_ms",
        help="调大防止句首辅音或句尾被切断。",
    ),
    ParamSpec(
        "qwen.merge_gap_s", "合并间隔 (s)", QWEN, "float", 0.50,
        group="VAD", minimum=0.1, maximum=1.5, step=0.05, config_field="merge_gap_s",
        help="调大把相邻语音段合并成连贯大段送模。",
    ),
    ParamSpec(
        "qwen.max_segment_s", "送模音频窗口 (s)", QWEN, "float", 16.0,
        group="VAD", minimum=10.0, maximum=25.0, step=1.0, config_field="max_segment_s",
        help="12–18 秒是 Qwen 识别与 CTC 对齐的最佳平衡区间。",
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
    ParamSpec(
        "qwen.cue_pad_s", "字幕前后留白 (s)", QWEN, "float", 0.12,
        group="断句与字幕", minimum=0.0, maximum=0.30, step=0.01,
        config_field=("cue_pad_start_s", "cue_pad_end_s"),
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


def normalize(engine: str, values: dict | None) -> dict:
    """把外部传进来的参数收敛成「该引擎的完整取值」。

    缺失的键补默认值，越界的值夹到区间内，多余的键丢掉。
    """
    out = defaults_for(engine)
    for key, raw in (values or {}).items():
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
        value = resolved[spec.key]
        if isinstance(spec.config_field, tuple):
            for field_name in spec.config_field:
                kwargs[field_name] = value
        else:
            kwargs[spec.config_field] = value
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
