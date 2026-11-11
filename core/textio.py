"""原子写文本。

`Path.write_text` 在写入过程中崩溃/断电会留下半截文件，而 SRT 解析器对半截文件
不会报错，只会少最后几条——用户无从察觉。这里保证目标文件「要么是旧内容、
要么是完整新内容」，任何中间态都只存在于临时文件里。

从 `app.py` 原样搬出，供服务层与桌面端共用。
"""

from __future__ import annotations

import os
import tempfile
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
