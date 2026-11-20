"""HuggingFace 权重下载的共用入口。

背景：可选模型（SenseVoice / FireRedASR2 / FireRedPunc / WhisperSeg 切分器）都在
运行时按需下载。下载口径只留这一份：**直连失败 → 换镜像重试一次**，不要在调用方
各自再写一份，否则重试条件、镜像开关会慢慢分叉。

**只在没有显式设置 `HF_ENDPOINT` 时才回退到镜像**：用户或 CI 自己指定了镜像/代理时，
尊重他们的选择，不要悄悄改回默认值。

两个入口：
- `snapshot_download_files()`：按 allow_patterns 下整个目录（模型权重）；
- `hf_hub_download_file()`：只下单个文件（例如 Whisper 的 preprocessor_config.json）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

MIRROR_ENDPOINT = "https://hf-mirror.com"


def _retry_with_mirror(repo_id: str, call) -> None:
    """执行 ``call()``；直连失败且用户没指定 endpoint 时切镜像重试一次。"""
    try:
        call()
    except Exception:
        if os.environ.get("HF_ENDPOINT"):
            raise
        log.warning("HuggingFace 直连失败，改用镜像重试 | repo=%s", repo_id, exc_info=True)
        os.environ["HF_ENDPOINT"] = MIRROR_ENDPOINT
        import huggingface_hub.constants as hub_constants

        hub_constants.HF_ENDPOINT = MIRROR_ENDPOINT
        call()


def snapshot_download_files(
    *,
    repo_id: str,
    dest: Path,
    allow_patterns: list[str] | tuple[str, ...],
    progress_cb=None,
    label: str = "",
) -> None:
    """把 repo 里匹配的文件下到 ``dest``；直连失败时用镜像重试一次。

    进度由调用方（下载任务）按磁盘增长估算，这里只在开始给一帧阶段文案。
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb(0.005, f"正在下载 {label or repo_id} 权重…")

    from huggingface_hub import snapshot_download

    kwargs = {
        "repo_id": repo_id,
        "local_dir": str(dest),
        "allow_patterns": list(allow_patterns),
        "max_workers": 2,
    }
    _retry_with_mirror(repo_id, lambda: snapshot_download(**kwargs))


def hf_hub_download_file(
    *,
    repo_id: str,
    filename: str,
    dest: Path,
    progress_cb=None,
    label: str = "",
) -> Path:
    """下载 repo 里的单个文件到 ``dest``；直连失败时用镜像重试一次。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb(0.01, f"正在下载 {label or filename}…")

    from huggingface_hub import hf_hub_download

    kwargs = {
        "repo_id": repo_id,
        "filename": filename,
        "local_dir": str(dest),
    }
    _retry_with_mirror(repo_id, lambda: hf_hub_download(**kwargs))
    return dest / filename
