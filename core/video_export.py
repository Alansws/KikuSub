"""成片导出：把当前时间轴烧进画面，或封装成软字幕。

为什么不是简单调用 ffmpeg 的 ``subtitles`` / ``ass`` 滤镜：Homebrew 的 ffmpeg
默认不带 libass/freetype，这两个滤镜经常直接不存在（本项目实测的 9.0.2 就没有）。
所以这里的硬字幕走一条**不依赖 libass** 的路线：

1. 用 Pillow 把每批字幕画成一张透明 PNG 长条（第 0 块是空白，后面每块一句）；
2. ffmpeg 只把这张 PNG 当输入，用 ``crop`` 的 ``y`` 表达式按时间切出当前这一块，
   再用 **一个** ``overlay`` 叠到画面上；
3. 每批最多几十到一百多句，避免单张精灵图过大；每批一个 overlay，滤镜图仍然很短。

这条路线在 macOS 自带的 Python/Pillow 上就能跑，不要求用户额外安装 ffmpeg 变体。
软字幕模式则直接封装 ``mov_text``（MP4）或 ``srt``（MKV），可以做到不重编码。
"""

from __future__ import annotations

import io
import queue
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .i18n import bilingual_cues, bilingual_entries, target_cues
from .procutil import (
    CommandCancelled,
    CommandTimeout,
    SPAWN_LOCK,
    is_shutting_down,
    register_process,
    run_command,
    tail,
    terminate_process,
    unregister_process,
)
from .subtitles import SubtitleCue, cues_to_srt

# --------------------------------------------------------------------------- 预设

RESOLUTIONS: dict[str, int] = {
    "source": 0,
    "2160p": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}

PRESETS: dict[str, dict] = {
    "small": {
        "label": "小",
        "factor": 0.55,
        "crf": 25,
        "hint": "文件最小，适合发群/传网盘；细节会有可接受的损失。",
    },
    "balanced": {
        "label": "甜点",
        "factor": 1.0,
        "crf": 21,
        "hint": "速度、画质、体积的平衡点，绝大多数场景直接选它。",
    },
    "high": {
        "label": "高",
        "factor": 1.6,
        "crf": 18,
        "hint": "保留更多纹理与暗部细节，文件明显变大。",
    },
    "ultra": {
        "label": "极高",
        "factor": 2.4,
        "crf": 15,
        "hint": "接近源画质的收藏档；编码更慢、文件最大。",
    },
}

MODES = {"burn", "soft", "copy"}

# 码率基准（H.264 1080p 甜点约 4.5 Mbps）。按输出高度取最近档。
_BITRATE_LADDER = (
    (480, 1_200_000),
    (720, 2_500_000),
    (1080, 4_500_000),
    (1440, 8_000_000),
    (2160, 14_000_000),
)

# --------------------------------------------------------------------------- 字幕样式

# 组标/汉化组常见的本机字体。macOS 把 PingFang / 兰亭黑 / 圆体这类字体放在
# `/System/Library/AssetsV2/com_apple_MobileAsset_Font*` 下，目录名是随机 hash，
# 所以只能按文件名搜索，不能写死路径。
FONT_SEARCH_DIRS = (
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
)

WEIGHTS: dict[str, str] = {
    "regular": "常规",
    "medium": "中等",
    "bold": "粗体",
}


@dataclass(frozen=True, slots=True)
class FontFamily:
    key: str
    label: str
    hint: str
    files: tuple[str, ...]
    # 权重 -> (TTC 里的 family 名, style 名)。用名字而不是固定 index：
    # 不同 macOS 版本里 TTC 内的面顺序不保证一致。
    faces: dict[str, tuple[str, str]]


FONT_FAMILIES: tuple[FontFamily, ...] = (
    FontFamily(
        "pingfang",
        "苹方",
        "macOS 中文黑体，笔画干净；组标最通用的选择",
        ("PingFang.ttc",),
        {
            "regular": ("PingFang SC", "Regular"),
            "medium": ("PingFang SC", "Medium"),
            "bold": ("PingFang SC", "Semibold"),
        },
    ),
    FontFamily(
        "lantinghei",
        "兰亭黑",
        "方正兰亭黑风格，粗重有力，电影/番剧组标常用",
        ("Lantinghei.ttc",),
        {
            "regular": ("Lantinghei SC", "Demibold"),
            "medium": ("Lantinghei SC", "Demibold"),
            "bold": ("Lantinghei SC", "Heavy"),
        },
    ),
    FontFamily(
        "hiragino",
        "冬青黑",
        "Hiragino Sans GB，日系排版感强，W6 适合硬字幕",
        ("Hiragino Sans GB.ttc",),
        {
            "regular": ("Hiragino Sans GB", "W3"),
            "medium": ("Hiragino Sans GB", "W6"),
            "bold": ("Hiragino Sans GB", "W6"),
        },
    ),
    FontFamily(
        "heiti",
        "华文黑体",
        "经典 STHeiti，字形偏方，老番组标常见",
        ("STHeiti Medium.ttc", "STHEITI.ttf"),
        {
            "regular": ("Heiti SC", "Medium"),
            "medium": ("Heiti SC", "Medium"),
            "bold": ("Heiti SC", "Medium"),
        },
    ),
    FontFamily(
        "yuanti",
        "圆体",
        "圆润字形，适合轻喜剧、恋爱番",
        ("Yuanti.ttc",),
        {
            "regular": ("Yuanti SC", "Regular"),
            "medium": ("Yuanti SC", "Regular"),
            "bold": ("Yuanti SC", "Bold"),
        },
    ),
    FontFamily(
        "songti",
        "宋体",
        "衬线宋体，电影、正剧、旁白字幕用得多",
        ("Songti.ttc",),
        {
            "regular": ("Songti SC", "Regular"),
            "medium": ("Songti SC", "Regular"),
            "bold": ("Songti SC", "Bold"),
        },
    ),
    FontFamily(
        "biz-ud",
        "日式放送",
        "BIZ UDGothic，日本电视放送/字幕组常用的 UD 黑体",
        ("BIZ_UDGothic.ttc",),
        {
            "regular": ("BIZ UDGothic", "Regular"),
            "medium": ("BIZ UDGothic", "Regular"),
            "bold": ("BIZ UDGothic", "Bold"),
        },
    ),
    FontFamily(
        "tsukushi-maru",
        "筑紫丸黑",
        "Tsukushi B Round Gothic，圆黑字形，日式轻快风格",
        ("TsukushiBMaruGothic.ttc",),
        {
            "regular": ("Tsukushi B Round Gothic", "Regular"),
            "medium": ("Tsukushi B Round Gothic", "Bold"),
            "bold": ("Tsukushi B Round Gothic", "Bold"),
        },
    ),
)

_FONT_BY_KEY = {family.key: family for family in FONT_FAMILIES}

# 字号默认值：1080p 下约 58px（旧版 49px，用户反馈太细）。
FONT_BASE_RATIO = 0.054
# 描边宽度相对字号；旧版 0.055，现在默认更粗，接近组标观感。
OUTLINE_RATIO = 0.085
SHADOW_RATIO = 0.05

STYLE_RANGES = {
    "size": (0.7, 1.6),
    "outline": (0.0, 2.4),
    "margin": (1.0, 14.0),
}


@dataclass(slots=True)
class SubtitleStyle:
    """烧录硬字幕的样式。

    只影响 ``burn``：软字幕/仅封装把样式交给播放器，改了也没有效果。
    """

    preset: str = "fansub"
    font: str = "pingfang"
    weight: str = "bold"
    size: float = 1.0
    outline: float = 1.0
    shadow: bool = True
    position: str = "bottom"
    margin: float = 4.5
    fill: str = "#FFFFFF"
    outline_color: str = "#000000"

    def to_dict(self) -> dict:
        return {
            "preset": self.preset,
            "font": self.font,
            "weight": self.weight,
            "size": round(float(self.size), 3),
            "outline": round(float(self.outline), 3),
            "shadow": bool(self.shadow),
            "position": self.position,
            "margin": round(float(self.margin), 2),
            "fill": self.fill.upper(),
            "outline_color": self.outline_color.upper(),
        }

    @classmethod
    def from_mapping(cls, raw: dict | None) -> "SubtitleStyle":
        """从请求/预设构造样式；越界值夹紧而不是报错，避免前端滑块把导出卡死。"""
        data = dict(raw or {})
        style = cls()
        preset = str(data.get("preset") or "").strip()
        if preset:
            style.preset = preset
        font = str(data.get("font") or "").strip()
        if font:
            style.font = font
        weight = str(data.get("weight") or "").strip()
        if weight in WEIGHTS:
            style.weight = weight

        def number(key: str, default: float, low: float, high: float) -> float:
            try:
                value = float(data.get(key, default))
            except (TypeError, ValueError):
                return default
            return max(low, min(high, value))

        style.size = number("size", style.size, *STYLE_RANGES["size"])
        style.outline = number("outline", style.outline, *STYLE_RANGES["outline"])
        style.margin = number("margin", style.margin, *STYLE_RANGES["margin"])
        style.shadow = bool(data.get("shadow", style.shadow))
        position = str(data.get("position") or "").strip()
        if position in ("bottom", "top"):
            style.position = position
        fill = str(data.get("fill") or "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", fill):
            style.fill = fill.upper()
        outline_color = str(data.get("outline_color") or "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", outline_color):
            style.outline_color = outline_color.upper()
        return style

    def validate(self) -> None:
        if self.font not in _FONT_BY_KEY:
            raise ExportError(f"未知字幕字体：{self.font}")
        if self.weight not in WEIGHTS:
            raise ExportError(f"未知字重：{self.weight}")
        if self.position not in ("bottom", "top"):
            raise ExportError(f"未知字幕位置：{self.position}")
        low, high = STYLE_RANGES["size"]
        if not (low <= float(self.size) <= high):
            raise ExportError(f"字号倍率必须在 {low}–{high} 之间")
        low, high = STYLE_RANGES["outline"]
        if not (low <= float(self.outline) <= high):
            raise ExportError(f"描边倍率必须在 {low}–{high} 之间")
        low, high = STYLE_RANGES["margin"]
        if not (low <= float(self.margin) <= high):
            raise ExportError(f"底边距离必须在 {low}–{high}% 之间")
        for key in ("fill", "outline_color"):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", getattr(self, key)):
                raise ExportError(f"{key} 必须是 #RRGGBB 颜色")


# 内置样式：按「一看就知道该选哪个」命名，不堆砌参数。
STYLE_PRESETS: dict[str, dict] = {
    "fansub": {
        "label": "组标标准",
        "hint": "苹方粗体＋白字黑边，通用性最好；默认选它。",
        "font": "pingfang",
        "weight": "bold",
        "size": 1.0,
        "outline": 1.0,
        "shadow": True,
        "position": "bottom",
        "margin": 4.5,
        "fill": "#FFFFFF",
        "outline_color": "#000000",
    },
    "fansub-heavy": {
        "label": "粗黑重边",
        "hint": "兰亭黑重字重＋更粗描边，远景/动作片也压得住。",
        "font": "lantinghei",
        "weight": "bold",
        "size": 1.02,
        "outline": 1.25,
        "shadow": True,
        "position": "bottom",
        "margin": 4.2,
        "fill": "#FFFFFF",
        "outline_color": "#000000",
    },
    "anime-round": {
        "label": "番剧圆体",
        "hint": "圆体粗体，气质轻快，适合动画/恋爱番。",
        "font": "yuanti",
        "weight": "bold",
        "size": 1.02,
        "outline": 1.0,
        "shadow": True,
        "position": "bottom",
        "margin": 4.5,
        "fill": "#FFFFFF",
        "outline_color": "#000000",
    },
    "movie": {
        "label": "电影宋体",
        "hint": "宋体加粗＋细一点的描边，正剧/电影旁白更稳。",
        "font": "songti",
        "weight": "bold",
        "size": 1.0,
        "outline": 0.8,
        "shadow": True,
        "position": "bottom",
        "margin": 4.8,
        "fill": "#FFFFFF",
        "outline_color": "#000000",
    },
    "japanese": {
        "label": "日式放送",
        "hint": "BIZ UDGothic 粗体，日文字幕常见的放送字形。",
        "font": "biz-ud",
        "weight": "bold",
        "size": 1.0,
        "outline": 1.0,
        "shadow": True,
        "position": "bottom",
        "margin": 4.5,
        "fill": "#FFFFFF",
        "outline_color": "#000000",
    },
    "clean": {
        "label": "清爽细体",
        "hint": "冬青黑常规字重，描边很轻；接近旧版观感。",
        "font": "hiragino",
        "weight": "regular",
        "size": 0.96,
        "outline": 0.55,
        "shadow": False,
        "position": "bottom",
        "margin": 4.5,
        "fill": "#FFFFFF",
        "outline_color": "#000000",
    },
}


def default_style() -> SubtitleStyle:
    return SubtitleStyle.from_mapping({"preset": "fansub", **STYLE_PRESETS["fansub"]})


def style_preset_list() -> list[dict]:
    items: list[dict] = []
    for key, preset in STYLE_PRESETS.items():
        style = SubtitleStyle.from_mapping({"preset": key, **preset})
        items.append(
            {
                "key": key,
                "label": preset["label"],
                "hint": preset["hint"],
                "style": style.to_dict(),
            }
        )
    return items





class ExportError(RuntimeError):
    """可以直接展示给用户的导出失败。"""


@dataclass(slots=True)
class SourceInfo:
    width: int = 0
    height: int = 0
    duration: float = 0.0
    video_bitrate: int = 0
    audio_bitrate: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    has_video: bool = False
    has_audio: bool = False
    size: int = 0
    container: str = ""

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "video_bitrate": self.video_bitrate,
            "audio_bitrate": self.audio_bitrate,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "has_video": self.has_video,
            "has_audio": self.has_audio,
            "size": self.size,
            "container": self.container,
        }


@dataclass(slots=True)
class ExportOptions:
    mode: str = "burn"
    track: str = "source"
    lang: str = ""
    resolution: str = "1080p"
    preset: str = "balanced"
    burn_subtitles: bool = True
    export_srt: bool = True
    style: SubtitleStyle = field(default_factory=default_style)

    def validate(self) -> None:
        if self.mode not in MODES:
            raise ExportError(f"未知导出模式：{self.mode}")
        if self.track not in ("source", "target", "both"):
            raise ExportError(f"未知字幕轨：{self.track}")
        if self.resolution not in RESOLUTIONS:
            raise ExportError(f"未知分辨率：{self.resolution}")
        if self.preset not in PRESETS:
            raise ExportError(f"未知码率档位：{self.preset}")
        self.style.validate()
        if self.track != "source" and not self.lang.strip():
            raise ExportError("导出译文时必须指定语种")


@dataclass(slots=True)
class ExportPlan:
    mode: str
    track: str
    lang: str
    width: int
    height: int
    video_bitrate: int
    audio_bitrate: int
    duration: float
    estimated_bytes: int
    estimated_seconds: float
    container: str
    suffix: str
    warnings: list[str] = field(default_factory=list)
    source: SourceInfo = field(default_factory=SourceInfo)
    style: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "track": self.track,
            "lang": self.lang,
            "width": self.width,
            "height": self.height,
            "video_bitrate": self.video_bitrate,
            "audio_bitrate": self.audio_bitrate,
            "duration": self.duration,
            "estimated_bytes": self.estimated_bytes,
            "estimated_seconds": self.estimated_seconds,
            "container": self.container,
            "suffix": self.suffix,
            "warnings": self.warnings,
            "source": self.source.to_dict(),
            "style": self.style,
        }


# --------------------------------------------------------------------------- 探测 / 规划


def probe_source(path: Path) -> SourceInfo:
    import json

    path = Path(path)
    try:
        proc = run_command(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries",
                "format=duration,bit_rate,size,format_name:stream=codec_type,codec_name,width,height,bit_rate",
                "-of", "json",
                str(path),
            ],
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise ExportError("找不到 ffprobe，请先安装 ffmpeg。") from exc
    except CommandTimeout as exc:
        raise ExportError("ffprobe 超时，文件可能损坏。") from exc
    except OSError as exc:
        raise ExportError(f"无法执行 ffprobe：{exc}") from exc
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        data = {}
    fmt = data.get("format") or {}
    info = SourceInfo()
    info.container = str(fmt.get("format_name") or "")
    try:
        info.duration = max(0.0, float(fmt.get("duration") or 0.0))
        info.size = int(fmt.get("size") or path.stat().st_size)
        info.video_bitrate = int(fmt.get("bit_rate") or 0)
    except (TypeError, ValueError, OSError):
        pass
    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and not info.has_video:
            info.has_video = True
            info.video_codec = str(stream.get("codec_name") or "")
            try:
                info.width = int(stream.get("width") or 0)
                info.height = int(stream.get("height") or 0)
                stream_rate = int(stream.get("bit_rate") or 0)
                if stream_rate > 0:
                    info.video_bitrate = stream_rate
            except (TypeError, ValueError):
                pass
        elif kind == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = str(stream.get("codec_name") or "")
            try:
                info.audio_bitrate = int(stream.get("bit_rate") or 0)
            except (TypeError, ValueError):
                pass
    return info


def _even(value: int) -> int:
    return max(2, int(value) // 2 * 2)


def _base_bitrate(height: int) -> int:
    last = _BITRATE_LADDER[0][1]
    for limit, value in _BITRATE_LADDER:
        if height <= limit:
            return value
        last = value
    return last


def _copy_container(source: SourceInfo) -> tuple[str, str]:
    """不重编码时的容器：优先 MP4，编解码组合不兼容才退回 MKV。"""
    video_ok = source.video_codec in {"h264", "hevc", "av1"}
    audio_ok = (not source.has_audio) or source.audio_codec in {
        "aac", "mp3", "ac3", "eac3", "alac",
    }
    if video_ok and audio_ok:
        return "mp4", ".mp4"
    return "mkv", ".mkv"


def plan_export(source: SourceInfo, options: ExportOptions) -> ExportPlan:
    options.validate()
    if not source.has_video or source.width <= 0 or source.height <= 0:
        raise ExportError("当前媒体没有可导出的视频画面（纯音频文件请直接导出字幕）")
    if options.mode == "burn":
        if not _pillow_available():
            raise ExportError(
                "当前内核缺少 Pillow，无法烧录硬字幕；请改用「软字幕 MP4 / 仅封装」，"
                "或重新安装 requirements.txt 依赖。"
            )
        _ensure_style_font(options.style)

    warnings: list[str] = []
    if options.mode == "copy":
        container, ext = _copy_container(source)
        height = _even(source.height)
        width = _even(source.width)
        video_bitrate = source.video_bitrate or max(
            1, int(source.size * 8 / max(0.001, source.duration))
        )
        audio_bitrate = source.audio_bitrate or 0
        estimated = int(source.size * 1.01)
        if container == "mkv":
            warnings.append("源编码组合不适合 MP4，输出 MKV；画质无损，但 QuickTime 可能打不开。")
        warnings.append("仅封装不重编码：视频/音频原样复制，几秒完成，体积与源接近。")
        return ExportPlan(
            mode=options.mode,
            track=options.track,
            lang=options.lang,
            width=width,
            height=height,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            duration=source.duration,
            estimated_bytes=estimated,
            estimated_seconds=max(2.0, min(45.0, source.duration * 0.01)),
            container=container,
            suffix=ext,
            warnings=warnings,
            source=source,
        )

    target_height = RESOLUTIONS.get(options.resolution, 1080)
    if options.resolution == "source" or target_height <= 0:
        height = _even(source.height)
    else:
        height = _even(min(target_height, source.height))
    width = _even(round(source.width * height / max(1, source.height)))
    if width <= 0:
        width = _even(source.width)
    if height <= 0:
        height = _even(source.height)

    factor = float(PRESETS[options.preset]["factor"])
    video_bitrate = int(_base_bitrate(height) * factor)
    if source.video_bitrate > 0:
        cap_factor = 1.25 if options.preset in ("high", "ultra") else 1.0
        video_bitrate = min(video_bitrate, int(source.video_bitrate * cap_factor))
    video_bitrate = max(250_000, video_bitrate)
    audio_bitrate = (192_000 if height >= 720 else 128_000) if source.has_audio else 0
    if not source.has_audio:
        warnings.append("源文件没有音轨，成片将没有声音。")
    if source.duration > 0:
        estimated = int((video_bitrate + audio_bitrate) * source.duration / 8 * 1.01)
    else:
        estimated = 0
    speed = {"small": 2.6, "balanced": 2.2, "high": 1.5, "ultra": 0.9}[options.preset]
    estimated_seconds = max(2.0, source.duration / speed) if source.duration else 0.0

    if source.video_bitrate > 0 and video_bitrate < source.video_bitrate * 0.7:
        warnings.append("目标码率低于源文件，暗部/纹理会有可见损失；在意画质可选「高」或「极高」。")
    if options.resolution != "source" and target_height > source.height:
        warnings.append("源分辨率低于目标值，已按源尺寸输出，不做无意义放大。")

    container = "mp4"
    ext = ".mp4"
    return ExportPlan(
        mode=options.mode,
        track=options.track,
        lang=options.lang,
        width=width,
        height=height,
        video_bitrate=video_bitrate,
        audio_bitrate=audio_bitrate,
        duration=source.duration,
        estimated_bytes=estimated,
        estimated_seconds=estimated_seconds,
        container=container,
        suffix=ext,
        warnings=warnings,
        source=source,
    )


# --------------------------------------------------------------------------- 字体 / 字幕精灵


def _pillow_available() -> bool:
    try:
        import PIL  # noqa: F401

        return True
    except Exception:
        return False


_FONT_FILE_CACHE: dict[tuple[str, ...], str | None] = {}
_FONT_DIR_CACHE: list[Path] | None = None


def _font_dirs() -> list[Path]:
    """字体可能出现的目录：系统字体目录 + AssetsV2 的 Font* 资产目录。"""
    global _FONT_DIR_CACHE
    if _FONT_DIR_CACHE is None:
        dirs = [path for path in FONT_SEARCH_DIRS if path.is_dir()]
        assets = Path("/System/Library/AssetsV2")
        if assets.is_dir():
            try:
                dirs.extend(
                    sorted(path for path in assets.glob("com_apple_MobileAsset_Font*/*/AssetData") if path.is_dir())
                )
            except OSError:
                pass
        _FONT_DIR_CACHE = dirs
    return _FONT_DIR_CACHE


def _find_font_file(files: tuple[str, ...]) -> str | None:
    cached = _FONT_FILE_CACHE.get(files)
    if cached is not None or files in _FONT_FILE_CACHE:
        return cached
    found: str | None = None
    for folder in _font_dirs():
        for name in files:
            candidate = folder / name
            if candidate.is_file():
                found = str(candidate)
                break
        if found:
            break
    _FONT_FILE_CACHE[files] = found
    return found


@lru_cache(maxsize=64)
def _face_index(path: str, face_family: str, face_style: str) -> int:
    """在 TTC 里按名字找到对应字重；找不到就退回第 0 个面。"""
    from PIL import ImageFont

    for index in range(0, 24):
        try:
            probe = ImageFont.truetype(path, 12, index=index)
        except OSError:
            break
        if tuple(probe.getname()) == (face_family, face_style):
            return index
    return 0


@lru_cache(maxsize=256)
def _resolve_face(family_key: str, weight: str) -> tuple[str, str, int]:
    """返回 ``(文件路径, family 名, TTC index)``；任何不可用时抛可读错误。"""
    order = [family_key] + [f.key for f in FONT_FAMILIES if f.key != family_key]
    for key in order:
        family = _FONT_BY_KEY.get(key)
        if family is None:
            continue
        path = _find_font_file(family.files)
        if not path:
            continue
        wanted = weight if weight in family.faces else "regular"
        face_family, face_style = family.faces[wanted]
        return path, face_family, _face_index(path, face_family, face_style)
    tried = " / ".join(name for family in FONT_FAMILIES for name in family.files)
    raise ExportError(
        f"找不到可用的中文字体（已尝试 {tried}）。烧录硬字幕需要系统字体；"
        "可改用「软字幕封装」，或在预览里换一个字体。"
    )


def _load_font(family_key: str, weight: str, size: int):
    from PIL import ImageFont

    path, _, index = _resolve_face(family_key, weight)
    try:
        return ImageFont.truetype(path, size=size, index=index)
    except OSError:
        return ImageFont.truetype(path, size=size)


def _ensure_style_font(style: SubtitleStyle) -> None:
    style.validate()
    _resolve_face(style.font, style.weight)


def font_status() -> tuple[bool, str]:
    """给设置页/导出面板判断「这台机器能不能烧硬字幕」。"""
    if not _pillow_available():
        return False, "当前内核缺少 Pillow，无法烧录硬字幕"
    try:
        _resolve_face("pingfang", "bold")
    except ExportError as exc:
        return False, str(exc)
    return True, ""


def font_catalog() -> list[dict]:
    """可选的字体列表（含本机是否可用）。"""
    items: list[dict] = []
    for family in FONT_FAMILIES:
        available = _find_font_file(family.files) is not None
        items.append(
            {
                "key": family.key,
                "label": family.label,
                "hint": family.hint,
                "available": available,
                "weights": [{"key": key, "label": label} for key, label in WEIGHTS.items()],
            }
        )
    return items

def _wrap_line(text: str, font, max_width: float) -> list[str]:
    """按字符宽度折行；优先在空格/标点处断，找不到就硬断。"""
    text = str(text or "").strip()
    if not text:
        return []
    if font.getlength(text) <= max_width:
        return [text]
    lines: list[str] = []
    current = ""
    break_chars = set("，。、！？；：,.!?;: 　）】」』")
    for char in text:
        candidate = current + char
        if current and font.getlength(candidate) > max_width:
            # 回退到最近的空格/标点，避免把句子切得太碎
            cut = -1
            for idx in range(len(current) - 1, max(0, len(current) - 8) - 1, -1):
                if current[idx] in break_chars:
                    cut = idx + 1
                    break
            if cut > 0:
                lines.append(current[:cut].rstrip())
                current = current[cut:].lstrip() + char
            else:
                lines.append(current.rstrip())
                current = char
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())
    return lines


def _fit_lines(
    text: str,
    base_size: int,
    max_width: float,
    max_lines: int,
    *,
    family: str,
    weight: str,
):
    """从基准字号往下试，直到折行数不超过 max_lines；返回 (font, lines)。"""
    size = base_size
    floor = max(12, int(base_size * 0.62))
    last = None
    while size >= floor:
        font = _load_font(family, weight, size)
        lines: list[str] = []
        for paragraph in str(text or "").split("\n"):
            lines.extend(_wrap_line(paragraph, font, max_width))
        if len(lines) <= max_lines:
            return font, lines
        last = (font, lines)
        size -= 1
    font, lines = last or (_load_font(family, weight, floor), [str(text or "")])
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("，。、") + "…"
    return font, lines


@dataclass(slots=True)
class StyleMetrics:
    """样式换算成像素后的结果（精灵与预览共用，保证所见即所得）。"""

    font_px: int
    outline_px: int
    shadow_px: int
    shadow_blur: int
    line_gap: int
    block_h: int
    margin_px: int


def style_metrics(style: SubtitleStyle, height: int, *, lines: int = 2, scale: float = 1.0) -> StyleMetrics:
    height = max(2, int(round(height * scale)))
    font_px = int(round(height * FONT_BASE_RATIO * float(style.size)))
    font_px = max(12, min(240, font_px))
    outline_px = max(0, int(round(font_px * OUTLINE_RATIO * float(style.outline))))
    shadow_px = max(1, int(round(font_px * SHADOW_RATIO))) if style.shadow else 0
    shadow_blur = max(1, int(round(font_px * 0.045))) if style.shadow else 0
    line_gap = max(2, int(round(font_px * 0.14)))
    # 行高按 1.16 倍字号估；再加描边和阴影的外扩，避免最下面一行被裁。
    text_h = int(round(font_px * 1.16)) * lines + line_gap * (lines - 1)
    padding = outline_px * 2 + shadow_px * 2 + int(round(font_px * 0.18))
    block_h = max(28, text_h + padding)
    margin_px = max(0, int(round(height * float(style.margin) / 100.0)))
    return StyleMetrics(
        font_px=font_px,
        outline_px=outline_px,
        shadow_px=shadow_px,
        shadow_blur=shadow_blur,
        line_gap=line_gap,
        block_h=block_h,
        margin_px=margin_px,
    )


def _hex_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    from PIL import ImageColor

    red, green, blue = ImageColor.getrgb(value)
    return (red, green, blue, max(0, min(255, int(alpha))))


def _text_layer(
    text: str,
    *,
    out_w: int,
    metrics: StyleMetrics,
    style: SubtitleStyle,
    max_lines: int = 2,
):
    """把一句字幕画成 width × block_h 的透明图层（含描边与阴影）。"""
    from PIL import Image, ImageDraw, ImageFilter

    text = str(text or "").strip()
    layer = Image.new("RGBA", (out_w, metrics.block_h), (0, 0, 0, 0))
    if not text:
        return layer
    font, lines = _fit_lines(
        text,
        metrics.font_px,
        out_w * 0.9,
        max_lines,
        family=style.font,
        weight=style.weight,
    )
    if not lines:
        return layer
    content = "\n".join(lines)
    anchor = (out_w / 2, metrics.block_h / 2)
    if metrics.shadow_px:
        shadow = Image.new("RGBA", (out_w, metrics.block_h), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.multiline_text(
            (anchor[0], anchor[1] + metrics.shadow_px),
            content,
            font=font,
            fill=(0, 0, 0, 150),
            anchor="mm",
            align="center",
            spacing=metrics.line_gap,
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(metrics.shadow_blur))
        layer.alpha_composite(shadow)
    draw = ImageDraw.Draw(layer)
    draw.multiline_text(
        anchor,
        content,
        font=font,
        fill=_hex_rgba(style.fill),
        anchor="mm",
        align="center",
        spacing=metrics.line_gap,
        stroke_width=metrics.outline_px,
        stroke_fill=_hex_rgba(style.outline_color, 245),
    )
    return layer


def _render_sprite(
    cues: list[SubtitleCue],
    *,
    batch_start: int,
    batch_end: int,
    out_w: int,
    out_h: int,
    lines_per_cue: int,
    style: SubtitleStyle,
    path: Path,
    scale: float = 1.0,
    cancel_event=None,
) -> int:
    """画一批字幕精灵，返回单块高度。第 0 块是空白。

    ``scale`` < 1 时按比例缩小精灵，由 ffmpeg 放大回输出尺寸：4K 长片字幕
    不需要逐像素级精度，用一半分辨率可以把内存占用降到 1/4。
    """
    from PIL import Image

    scale = max(0.4, min(1.0, float(scale)))
    out_w = max(2, int(round(out_w * scale)))
    out_h = max(2, int(round(out_h * scale)))
    metrics = style_metrics(style, out_h, lines=lines_per_cue)
    block_h = metrics.block_h
    count = batch_end - batch_start
    sprite = Image.new("RGBA", (out_w, block_h * (count + 1)), (0, 0, 0, 0))
    for offset, cue in enumerate(cues[batch_start:batch_end]):
        if is_shutting_down() or (cancel_event is not None and cancel_event.is_set()):
            raise CommandCancelled(["ffmpeg"])
        layer = _text_layer(
            str(cue.text or "").strip(),
            out_w=out_w,
            metrics=metrics,
            style=style,
            max_lines=lines_per_cue,
        )
        sprite.alpha_composite(layer, (0, (offset + 1) * block_h))
    sprite.save(path, "PNG")
    return block_h


def _gradient_background(width: int, height: int):
    """预览用的中性深色背景，避免纯黑看不出描边细节。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (26, 30, 38))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        color = (
            int(24 + 26 * t),
            int(28 + 24 * t),
            int(38 + 22 * t),
        )
        draw.line([(0, y), (width, y)], fill=color)
    return image.convert("RGBA")


def render_preview(
    style: SubtitleStyle,
    *,
    width: int = 1280,
    height: int = 720,
    text: str = "这句话用来预览字幕的字体、粗细与描边。",
    background: bytes | None = None,
    zoom: bool = False,
) -> bytes:
    """渲染一张样式预览 PNG；有真实视频帧就用它当背景。

    ``zoom=True`` 时裁出字幕周围的一条「特写」：界面里的预览面板只有三百多
    像素宽，整帧 16:9 缩进去后字号只剩十来像素，看不清字重与描边；特写把
    横向裁窄，按面板宽度显示时字号能放大近两倍。
    """
    from PIL import Image

    width = max(320, min(1920, int(width)))
    height = max(180, min(1080, int(height)))
    if background:
        try:
            image = Image.open(io.BytesIO(background)).convert("RGBA")
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        except Exception:  # noqa: BLE001 - 背景坏了不能挡住预览
            image = _gradient_background(width, height)
    else:
        image = _gradient_background(width, height)

    metrics = style_metrics(style, height, lines=2)
    layer = _text_layer(text, out_w=width, metrics=metrics, style=style, max_lines=2)
    if style.position == "top":
        y = metrics.margin_px
    else:
        y = height - metrics.block_h - metrics.margin_px
    image.alpha_composite(layer, (0, max(0, min(height - 1, y))))

    if zoom:
        box = layer.getbbox()
        text_w = (box[2] - box[0]) if box else width * 0.7
        crop_w = int(min(width, max(380, min(640, text_w + 80))))
        band_h = int(min(height, metrics.block_h + 40))
        center_x = ((box[0] + box[2]) // 2) if box else width // 2
        left = max(0, min(width - crop_w, center_x - crop_w // 2))
        top = max(0, min(height - band_h, y - 20))
        image = image.crop((left, top, left + crop_w, top + band_h))

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _batch_size(out_w: int, block_h: int) -> int:
    # 单张精灵控制在 ~110 MB 以内；4K 下自动变成二三十句一批。
    budget = 110 * 1024 * 1024
    per_block = max(1, out_w * block_h * 4)
    # 上限 60：crop 的时间表达式是一串嵌套 if，批越大表达式越长；FFmpeg 在
    # 240 句一批时已经报 "Failed to configure input pad"。60 句一批实测稳定。
    return max(16, min(60, budget // per_block))


# --------------------------------------------------------------------------- ffmpeg


def _seconds_from_hhmmss(value: str) -> float:
    parts = value.strip().split(":")
    if len(parts) != 3:
        return 0.0
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return 0.0


def _progress_reader(cmd: list[str], duration: float, on_progress, cancel_event):
    """跑一次 ffmpeg，解析 ``-progress pipe:1``；失败时返回 stderr。

    为什么用读线程 + 队列而不是直接 ``readline()``：进度流在 ffmpeg 输出前
    是阻塞的，取消令牌根本没有机会被检查。旧实现正是这样——进度永远停在 0%，
    点「取消」也要等 ffmpeg 自己跑完才生效。现在主循环每 150ms 醒一次，
    先看取消令牌，再取一行进度。
    """
    err_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    proc = None
    reader = None
    max_out = 0.0
    speed = ""
    last_emit = 0.0
    last_pct = -1
    lines: "queue.Queue[str | None]" = queue.Queue()
    try:
        with SPAWN_LOCK:
            if is_shutting_down():
                raise CommandCancelled(cmd)
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=err_file,
                text=True,
                bufsize=1,
            )
            register_process(proc)
        if is_shutting_down():
            # sidecar 正在退出：刚 spawn 的 ffmpeg 不能留下来继续编码
            terminate_process(proc)
            raise CommandCancelled(cmd)

        def _pump(pipe) -> None:
            try:
                for raw in iter(pipe.readline, ""):
                    lines.put(raw)
            except Exception:  # noqa: BLE001 - 管道关闭时正常结束
                pass
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass
                lines.put(None)

        reader = threading.Thread(
            target=_pump,
            args=(proc.stdout,),
            daemon=True,
            name="kikusub-ffmpeg-progress",
        )
        reader.start()

        while True:
            if cancel_event is not None and cancel_event.is_set():
                terminate_process(proc)
                raise CommandCancelled(cmd)
            try:
                line = lines.get(timeout=0.15)
            except queue.Empty:
                continue
            if line is None:
                break
            key, _, value = line.strip().partition("=")
            key, value = key.strip(), value.strip()
            updated = False
            if key in ("out_time_us", "out_time_ms"):
                # 注意 `out_time_ms` 在 ffmpeg 里实际也是微秒（历史命名）。
                try:
                    max_out = max(max_out, float(value) / 1_000_000.0)
                    updated = True
                except ValueError:
                    pass
            elif key == "out_time":
                max_out = max(max_out, _seconds_from_hhmmss(value))
                updated = True
            elif key == "speed":
                speed = value
            if not updated:
                continue
            now = time.time()
            if now - last_emit < 0.25:
                continue
            if duration > 0:
                pct = int(min(99, max(0, max_out / duration * 100)))
                if pct == last_pct and now - last_emit < 1.5:
                    continue
                last_pct = pct
            else:
                pct = None
            last_emit = now
            if on_progress is not None:
                on_progress(max_out, pct, {"speed": speed})
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            terminate_process(proc)
        if cancel_event is not None and cancel_event.is_set():
            raise CommandCancelled(cmd)
        err_file.seek(0)
        stderr = err_file.read()
        return proc.returncode, stderr
    finally:
        if proc is not None and proc.poll() is None:
            terminate_process(proc)
        unregister_process(proc)
        if reader is not None:
            reader.join(timeout=1.5)
        try:
            proc.stdout.close()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            err_file.close()
        except Exception:
            pass


def _encoder_args(bitrate: int) -> list[list[str]]:
    """返回依次尝试的编码参数：先硬件、后 CPU。"""
    maxrate = max(400_000, int(bitrate * 1.35))
    bufsize = max(800_000, int(bitrate * 2.5))
    hardware = [
        "-c:v", "h264_videotoolbox",
        "-b:v", str(bitrate),
        "-maxrate", str(maxrate),
        "-bufsize", str(bufsize),
        "-allow_sw", "1",
    ]
    software = [
        "-c:v", "libx264",
        "-preset", "medium",
        "-b:v", str(bitrate),
        "-maxrate", str(maxrate),
        "-bufsize", str(bufsize),
        "-pix_fmt", "yuv420p",
    ]
    return [hardware, software]


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}-{int(time.time())}{path.suffix}")


def _suffix_for(track: str, lang: str) -> str:
    if track == "target":
        return f".{lang}"
    if track == "both":
        return ".bilingual"
    return ""


def _subtitle_cues(cues: list[SubtitleCue], track: str, texts: list[str] | None):
    if track == "target":
        result, skipped = target_cues(cues, texts or [])
        if not result:
            raise ExportError("译文轨全是空的，没有可导出的字幕")
        return result, skipped
    if track == "both":
        return bilingual_cues(cues, texts or []), 0
    return list(cues), 0


def run_export(
    media_path: Path,
    cues: list[SubtitleCue],
    info: SourceInfo,
    options: ExportOptions,
    out_dir: Path,
    *,
    translation_texts: list[str] | None = None,
    on_progress=None,
    cancel_event=None,
) -> dict:
    """阻塞执行导出；成功返回结果字典，失败抛 :class:`ExportError` / ``CommandCancelled``。"""
    options.validate()
    if not cues:
        raise ExportError("当前没有字幕，先转写或导入一份再导出")
    plan = plan_export(info, options)
    if options.mode == "burn":
        # 提前确认字体可用，别等编码到一半才报错
        _ensure_style_font(options.style)

    media_path = Path(media_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = media_path.stem
    suffix = _suffix_for(options.track, options.lang)
    ext = ".mkv" if options.mode == "copy" and plan.container == "mkv" else ".mp4"
    # 文件名用**实际输出高度**：源片是 360p 时选 1080p 不会放大，名字也不该骗人。
    res_tag = options.resolution
    if options.resolution != "source" and plan.height != RESOLUTIONS.get(options.resolution):
        res_tag = f"{plan.height}p"
    out_path = _unique_path(out_dir / f"{stem}{suffix}.{res_tag}.{options.preset}{ext}")

    track_cues, skipped = _subtitle_cues(cues, options.track, translation_texts)
    # 空字幕不烧进画面
    track_cues = [cue for cue in track_cues if str(cue.text or "").strip()]
    if not track_cues:
        raise ExportError("当前字幕轨没有文本可导出")

    tmpdir = Path(tempfile.mkdtemp(prefix="kikusub-export-"))
    started = time.time()
    try:
        srt_path = tmpdir / "subtitles.srt"
        srt_path.write_text(cues_to_srt(track_cues), encoding="utf-8")
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            # 没有 -progress 时 ffmpeg 的 stdout 是空的，读线程会一直阻塞：
            # 进度停在 0%、取消也收不到。这个参数是进度与取消能工作的前提。
            "-nostats", "-progress", "pipe:1",
            "-i", str(media_path),
        ]
        extra_inputs: list[Path] = []
        filter_complex = ""
        map_args: list[str] = []
        stage = "正在准备导出…"
        burn_base = 0.0
        sprite_scale = 1.0

        if options.mode == "burn":
            # 双语也只按两行排版：源/译各一行，长句由 _fit_lines 自动缩字号。
            lines_per_cue = 2
            metrics = style_metrics(options.style, plan.height, lines=lines_per_cue)
            block_h = metrics.block_h
            # 4K/2K 用半分辨率精灵再放大，内存占用降到 1/4；1080p 以下保持原尺寸。
            if plan.height > 1440:
                sprite_scale = 0.5
            elif plan.height > 1080:
                sprite_scale = 0.75
            batch = _batch_size(
                max(2, int(round(plan.width * sprite_scale))),
                max(28, int(round(block_h * sprite_scale))),
            )
            chunks = [track_cues[i : i + batch] for i in range(0, len(track_cues), batch)]
            filter_parts = [
                f"[0:v]setpts=PTS-STARTPTS,scale={plan.width}:{plan.height}:flags=lanczos,setsar=1[base0]"
            ]
            prev = "base0"
            # 画精灵要花时间（4K 长片尤其明显），把它算进前 10%，否则进度条在
            # 真正开始编码前会一直停在 0%。
            burn_base = 0.10
            if on_progress is not None:
                on_progress(0.01, f"正在渲染字幕图层 0/{max(1, len(chunks))}", {})
            for index, chunk in enumerate(chunks):
                if is_shutting_down() or (cancel_event is not None and cancel_event.is_set()):
                    raise CommandCancelled(["ffmpeg"])
                start_index = index * batch
                end_index = start_index + len(chunk)
                sprite_path = tmpdir / f"subs_{index:03d}.png"
                actual_block = _render_sprite(
                    track_cues,
                    batch_start=start_index,
                    batch_end=end_index,
                    out_w=plan.width,
                    out_h=plan.height,
                    lines_per_cue=lines_per_cue,
                    style=options.style,
                    path=sprite_path,
                    scale=sprite_scale,
                    cancel_event=cancel_event,
                )
                extra_inputs.append(sprite_path)
                expr = "0"
                for offset in range(len(chunk) - 1, -1, -1):
                    cue = chunk[offset]
                    expr = (
                        f"if(between(t,{cue.start:.3f},{cue.end:.3f}),"
                        f"{actual_block * (offset + 1)},{expr})"
                    )
                input_index = index + 1
                label = f"sub{index}"
                scaled_label = f"subs{index}"
                out_label = f"base{index + 1}"
                sprite_w = max(2, int(round(plan.width * sprite_scale)))
                plan_block = max(28, int(round(actual_block / sprite_scale)))
                filter_parts.append(
                    f"[{input_index}:v]crop={sprite_w}:{actual_block}:0:'{expr}'[{label}]"
                )
                filter_parts.append(
                    f"[{label}]scale={plan.width}:{plan_block}:flags=lanczos[{scaled_label}]"
                )
                enable_start = chunk[0].start
                enable_end = chunk[-1].end
                margin_px = max(0, int(round(plan.height * float(options.style.margin) / 100.0)))
                if options.style.position == "top":
                    y = margin_px
                else:
                    y = plan.height - plan_block - margin_px
                filter_parts.append(
                    f"[{prev}][{scaled_label}]overlay=0:{max(0, y)}:enable='between(t,{enable_start:.3f},{enable_end:.3f})'[{out_label}]"
                )
                prev = out_label
                if on_progress is not None:
                    done = index + 1
                    on_progress(
                        0.01 + (burn_base - 0.01) * done / max(1, len(chunks)),
                        f"正在渲染字幕图层 {done}/{len(chunks)}",
                        {},
                    )
            filter_complex = ";".join(filter_parts)
            map_args = ["-map", f"[{prev}]", "-map", "0:a:0?"]
            stage = "正在烧录字幕并编码…"
        elif options.mode == "soft":
            cmd += ["-i", str(srt_path)]
            filter_complex = (
                f"[0:v]setpts=PTS-STARTPTS,scale={plan.width}:{plan.height}:flags=lanczos,setsar=1[v]"
            )
            map_args = ["-map", "[v]", "-map", "0:a:0?", "-map", "1:s:0"]
            stage = "正在封装软字幕并编码…"
        else:  # copy
            cmd += ["-i", str(srt_path)]
            map_args = ["-map", "0:v:0", "-map", "0:a:0?", "-map", "1:s:0"]
            stage = "正在复制视频流并封装软字幕…"

        for sprite in extra_inputs:
            cmd += ["-loop", "1", "-i", str(sprite)]
        if filter_complex:
            cmd += ["-filter_complex", filter_complex]

        # 把命令拆成「前缀 / 编码段 / 后缀」，硬件失败时只替换编码段重试，
        # 不能靠字符串切片改命令（很容易把 -c:a 之类的参数顺序弄乱）。
        prefix = list(cmd) + list(map_args)
        tail_args: list[str] = []
        if options.mode == "copy":
            tail_args += ["-c:v", "copy", "-c:a", "copy"]
            tail_args += ["-c:s", "srt" if plan.container == "mkv" else "mov_text"]
            tail_args += ["-metadata:s:s:0", f"language={_lang_code(options.lang, options.track)}"]
        elif options.mode == "soft":
            tail_args += ["-c:a", "aac", "-b:a", str(plan.audio_bitrate or 128_000)]
            tail_args += ["-c:s", "mov_text"]
            tail_args += ["-metadata:s:s:0", f"language={_lang_code(options.lang, options.track)}"]
        else:  # burn：字幕已经画进画面，不再生成字幕流
            tail_args += ["-c:a", "aac", "-b:a", str(plan.audio_bitrate or 128_000)]
        if plan.container == "mp4":
            tail_args += ["-movflags", "+faststart"]
        if plan.duration > 0:
            tail_args += ["-t", f"{plan.duration:.3f}"]
        partial = out_path.with_name(f".{out_path.stem}.part{out_path.suffix}")
        tail_args += [str(partial)]

        if options.mode == "copy":
            variants = [prefix + tail_args]
        else:
            variants = [prefix + enc + tail_args for enc in _encoder_args(plan.video_bitrate)]

        # 进度基线：烧录模式的前 10% 已经花在字幕图层上，编码从 10% 起算；
        # 软字幕/仅封装的准备阶段很短，从 2% 起算即可。
        progress_base = burn_base if options.mode == "burn" else 0.02
        if on_progress is not None:
            on_progress(0.0, stage, {})

        def progress(out_s: float, pct: int | None, extras: dict | None = None) -> None:
            if on_progress is None:
                return
            if pct is None:
                ratio = progress_base
            else:
                ratio = progress_base + (pct / 100.0) * (0.99 - progress_base)
            payload: dict = {"out_s": out_s}
            for key in ("speed", "fps"):
                value = (extras or {}).get(key)
                if value:
                    payload[key] = value
            on_progress(ratio, stage, payload)

        last_error = ""
        for attempt, run_cmd in enumerate(variants):
            try:
                returncode, stderr = _progress_reader(
                    run_cmd, plan.duration, progress, cancel_event
                )
            except CommandCancelled:
                try:
                    partial.unlink()
                except OSError:
                    pass
                raise
            if returncode == 0 and partial.exists() and partial.stat().st_size > 1024:
                partial.replace(out_path)
                break
            last_error = tail(stderr, 1600) or f"ffmpeg 退出码 {returncode}"
            try:
                partial.unlink()
            except OSError:
                pass
        else:
            raise ExportError(f"导出失败：{last_error}")

        size = out_path.stat().st_size
        result = {
            "path": str(out_path),
            "name": out_path.name,
            "size": size,
            "elapsed": round(time.time() - started, 2),
            "width": plan.width,
            "height": plan.height,
            "video_bitrate": plan.video_bitrate,
            "audio_bitrate": plan.audio_bitrate,
            "duration": plan.duration,
            "mode": options.mode,
            "track": options.track,
            "lang": options.lang,
            "resolution": options.resolution,
            "actual_resolution": res_tag,
            "preset": options.preset,
            "container": plan.container,
            "subtitle_count": len(track_cues),
            "skipped": skipped,
            "style": options.style.to_dict() if options.mode == "burn" else {},
        }
        if options.export_srt:
            try:
                srt_out = _unique_path(out_dir / f"{stem}{suffix}.srt")
                # 随片附带的字幕同样是交付文件：双语按「每语种一条 cue」写，
                # 别写成一条两行——那会让用户重新导入核对台时挤成一行（D-4）。
                srt_cues = (
                    bilingual_entries(cues, translation_texts or [])
                    if options.track == "both"
                    else track_cues
                )
                srt_out.write_text(cues_to_srt(srt_cues), encoding="utf-8")
                result["srt_path"] = str(srt_out)
            except OSError:
                # 成片已经成功，SRT 写失败不能让整个导出判失败；界面不再显示 srt_path。
                pass
        return result
    finally:
        try:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def _lang_code(lang: str, track: str) -> str:
    if track == "source":
        return "jpn"
    value = (lang or "").lower()
    if value.startswith("zh-hant") or value.startswith("zh-tw"):
        return "chi"
    if value.startswith("zh"):
        return "zho"
    if value.startswith("en"):
        return "eng"
    if value.startswith("ko"):
        return "kor"
    if value.startswith("ja"):
        return "jpn"
    return "und"
