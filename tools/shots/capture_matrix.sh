#!/usr/bin/env bash
# 静默截图矩阵：一次把关键界面按固定视口截下来，供人工/像素比对。
#
# 为什么需要：改样式、改布局时"编译通过"不等于没坏。用法见同目录 README.md。
# 依赖主进程已有的 --screenshot（透明窗口 + capturePage，桌面上不出现，可后台跑）。
#
#   bash tools/shots/capture_matrix.sh                    # 输出到 docs/images/shots/current
#   bash tools/shots/capture_matrix.sh --out /tmp/x --size 1360x838
#   bash tools/shots/capture_matrix.sh --compare docs/images/shots/baseline
#   bash tools/shots/capture_matrix.sh --theme dark --states "polish reshape dual"
#                                                         # 带主题后缀，一次跑三套主题
#   bash tools/shots/capture_matrix.sh --seed tools/shots/readme-seed.json --delay 12000
#                                                         # 重出 README 成品图（见 tools/shots/README.md）
#   沙箱 / CI 里 Electron 起不来时：KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox bash ...
#
# 退出码：0 正常；2 参数错误；3 缺少 electron/ffmpeg 依赖。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$REPO_ROOT/docs/images/shots/current"
SIZE="1360x838"
DELAY=4500
COMPARE=""
MEDIA="${KIKUSUB_SHOT_MEDIA:-/tmp/kikusub-shot-media.mp4}"
STATES="import transcribe review dual polish reshape translate prompts export settings"
# 种子文件：默认 12 条演示字幕（时间从 0 开始）。README 的成品图另有一份
# `tools/shots/readme-seed.json`——时间落在《言叶之庭》那座桥约 1:58 处，
# 首屏截图才不会是一块黑画面。
SEED_FILE="$REPO_ROOT/tools/shots/seed.json"
# 外观：light（默认，沿用旧文件名）/ dark / mincho。
# 2026-11-25 起外观模型拆成「明暗（light/dark）」+「字幕字体（黑体/明朝）」：
# --theme mincho = light 外观 + 明朝字幕字体（旧名保留，方便既有命令与基线文件名不变）。
# 显式传 --theme 时文件名带主题后缀；不传时保持 <state>-<size>.png，基线比对不受影响。
THEME=""
# 沙箱环境（例如 CI 容器）里 Electron 起不来时，用 KIKUSUB_SHOT_ELECTRON_ARGS=--no-sandbox 追加。
ELECTRON_ARGS="${KIKUSUB_SHOT_ELECTRON_ARGS:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT_DIR="${2:?}"; shift 2 ;;
    --size) SIZE="${2:?}"; shift 2 ;;
    --delay) DELAY="${2:?}"; shift 2 ;;
    --media) MEDIA="${2:?}"; shift 2 ;;
    --states) STATES="${2:?}"; shift 2 ;;
    --compare) COMPARE="${2:?}"; shift 2 ;;
    --theme) THEME="${2:?}"; shift 2 ;;
    --seed) SEED_FILE="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

case "${THEME:-light}" in
  light|dark|mincho) ;;
  *) echo "未知主题：${THEME}（light / dark / mincho）" >&2; exit 2 ;;
esac

suffix() {
  [ -n "$THEME" ] && echo "-$THEME" || true
}
# 注意：只写 DOM 属性只能骗过第一帧的 CSS；真正的状态在 localStorage，
# 所以两处都写。mincho 走 data-cue-font，不再往 data-theme 塞第三个值。
theme_eval() {
  case "${THEME:-}" in
    "") ;;
    mincho)
      echo "document.documentElement.dataset.cueFont='mincho';localStorage.setItem('kikusub.cueFont','mincho');"
      ;;
    *)
      echo "document.documentElement.dataset.theme='${THEME}';localStorage.setItem('kikusub.appearance','${THEME}');"
      ;;
  esac
}

[ -d "$REPO_ROOT/desktop/node_modules/electron" ] || { echo "缺少 desktop/node_modules/electron" >&2; exit 3; }
command -v ffmpeg >/dev/null || { echo "缺少 ffmpeg" >&2; exit 3; }

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"   # 子 shell 会 cd 到 desktop，这里必须先转绝对路径
if [ ! -f "$MEDIA" ]; then
  ffmpeg -y -v error -f lavfi -i color=c=0x223344:s=640x360:d=3 -pix_fmt yuv420p \
    -c:v libx264 -preset ultrafast "$MEDIA" || exit 3
fi

[ -f "$SEED_FILE" ] || { echo "缺少种子文件：$SEED_FILE" >&2; exit 2; }
SEED="$(mktemp -t kikusub-shot-seed).json"
python3 - "$SEED_FILE" "$MEDIA" "$SEED" <<'PY'
import json, sys
src, media, dst = sys.argv[1:4]
data = json.load(open(src, encoding='utf-8'))
data['mediaPath'] = media
json.dump(data, open(dst, 'w', encoding='utf-8'), ensure_ascii=False)
PY

shot() {  # $1=状态名 $2=dev-eval $3=是否用 seed
  local name="$1" eval="$2" seed="${3:-}"
  local base="/tmp/kikusub-shot-$name"
  local out="$OUT_DIR/$name$(suffix)-$SIZE.png"
  rm -rf "$base"; mkdir -p "$base/out" "$base/data" "$base/profile"
  local envs=(KIKUSUB_ALLOW_MULTIPLE=1 "KIKUSUB_WIN_SIZE=$SIZE" "KIKUSUB_SHOT_DELAY=$DELAY"
              "KIKUSUB_OUTPUT_DIR=$base/out" "KIKUSUB_DATA_DIR=$base/data"
              "KIKUSUB_PREFERENCES_PATH=$base/prefs.json")
  [ -n "$seed" ] && envs+=("KIKUSUB_DEV_SEED=$SEED")
  # 主题要单独判一次：`review` 这类状态没有自己的 eval，过去 `[ -n "$eval" ]`
  # 直接把 theme_eval 一起吞掉了——`--theme dark --states review` 截出来的
  # 其实是浅色，文件名却在骗人（2026-11-24 发现）。
  local theme_prefix
  theme_prefix="$(theme_eval)"
  if [ -n "$theme_prefix" ] || [ -n "$eval" ]; then
    envs+=("KIKUSUB_DEV_EVAL=${theme_prefix}${eval}")
  fi
  local extra_args=()
  # 截图模式不固定 userData：这里显式给一个临时 profile，避免落到用户的
  # ~/Library/Application Support 里（沙箱环境会直接起不来）。
  extra_args+=(--user-data-dir="$base/profile")
  # shellcheck disable=SC2206
  [ -n "$ELECTRON_ARGS" ] && extra_args+=($ELECTRON_ARGS)
  ( cd "$REPO_ROOT/desktop" && env "${envs[@]}" env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS \
      npx electron . "${extra_args[@]}" --screenshot="$out" ) > "/tmp/kikusub-shot-$name.log" 2>&1
  if [ -f "$out" ]; then
    echo "  ✓ ${name}$(suffix)  $(du -h "$out" | cut -f1)  $(grep -o '"active":"[^"]*"' "/tmp/kikusub-shot-$name.log" | head -1)"
  else
    echo "  ✗ ${name}$(suffix)（见 /tmp/kikusub-shot-${name}.log）"
  fi
}

for st in $STATES; do
  case "$st" in
    # 截图模式的初始视图是「导入」以外的一屏（转写），所以每个状态都显式点侧栏；
    # 早期 `transcribe` 不点，截出来其实是导入页，文件名一直在骗人。
    # 需要「有片 + 有字幕」才有意义的页面用 seed（导入 / 转写 / 核对 / 翻译 / 导出）：
    # 空态的转写与导出页只能看见「先导入媒体」，对 README 与人工验收都没信息量。
    import)     shot import "document.querySelectorAll('.sb-item')[0].click()" "seed" ;;
    transcribe) shot transcribe "document.querySelectorAll('.sb-item')[1].click()" "seed" ;;
    review)     shot review "" "seed" ;;
    # 侧栏顺序（components/Sidebar.svelte）：0 导入 / 1 转写 / 2 核对台 / 3 双引擎 /
    # 4 润色 / 5 断句重排 / 6 翻译 / 7 导出 / 8 提示词库 / 9 设置
    settings)   shot settings "document.querySelectorAll('.sb-item')[9].click()" "" ;;
    prompts)    shot prompts "document.querySelectorAll('.sb-item')[8].click()" "" ;;
    # 导出页的「样式预览」要等一次 style-preview 请求回来（有片时取当前帧），
    # 点完立刻截会截到「渲染中…」+ 纯色底，看起来像坏了。
    export)     shot export "(async()=>{document.querySelectorAll('.sb-item')[7].click(); await new Promise((r)=>setTimeout(r,3000));})()" "seed" ;;
    translate)  shot translate "document.querySelectorAll('.sb-item')[6].click()" "seed" ;;
    polish)     shot polish "document.querySelectorAll('.sb-item')[4].click()" "" ;;
    reshape)    shot reshape "document.querySelectorAll('.sb-item')[5].click()" "" ;;
    dual)       shot dual "document.querySelectorAll('.sb-item')[3].click()" "" ;;
    *) echo "未知状态：$st" >&2; exit 2 ;;
  esac
done

if [ -n "$COMPARE" ]; then
  echo "== PSNR 对比（基线 ${COMPARE}；inf/高分 = 一致，<35dB 基本可判定改坏了）=="
  for st in $STATES; do
    a="$OUT_DIR/$st$(suffix)-$SIZE.png"; b="$COMPARE/$st$(suffix)-$SIZE.png"
    [ -f "$a" ] && [ -f "$b" ] || { echo "  $st: 缺文件，跳过"; continue; }
    printf "  %-11s " "$st"
    ffmpeg -hide_banner -v info -i "$a" -i "$b" -lavfi "[0:v][1:v]psnr" -f null - 2>&1 \
      | grep -o "average:[^ ]*" | head -1
  done
fi
