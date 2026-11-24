#!/usr/bin/env bash
# 删一棵目录树，躲开 macOS Finder 的 `.DS_Store` 竞态。
#
# 为什么不能直接 `rm -rf`（2026-11-21 实际踩到）：
#   Finder 显示过 `build/pack/...` 里的目录之后会往里写 `.DS_Store`。`rm -rf` 把几万
#   个文件删完、调 rmdir 之前的那一瞬间如果正好被写进一个 `.DS_Store`，rmdir 就返回
#   ENOTEMPTY，`rm` 报 `Directory not empty`；打包脚本是 `set -e`，于是整个重打停在
#   这里（表现：`bash tools/pack/rebuild.sh` 只输出一行 rm 报错就退出）。
#
# 做法：先同盘 rename 挪走，再删那个带随机后缀的垃圾目录。
#   rename 是原子的 —— Finder 手里握的目录仍是旧 inode，不会追到新名字里继续写；
#   删除阶段再重试几次，把「删的过程中又被写进来」的残余兜掉。同盘 rename 不搬数据，
#   几千兆的目录也是瞬间完成。
#
# 用法：`source tools/pack/_rmtree.sh` 之后 `rm_tree <dir> [<dir>...]`。
# 失败返回 1（交给调用方的 `set -e` 中止），并打印卡住的路径。

rm_tree() {
  local target trash attempt
  for target in "$@"; do
    # 悬空符号链接也要删：`-e` 对它为假
    [ -e "$target" ] || [ -L "$target" ] || continue

    trash="${target}.trash.$$.$RANDOM"
    if ! mv "$target" "$trash" 2>/dev/null; then
      # 改名失败（跨设备、父目录只读、并发…）：退回原地删，下面照样重试
      trash="$target"
    fi

    # PyInstaller 偶尔产出只读文件；先把写权限补回来，否则 rm 会卡在 EACCES
    chmod -R u+w "$trash" 2>/dev/null || true

    for attempt in 1 2 3 4 5; do
      rm -rf "$trash" 2>/dev/null && break
      # 最后一招：清掉被写进来的 .DS_Store，再来一轮
      find "$trash" -name .DS_Store -delete 2>/dev/null || true
      sleep 0.3
    done

    if [ -e "$trash" ] || [ -L "$trash" ]; then
      echo "❌ 删不掉：$trash" >&2
      echo "   多半还有进程在往里写（Finder 窗口 / 正在运行的 sidecar）。" >&2
      echo "   关掉那个 Finder 窗口或结束进程后，手动删掉它再重跑。" >&2
      return 1
    fi
  done
}
