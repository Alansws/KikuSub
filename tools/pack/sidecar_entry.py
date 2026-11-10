"""打包入口：把 `python -m server` 变成可执行文件。

PyInstaller 需要一个真实脚本作为入口（`-m` 的写法它不认），
所以这里只是把 `server.__main__.main()` 转出来。
"""

from __future__ import annotations

import logging
import sys

from server.__main__ import main

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
