#!/usr/bin/env bash
# 重新打包后 Finder 仍显示旧图标 / 空白图标时执行一次。
#
# 只做两件事：touch 应用包（让 IconServices 重新取图标）+ 重新向 LaunchServices
# 注册。传入 --restart 会重启 Finder（窗口会自动恢复），用于缓存特别顽固的情况。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="${1:-$REPO_ROOT/build/pack/KikuSub.app}"
if [ "${1:-}" = "--restart" ]; then
  APP="$REPO_ROOT/build/pack/KikuSub.app"
fi

if [ ! -d "$APP" ]; then
  echo "找不到应用包：$APP" >&2
  exit 1
fi

touch "$APP"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [ -x "$LSREGISTER" ]; then
  "$LSREGISTER" -f -R -trusted "$APP" || true
fi

if [ "${1:-}" = "--restart" ] || [ "${2:-}" = "--restart" ]; then
  echo "重启 Finder 以刷新图标缓存…"
  killall Finder 2>/dev/null || true
fi

echo "已刷新：$APP"
echo "如果 Finder 仍显示旧图标，请再执行：bash tools/pack/refresh_finder_icon.sh --restart"
