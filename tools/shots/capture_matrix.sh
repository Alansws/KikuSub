#!/usr/bin/env bash
# 静默截图矩阵：一次把关键界面按固定视口截下来，供人工/像素比对。
#
# 为什么需要：改样式、改布局时"编译通过"不等于没坏。用法见同目录 README.md。
# 依赖主进程已有的 --screenshot（show:false + capturePage，不抢焦点，可后台跑）。
#
#   bash tools/shots/capture_matrix.sh                    # 输出到 docs/images/shots/current
#   bash tools/shots/capture_matrix.sh --out /tmp/x --size 1360x838
#   bash tools/shots/capture_matrix.sh --compare docs/images/shots/baseline
#
# 退出码：0 正常；2 参数错误；3 缺少 electron/ffmpeg 依赖。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$REPO_ROOT/docs/images/shots/current"
SIZE="1360x838"
DELAY=4500
COMPARE=""
MEDIA="${KIKUSUB_SHOT_MEDIA:-/tmp/kikusub-shot-media.mp4}"
STATES="transcribe review dual polish translate prompts export settings"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT_DIR="${2:?}"; shift 2 ;;
    --size) SIZE="${2:?}"; shift 2 ;;
    --delay) DELAY="${2:?}"; shift 2 ;;
    --media) MEDIA="${2:?}"; shift 2 ;;
    --states) STATES="${2:?}"; shift 2 ;;
    --compare) COMPARE="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -d "$REPO_ROOT/desktop/node_modules/electron" ] || { echo "缺少 desktop/node_modules/electron" >&2; exit 3; }
command -v ffmpeg >/dev/null || { echo "缺少 ffmpeg" >&2; exit 3; }

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"   # 子 shell 会 cd 到 desktop，这里必须先转绝对路径
if [ ! -f "$MEDIA" ]; then
  ffmpeg -y -v error -f lavfi -i color=c=0x223344:s=640x360:d=3 -pix_fmt yuv420p \
    -c:v libx264 -preset ultrafast "$MEDIA" || exit 3
fi

SEED="$(mktemp -t kikusub-shot-seed).json"
python3 - "$REPO_ROOT/tools/shots/seed.json" "$MEDIA" "$SEED" <<'PY'
import json, sys
src, media, dst = sys.argv[1:4]
data = json.load(open(src, encoding='utf-8'))
data['mediaPath'] = media
json.dump(data, open(dst, 'w', encoding='utf-8'), ensure_ascii=False)
PY

shot() {  # $1=状态名 $2=dev-eval $3=是否用 seed
  local name="$1" eval="$2" seed="${3:-}"
  local base="/tmp/kikusub-shot-$name"
  rm -rf "$base"; mkdir -p "$base/out" "$base/data"
  local envs=(KIKUSUB_ALLOW_MULTIPLE=1 "KIKUSUB_WIN_SIZE=$SIZE" "KIKUSUB_SHOT_DELAY=$DELAY"
              "KIKUSUB_OUTPUT_DIR=$base/out" "KIKUSUB_DATA_DIR=$base/data"
              "KIKUSUB_PREFERENCES_PATH=$base/prefs.json")
  [ -n "$seed" ] && envs+=("KIKUSUB_DEV_SEED=$SEED")
  [ -n "$eval" ] && envs+=("KIKUSUB_DEV_EVAL=$eval")
  ( cd "$REPO_ROOT/desktop" && env "${envs[@]}" env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS \
      npx electron . --screenshot="$OUT_DIR/$name-$SIZE.png" ) > "/tmp/kikusub-shot-$name.log" 2>&1
  local png="$OUT_DIR/$name-$SIZE.png"
  if [ -f "$png" ]; then
    echo "  ✓ ${name}  $(du -h "$png" | cut -f1)  $(grep -o '"active":"[^"]*"' "/tmp/kikusub-shot-$name.log" | head -1)"
  else
    echo "  ✗ ${name}（见 /tmp/kikusub-shot-${name}.log）"
  fi
}

for st in $STATES; do
  case "$st" in
    transcribe) shot transcribe "" "" ;;
    review)     shot review "" "seed" ;;
    settings)   shot settings "document.querySelectorAll('.sb-item')[8].click()" "" ;;
    prompts)    shot prompts "document.querySelectorAll('.sb-item')[7].click()" "" ;;
    export)     shot export "document.querySelectorAll('.sb-item')[6].click()" "" ;;
    translate)  shot translate "document.querySelectorAll('.sb-item')[5].click()" "" ;;
    polish)     shot polish "document.querySelectorAll('.sb-item')[4].click()" "" ;;
    dual)       shot dual "document.querySelectorAll('.sb-item')[3].click()" "" ;;
    *) echo "未知状态：$st" >&2; exit 2 ;;
  esac
done

if [ -n "$COMPARE" ]; then
  echo "== PSNR 对比（基线 ${COMPARE}；inf/高分 = 一致，<35dB 基本可判定改坏了）=="
  for st in $STATES; do
    a="$OUT_DIR/$st-$SIZE.png"; b="$COMPARE/$st-$SIZE.png"
    [ -f "$a" ] && [ -f "$b" ] || { echo "  $st: 缺文件，跳过"; continue; }
    printf "  %-11s " "$st"
    ffmpeg -hide_banner -v info -i "$a" -i "$b" -lavfi "[0:v][1:v]psnr" -f null - 2>&1 \
      | grep -o "average:[^ ]*" | head -1
  done
fi
