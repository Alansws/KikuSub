"""cwd 被删掉时的自愈（用户报障：打包覆盖 .app 后转写报 `[Errno 2] No such file or directory`）。

事故链：`tools/pack/build_app.sh` 是先 `rm -rf KikuSub.app` 再重新装配，而 sidecar 是
detached 的（父进程退出它也不跟着死）。装配那一刻它的 cwd 就变成一个已删除的 inode，
之后每次 `os.getcwd()` 都抛 `OSError(ENOENT)`——torch 在 import 期就会踩
（`torch/_dynamo/config.py: default_debug_dir_root`），一次 Whisper/Qwen 转写就这样在
1 秒内失败，界面上只剩一句 `[Errno 2]`，跟视频、模型毫无关系。

这里锁住两件事：目录还活着时不许乱动进程 cwd；目录没了必须挪到真实存在的目录。
"""

from __future__ import annotations

import os

from core.paths import ensure_usable_cwd


def test_ensure_usable_cwd_is_noop_when_cwd_alive() -> None:
    before = os.getcwd()

    assert ensure_usable_cwd() is None
    assert os.getcwd() == before


def test_ensure_usable_cwd_repairs_deleted_cwd(tmp_path, monkeypatch) -> None:
    doomed = tmp_path / "doomed"
    doomed.mkdir()
    # monkeypatch 会记住进入前的 cwd，用例结束自动切回去——否则下面的 rmdir 之后
    # 整个 pytest 进程都会站在一个已删除的目录里。
    monkeypatch.chdir(doomed)
    os.rmdir(doomed)

    moved = ensure_usable_cwd()

    assert moved is not None, "cwd 已删除时必须切换到可用目录"
    assert os.getcwd() == moved
    assert os.path.isdir(moved)
