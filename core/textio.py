"""原子写文本。

`Path.write_text` 在写入过程中崩溃/断电会留下半截文件，而 SRT 解析器对半截文件
不会报错，只会少最后几条——用户无从察觉。这里保证目标文件「要么是旧内容、
要么是完整新内容」，任何中间态都只存在于临时文件里。

从 `app.py` 原样搬出，供服务层与桌面端共用。
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def write_text_atomic(path: str | Path, text: str, encoding: str = "utf-8") -> Path:
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


def next_available_path(path: str | Path) -> Path:
    """同名文件已存在时给出不冲突的路径：`name (2).srt`、`name (3).srt`……

    与成片导出共用同一套编号约定：交付文件**绝不静默覆盖**另一份内容。
    调用方先判断内容是否相同；相同可以原地重写，不同才用这个函数换名。
    """
    target = Path(path)
    if not target.exists():
        return target
    for index in range(2, 1000):
        candidate = target.with_name(f"{target.stem} ({index}){target.suffix}")
        if not candidate.exists():
            return candidate
    return target.with_name(f"{target.stem}-{int(time.time())}{target.suffix}")
