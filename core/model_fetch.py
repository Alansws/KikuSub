"""HuggingFace 权重下载的共用入口。

背景：三个可选模型（SenseVoice / FireRedASR2 / FireRedPunc）都在运行时按需下载，
之前 `core/sherpa_asr.py` 里已经有一份「直连失败 → 换镜像重试」的逻辑。标点模型是
第二个调用方，所以抽到这里，避免两份下载逻辑慢慢分叉。

**只在没有显式设置 `HF_ENDPOINT` 时才回退到镜像**：用户或 CI 自己指定了镜像/代理时，
尊重他们的选择，不要悄悄改回默认值。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

MIRROR_ENDPOINT = "https://hf-mirror.com"


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
    try:
        snapshot_download(**kwargs)
    except Exception:
        if os.environ.get("HF_ENDPOINT"):
            raise
        log.warning("HuggingFace 直连失败，改用镜像重试 | repo=%s", repo_id, exc_info=True)
        os.environ["HF_ENDPOINT"] = MIRROR_ENDPOINT
        import huggingface_hub.constants as hub_constants

        hub_constants.HF_ENDPOINT = MIRROR_ENDPOINT
        snapshot_download(**kwargs)
