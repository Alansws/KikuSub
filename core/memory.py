"""物理内存探测（P2 双引擎预检用）。

只回答两个问题：

- ``total_ram_gb()``：整机物理内存，用于**任务开始前**的硬闸门（8GB 机型拒绝 dual）；
- ``available_ram_gb()``：当前可用内存，只写进报告，不用于 Pass A 之后的硬拦截
  ——macOS 会把刚读过的大视频缓存在统一内存里，那个瞬时值偏低是正常的。

不引入 psutil：macOS 用 ``sysconf`` + ``vm_stat``，Linux 用 ``/proc/meminfo``。
任何探测失败返回 0，由调用方按「未知」处理，不能因此误拦用户。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

#: 双引擎顺序协同的最低物理内存；8GB 机型在开始前直接拒绝，16GB 放行。
MIN_DUAL_RAM_GB = 12.0


def _bytes_to_gb(value: float) -> float:
    return round(float(value) / (1024**3), 1)


def total_ram_gb() -> float:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        size = int(os.sysconf("SC_PAGE_SIZE"))
        return _bytes_to_gb(pages * size)
    except (ValueError, OSError, AttributeError):
        return 0.0


def _macos_available_gb() -> float:
    from . import procutil

    try:
        proc = procutil.run_command(["vm_stat"], timeout=3)
    except Exception:  # noqa: BLE001 - 探测失败按未知处理
        return 0.0
    if proc.returncode != 0:
        return 0.0
    text = proc.stdout or ""
    page_size = 4096
    for line in text.splitlines():
        if "page size of" in line:
            try:
                page_size = int(line.split("page size of")[1].split("bytes")[0].strip())
            except (IndexError, ValueError):
                pass
            break
    wanted = ("Pages free", "Pages inactive", "Pages speculative")
    pages = 0
    for line in text.splitlines():
        for key in wanted:
            if line.strip().startswith(key):
                try:
                    pages += int(line.split(":")[1].strip().rstrip("."))
                except (IndexError, ValueError):
                    pass
    return _bytes_to_gb(pages * page_size)


def _linux_available_gb() -> float:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return _bytes_to_gb(int(line.split()[1]) * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def available_ram_gb() -> float:
    try:
        if sys.platform == "darwin":
            return _macos_available_gb()
        if sys.platform.startswith("linux"):
            return _linux_available_gb()
    except Exception:  # noqa: BLE001 - 报告字段，不允许反噬任务
        log.debug("可用内存探测失败", exc_info=True)
    return 0.0


def dual_memory_error() -> str:
    """返回拒绝文案；0 表示可以跑（内存未知时不拦）。"""
    total = total_ram_gb()
    if total and total < MIN_DUAL_RAM_GB:
        return (
            f"双引擎顺序协同需要 {MIN_DUAL_RAM_GB:.0f}GB 以上物理内存，"
            f"当前 {total:.0f}GB。请只跑主引擎，或换一台内存更大的机器。"
        )
    return ""
