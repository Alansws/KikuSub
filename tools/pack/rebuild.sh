#!/usr/bin/env bash
# 一条命令完成「改完代码 → 新的 KikuSub.app → 打开」。
#
#   bash tools/pack/rebuild.sh          # 按需重打 sidecar（仅 Python 变了才跑），构建、装配、打开
#   bash tools/pack/rebuild.sh --no-open # 只构建，不打开
#   FORCE_SIDECAR=1 bash tools/pack/rebuild.sh  # 强制重打 sidecar（约 3–5 分钟）
#
# 为什么需要它：改 `core/` / `server/` 后 build_app.sh 会拒绝装配旧 sidecar；而改了
# 渲染层却忘了 `npm run build` 时，装出来的 .app 仍是旧界面。这里把两步串起来，并在
# 打开前先把旧实例正常退出——否则 macOS 单实例锁会把新构建挡在门外。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

OPEN_APP=1
for arg in "$@"; do
  case "$arg" in
    --no-open) OPEN_APP=0 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数：$arg" >&2
      exit 2
      ;;
  esac
done

SIDECAR_BIN="build/pack/dist/sidecar/sidecar"
APP="build/pack/KikuSub.app"

need_sidecar=0
if [ "${FORCE_SIDECAR:-0}" = "1" ]; then
  need_sidecar=1
elif [ ! -x "$SIDECAR_BIN" ]; then
  need_sidecar=1
elif [ -n "$(find core server -name '*.py' -newer "$SIDECAR_BIN" -print -quit 2>/dev/null || true)" ]; then
  need_sidecar=1
elif [ tools/pack/sidecar_entry.py -nt "$SIDECAR_BIN" ]; then
  need_sidecar=1
fi

if [ "$need_sidecar" = "1" ]; then
  echo "== Python 侧有改动：重打 sidecar（3–5 分钟）=="
  bash tools/pack/build_sidecar.sh
else
  echo "== sidecar 仍是最新，跳过（FORCE_SIDECAR=1 可强制重打）=="
fi

echo "== 构建渲染层 =="
(cd desktop && npm run build)

echo "== 装配 KikuSub.app =="
bash tools/pack/build_app.sh

if [ "$OPEN_APP" = "1" ]; then
  # 旧实例还在跑时，新进程会因单实例锁直接退出：先让它走正常退出流程。
  # 用 SIGTERM 而不是 osascript：本机没有给终端 Automation 权限，Apple Event
  # 会被拒（-10004）；Electron 对 SIGTERM 走的正是 app.quit() → before-quit。
  if pgrep -f "KikuSub.app/Contents/MacOS/KikuSub" >/dev/null 2>&1; then
    echo "== 关闭正在运行的旧实例 =="
    pkill -TERM -f "KikuSub.app/Contents/MacOS/KikuSub" >/dev/null 2>&1 || true
    for _ in $(seq 1 24); do
      pgrep -f "KikuSub.app/Contents/MacOS/KikuSub" >/dev/null 2>&1 || break
      sleep 0.25
    done
    # 退出流程被清理面板挡住 / 卡住时兜底；sidecar 有父进程看门狗，2 秒内会自己退出。
    if pgrep -f "KikuSub.app/Contents/MacOS/KikuSub" >/dev/null 2>&1; then
      echo "⚠️ 旧实例没有及时退出（可能在退出清理面板上），强制结束" >&2
      pkill -9 -f "KikuSub.app/Contents/MacOS/KikuSub" >/dev/null 2>&1 || true
      sleep 2
    fi
  fi
  echo "== 打开 $APP =="
  open "$APP"
fi

echo "完成：$REPO_ROOT/$APP"
