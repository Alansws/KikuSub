"""打包入口：把 `python -m server` 变成可执行文件。

PyInstaller 需要一个真实脚本作为入口（`-m` 的写法它不认），
所以这里只是把 `server.__main__.main()` 转出来。

**必须在任何重依赖导入之前调 `multiprocessing.freeze_support()`**：
torch 的分布式模块会 spawn `multiprocessing.resource_tracker`，在冻结环境里
那是一个「重新执行 sidecar 可执行文件」的子进程。不接 freeze_support 的话，
子进程会带着 `-B -S -I -c ...` 撞进我们的 argparse，报
`unrecognized arguments`——日志里能看到，但主流程不一定立刻失败，属于
「今天不炸、下次炸」的定时炸弹。
"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()

# 静态分析（PyInstaller Analysis）需要看到这个顶层导入；被 freeze_support
# 接管的子进程会在上一行直接 exec 并退出，走不到这里。
from server.__main__ import main  # noqa: E402

if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
