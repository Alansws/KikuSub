"""媒体资源注册表：本地文件 → 稳定 id，并缓存时长 / 波形包络 / 编码信息。

桌面端的「导入」不是上传：Electron 拿到的就是本地绝对路径，3 GB 的 MKV 没有任何
理由复制一份走 HTTP。所以 `POST /api/media` 收的是路径，只做校验与元数据探测。

id 取「解析后绝对路径」的哈希，因此重复导入同一文件是幂等的——前端刷新、窗口
重开都不会产生重复条目。
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path

from core import audio_cache, proxy
from core.paths import OUTPUT_DIR
from core.procutil import CommandCancelled, CommandTimeout, run_command

# 与 app.py 的 SUPPORTED 保持一致；这里只做快速失败，真正的解码能力由 ffmpeg 决定。
MEDIA_SUFFIXES = {
    ".mkv", ".mp4", ".mov", ".m4v", ".webm", ".avi", ".ts", ".flv",
    ".wmv", ".mpg", ".mpeg", ".ogv",
    ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff",
}

# Chromium 能直接解的视频容器；其余走代理（阶段 4 接上自动压制）。
WEB_SAFE_SUFFIXES = {".mp4", ".m4v", ".webm"}
WEB_SAFE_CODECS = {"h264", "vp8", "vp9", "av1"}

FFPROBE_TIMEOUT_S = 30.0


class MediaError(RuntimeError):
    """导入失败（文件不存在 / 格式不支持 / 探测失败）。"""


@dataclass(slots=True)
class MediaInfo:
    id: str
    path: Path
    name: str
    size: int
    duration: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    has_video: bool = False
    # 是否已经存在压好的 480p 监看代理。由 MediaStore 在探测时刷新。
    proxy_ready: bool = False

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()

    @property
    def needs_proxy(self) -> bool:
        """Chromium 大概率解不出来的情况，前端据此提示「正在压制代理」。"""
        if not self.has_video:
            return False
        if self.suffix not in WEB_SAFE_SUFFIXES:
            return True
        return bool(self.video_codec) and self.video_codec not in WEB_SAFE_CODECS

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": str(self.path),
            "size": self.size,
            "duration": self.duration,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "has_video": self.has_video,
            "needs_proxy": self.needs_proxy,
            "proxy_ready": self.proxy_ready,
        }


def media_id_for(path: Path) -> str:
    return hashlib.sha1(path.as_posix().encode("utf-8")).hexdigest()[:16]


def _ffprobe_json(path: Path) -> dict:
    proc = run_command(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,codec_name",
            "-of", "json", str(path),
        ],
        timeout=FFPROBE_TIMEOUT_S,
    )
    import json

    try:
        return json.loads(proc.stdout or "{}")
    except ValueError:
        return {}


@dataclass
class _PeaksEntry:
    duration: float
    bins: int
    values: list[float] = field(default_factory=list)


class MediaStore:
    """进程内媒体表。线程安全：所有读写都走同一把锁。"""

    def __init__(self, max_peaks_entries: int = 16, output_dir: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        self._items: dict[str, MediaInfo] = {}
        self._peaks: dict[tuple[str, int], _PeaksEntry] = {}
        self._max_peaks_entries = max_peaks_entries

    # -- 注册 ---------------------------------------------------------------

    def register(self, raw_path: str | Path) -> MediaInfo:
        path = Path(raw_path).expanduser()
        try:
            path = path.resolve(strict=True)
        except OSError as exc:
            raise MediaError(f"文件不存在或不可读：{path}") from exc
        if not path.is_file():
            raise MediaError(f"不是普通文件：{path}")
        if path.suffix.lower() not in MEDIA_SUFFIXES:
            raise MediaError(f"不支持的文件格式：{path.suffix or '（无扩展名）'}")

        media_id = media_id_for(path)
        with self._lock:
            existing = self._items.get(media_id)
            if existing is not None:
                return existing

            info = MediaInfo(
                id=media_id,
                path=path,
                name=path.name,
                size=path.stat().st_size,
            )
            self._probe(info)
            info.proxy_ready = self.proxy_path(info) is not None
            self._items[media_id] = info
            return info

    def _probe(self, info: MediaInfo) -> None:
        data = _ffprobe_json(info.path)
        fmt = data.get("format") or {}
        try:
            info.duration = max(0.0, float(fmt.get("duration") or 0.0))
        except (TypeError, ValueError):
            info.duration = 0.0

        for stream in data.get("streams") or []:
            kind = stream.get("codec_type")
            codec = str(stream.get("codec_name") or "")
            if kind == "video" and not info.video_codec:
                info.video_codec = codec
                info.has_video = True
            elif kind == "audio" and not info.audio_codec:
                info.audio_codec = codec

    # -- 查询 ---------------------------------------------------------------

    def proxy_path(self, info: MediaInfo) -> Path | None:
        """已压好的 480p 代理路径；没有则 None。

        每次都问一遍磁盘（而不是缓存）：压制任务在另一个线程里写文件，
        缓存会让前端永远看不到「刚压好」这个状态。
        """
        try:
            return proxy.get_existing_proxy(info.path, self._output_dir)
        except Exception:
            return None

    def describe(self, media_id: str) -> dict:
        """对外描述：带上实时的 proxy_ready。"""
        info = self.get(media_id)
        info.proxy_ready = self.proxy_path(info) is not None
        return info.to_dict()

    def get(self, media_id: str) -> MediaInfo:
        with self._lock:
            info = self._items.get(media_id)
        if info is None:
            raise MediaError(f"未知媒体 id：{media_id}")
        if not info.path.exists():
            raise MediaError("媒体文件已不存在，请重新导入。")
        return info

    def list(self) -> list[MediaInfo]:
        with self._lock:
            return list(self._items.values())

    def drop(self, media_id: str) -> None:
        with self._lock:
            self._items.pop(media_id, None)
            for key in [k for k in self._peaks if k[0] == media_id]:
                self._peaks.pop(key, None)

    # -- 波形 ---------------------------------------------------------------

    def peaks(self, media_id: str, bins: int) -> tuple[float, list[float]]:
        """返回 `(duration, 归一化包络)`。

        按 `(id, bins)` 做进程内缓存：前端缩放时按 LOD 换 bins，换档只算一次；
        同一档位来回缩放是纯内存命中，这是规划 §5 指标 2「< 16 ms」的前提。
        """
        info = self.get(media_id)
        bins = max(1, min(int(bins), 400_000))
        key = (media_id, bins)
        with self._lock:
            hit = self._peaks.get(key)
        if hit is not None:
            return hit.duration, list(hit.values)

        try:
            wav_path = audio_cache.ensure_wav(info.path, loudnorm=False)
            duration, values = audio_cache.peaks(wav_path, bins)
        except (CommandTimeout, CommandCancelled) as exc:
            raise MediaError(f"解码音频超时或已取消：{exc}") from exc
        except Exception as exc:  # ffmpeg 缺失 / 无音轨 / 文件损坏
            raise MediaError(f"无法生成波形：{exc}") from exc

        if duration <= 0:
            duration = info.duration
        self._remember_peaks(key, duration, values)
        return duration, list(values)

    def _remember_peaks(self, key: tuple[str, int], duration: float, values: list[float]) -> None:
        with self._lock:
            if len(self._peaks) >= self._max_peaks_entries:
                # 简单的 FIFO 淘汰：波形缓存只服务当前会话的少量档位，
                # 不值得引入 LRU 计数开销。
                self._peaks.pop(next(iter(self._peaks)), None)
            self._peaks[key] = _PeaksEntry(duration=duration, bins=key[1], values=list(values))
