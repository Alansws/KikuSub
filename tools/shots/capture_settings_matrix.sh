#!/usr/bin/env bash
# 设置页取证矩阵：3 套主题 × 4 个页签，外加 4 个展开态与窄视口。
#
# 为什么单独一个脚本而不是塞进 capture_matrix.sh：设置页的取证要**先切主题再切页签**
# （主题卡只在外观页里），而 capture_matrix 的每个 state 只有一个 dev-eval 字符串，
# 传进去会把「哪个主题」和「哪个页签」揉成一段难维护的表达式。这里按参数拼装更清楚。
#
# 用法：
#   bash tools/shots/capture_settings_matrix.sh                 # 输出到 /tmp/kikusub-settings-shots
#   bash tools/shots/capture_settings_matrix.sh --out DIR \
#        --size 1360x838 --delay 11000
#   bash tools/shots/capture_settings_matrix.sh --only light-engines,dark-env
#
# 产物是 2x 的 PNG（主进程 --screenshot 的原生缩放）。仓库里提交的是转成 WebP 的同一批图
# （体积约为 PNG 的 1/3）；转换命令见 docs/sprints/2026-11-settings-redesign/落地记录.md。
#
# 依赖：desktop/node_modules/electron、可用的 sidecar（源码模式即可）。截图不抢焦点。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="/tmp/kikusub-settings-shots"
SIZE="1360x838"
DELAY="11000"
ONLY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT_DIR="${2:?}"; shift 2 ;;
    --size) SIZE="${2:?}"; shift 2 ;;
    --delay) DELAY="${2:?}"; shift 2 ;;
    --only) ONLY="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -d "$REPO_ROOT/desktop/node_modules/electron" ] || { echo "缺少 desktop/node_modules/electron" >&2; exit 3; }
mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"

# 页签 id 与 components/settings/SettingsTabs.svelte 里的 data 一致（lib/settings/tabs.ts）
TABS="engines appearance ai env"
THEMES="light dark mincho"
DATA_ROOT="/tmp/kikusub-settings-matrix"

theme_index() {
  case "$1" in
    light) echo 0 ;;
    dark) echo 1 ;;
    mincho) echo 2 ;;
    *) echo 0 ;;
  esac
}

shot() {  # $1=theme $2=tab $3=名字后缀 $4=额外 JS
  local theme="$1" tab="$2" suffix="$3" extra="${4:-}"
  local name="app-${theme}-${tab}${suffix}"
  local out="$OUT_DIR/${name}.png"
  local idx; idx="$(theme_index "$theme")"

  local extra_js=""
  [ -n "$extra" ] && extra_js="$extra"

  local eval_js
  eval_js=$(cat <<JS
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  document.querySelectorAll('.sb-item')[9]?.click();   // 侧栏「设置」
  await sleep(700);
  document.querySelector('#set-tab-appearance')?.click();
  await sleep(600);
  document.querySelectorAll('.theme-card')[${idx}]?.click();  // 主题卡：浅 / 深 / 明
  await sleep(600);
  document.querySelector('#set-tab-${tab}')?.click();
  await sleep(900);
  ${extra_js}
  await sleep(500);
  return 'ok';
})()
JS
)

  ( cd "$REPO_ROOT/desktop" && \
    KIKUSUB_ALLOW_MULTIPLE=1 KIKUSUB_WIN_SIZE="$SIZE" KIKUSUB_SHOT_DELAY="$DELAY" \
    KIKUSUB_OUTPUT_DIR="$DATA_ROOT/out" KIKUSUB_DATA_DIR="$DATA_ROOT/data" \
    KIKUSUB_PREFERENCES_PATH="$DATA_ROOT/prefs.json" \
    KIKUSUB_DEV_EVAL="$eval_js" \
    env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS npx electron . --screenshot="$out" \
      > "/tmp/kikusub-settings-${name}.log" 2>&1
  )

  if [ -f "$out" ]; then
    echo "  ✓ ${name}  $(du -h "$out" | cut -f1)"
  else
    echo "  ✗ ${name}（见 /tmp/kikusub-settings-${name}.log）" >&2
  fi
}

want() {
  [ -z "$ONLY" ] && return 0
  case ",$ONLY," in *",$1,"*) return 0 ;; *) return 1 ;; esac
}

echo "== 设置页截图矩阵（${SIZE}，输出 ${OUT_DIR}）=="
for theme in $THEMES; do
  for tab in $TABS; do
    want "${theme}-${tab}" || continue
    shot "$theme" "$tab" "" ""
  done
done

# 展开态与窄视口：只跑青空浅（展开态的主题差异已经由 12 张矩阵覆盖）
want "light-engines-open" && \
  shot light engines "-open" "document.querySelectorAll('.detail-btn').forEach((b)=>b.click()); document.querySelector('.settings').scrollTop = 560;"
want "light-ai-open" && \
  shot light ai "-open" "document.querySelector('details.advanced summary')?.click();"
want "light-env-open" && \
  shot light env "-open" "document.querySelector('details.paths-more summary')?.click(); document.querySelector('details.log-more summary')?.click(); document.querySelector('.settings').scrollTop = 99999;"

if want "narrow-engines"; then
  SIZE_SAVED="$SIZE"
  SIZE="680x900"
  shot light engines "-narrow" ""
  SIZE="$SIZE_SAVED"
fi

echo "完成。转换 WebP 并覆盖仓库证据的命令见 docs/sprints/2026-11-settings-redesign/落地记录.md"
