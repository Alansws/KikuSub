#!/usr/bin/env bash
# 设置页两屏静默截图（引擎与模型 / AI 与技能的折叠态）。
#
#   bash tools/shots/capture_settings_pages.sh            # 输出到 /tmp/kikusub-settings-pages
#   bash tools/shots/capture_settings_pages.sh docs/images/shots/current
#   KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox bash tools/shots/capture_settings_pages.sh
#   KIKUSUB_SETTINGS_SHOT_SIZE=1440x880 bash tools/shots/capture_settings_pages.sh DIR
#
# 视口默认 1440×880（不是 1440×900）：macOS 的可视工作区高度扣掉菜单栏与 Dock 后通常
# 只有 885pt 左右，请求 900 会被系统压回 885，落盘文件名却还写着 900——本项目踩过
# 「文件名一直骗人」的亏。要更高的视口就在支持的机器上显式传 KIKUSUB_SETTINGS_SHOT_SIZE。
#
# 为什么单独一个脚本：`capture_matrix.sh` 的 `settings` 状态只点侧栏，切视图动画 + 引擎注册表
# 加载常常没跑完，截出来是半透明的骨架屏（「正在读取引擎配置…」「0/0 引擎」）。这里在 eval
# 里多等两次再截，并且能直接落到 AI 与技能页（`#set-tab-ai`）——README 与 §6 的验收图都要它。
#
# 全程无窗口：走主进程 `--screenshot`（透明窗口 + capturePage + app.exit）。
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${1:-/tmp/kikusub-settings-pages}"
SIZE="${KIKUSUB_SETTINGS_SHOT_SIZE:-1440x880}"
ELECTRON_ARGS="${KIKUSUB_SHOT_ELECTRON_ARGS:-}"
case "$OUT_DIR" in
  -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
esac
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

shot() {  # $1=文件名前缀 $2=dev-eval
  local name="$1" eval="$2"
  local base="/tmp/kikusub-shot-$name"
  rm -rf "$base"; mkdir -p "$base/out" "$base/data" "$base/profile"
  local extra_args=("--user-data-dir=$base/profile")
  # shellcheck disable=SC2206
  [ -n "$ELECTRON_ARGS" ] && extra_args+=($ELECTRON_ARGS)
  ( cd "$REPO/desktop" && env KIKUSUB_ALLOW_MULTIPLE=1 "KIKUSUB_WIN_SIZE=$SIZE" \
      KIKUSUB_SHOT_DELAY=9000 "KIKUSUB_OUTPUT_DIR=$base/out" "KIKUSUB_DATA_DIR=$base/data" \
      "KIKUSUB_PREFERENCES_PATH=$base/prefs.json" "KIKUSUB_DEV_EVAL=$eval" \
      env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS \
      npx electron . "${extra_args[@]}" --screenshot="$OUT_DIR/$name-$SIZE.png" ) \
      > "/tmp/kikusub-shot-$name.log" 2>&1
  if [ -f "$OUT_DIR/$name-$SIZE.png" ]; then
    echo "  ✓ $name  $(du -h "$OUT_DIR/$name-$SIZE.png" | cut -f1)"
  else
    echo "  ✗ ${name}（见 /tmp/kikusub-shot-$name.log）"
  fi
}

SETTLE='const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));'
# 侧栏第 10 项是「设置」；等引擎注册表落地再截，否则会截到骨架屏。
shot settings-engines "(async()=>{$SETTLE document.querySelectorAll('.sb-item')[9]?.click(); await sleep(2600); document.querySelector('.settings')?.scrollTo(0,0); await sleep(1200); return 'ok';})()"
shot settings-ai "(async()=>{$SETTLE document.querySelectorAll('.sb-item')[9]?.click(); await sleep(1200); document.querySelector('#set-tab-ai')?.click(); await sleep(2200); document.querySelector('.settings')?.scrollTo(0,0); await sleep(800); return 'ok';})()"
