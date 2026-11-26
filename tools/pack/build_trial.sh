#!/usr/bin/env bash
# 构建「与现役 KikuSub.app 完全隔离、可双开」的试用版（2026-11-25）。
#
# 默认产物：build/pack-next/KikuSub-Next.app
# 默认身份：bundle id com.kikusub.desktop.next
# 默认数据：~/Library/Application Support/KikuSub-Next（Chromium userData 与
#           settings / presets / preferences / .ai-key 都在这一处）
#
# 三条硬保护：
#   1. 产物路径与名称不能等于现役包（默认就是独立的 build/pack-next）；
#   2. 装配脚本带 KIKUSUB_ISOLATION=1，跳过现役 Application Support 的模型软链，
#      并把隔离身份写进包内 app-isolation.json；
#   3. 全程不打开窗口、不注册默认文件处理器、不碰 build/pack/KikuSub.app。
#
# 用法：
#   bash tools/pack/build_trial.sh
#   KIKUSUB_TRIAL_APP=KikuSub-Another bash tools/pack/build_trial.sh
#
# 只给用户体验用：发版仍走 tools/pack/rebuild.sh → docs/release.md。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

APP_NAME="${KIKUSUB_TRIAL_APP:-KikuSub-Next}"
BUNDLE_ID="${KIKUSUB_TRIAL_BUNDLE_ID:-com.kikusub.desktop.next}"
PACK_DIR="${KIKUSUB_TRIAL_PACK_DIR:-build/pack-next}"
DATA_DIR_NAME="${KIKUSUB_TRIAL_DATA_DIR:-$APP_NAME}"

# 硬保护：名字只允许单段安全字符，避免把产物 / 数据根拼到别处。
[[ "$APP_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || {
  echo "❌ 试用版产品名不合法：$APP_NAME" >&2
  exit 1
}
[[ "$DATA_DIR_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || {
  echo "❌ 试用版数据根名不合法：$DATA_DIR_NAME" >&2
  exit 1
}
[[ "$BUNDLE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9.-]+$ && "$BUNDLE_ID" != *..* ]] || {
  echo "❌ 试用版 bundle id 不合法：$BUNDLE_ID" >&2
  exit 1
}

# 产物目录必须真实落在仓库 build/ 下，且不能是现役的 build/pack。
PACK_PARENT="$(cd "$(dirname "$PACK_DIR")" 2>/dev/null && pwd -P)" || {
  echo "❌ 试用版产物目录的父目录不存在：$PACK_DIR" >&2
  exit 1
}
PACK_DIR="$PACK_PARENT/$(basename "$PACK_DIR")"
REPO_BUILD="$(cd "$REPO_ROOT" && pwd -P)/build"
case "$PACK_DIR" in
  "$REPO_BUILD"/*) ;;
  *)
    echo "❌ 试用版产物必须写在仓库 build/ 下：$PACK_DIR" >&2
    exit 1
    ;;
esac

# 硬保护：试用构建必须换独立身份，绝不允许指回现役产物。
[ "$APP_NAME" != "KikuSub" ] || {
  echo "❌ 试用版不允许使用现役产品名 KikuSub（会顶掉现役包的身份）" >&2
  exit 1
}
[ "$PACK_DIR" != "$REPO_BUILD/pack" ] || {
  echo "❌ 试用版不允许写 build/pack（现役 KikuSub.app 的目录）" >&2
  exit 1
}
[ "$BUNDLE_ID" != "com.kikusub.desktop" ] || {
  echo "❌ 试用版必须使用独立 bundle id（现役是 com.kikusub.desktop）" >&2
  exit 1
}
[ "$DATA_DIR_NAME" != "KikuSub" ] || {
  echo "❌ 试用版必须使用独立数据根（现役是 Application Support/KikuSub）" >&2
  exit 1
}

APP="$PACK_DIR/$APP_NAME.app"

SIDECAR_BIN="build/pack/dist/sidecar/sidecar"
CLI_BIN="build/pack/dist/kikusub"
CLI_LIB="build/pack/dist/kikusub-internal"

[ -d "desktop/node_modules/electron/dist/Electron.app" ] || {
  echo "缺少 Electron：cd desktop && npm install" >&2
  exit 1
}
[ -x "build/pack/vendor/ffmpeg/bin/ffmpeg" ] && [ -x "build/pack/vendor/ffmpeg/bin/ffprobe" ] || {
  echo "❌ 缺少内置 ffmpeg/ffprobe：先跑 bash tools/pack/fetch_ffmpeg.sh" >&2
  exit 1
}

# --- 和 rebuild.sh 同一套「按需重打」判断（只写 build/pack/dist 构建产物）---
need_sidecar=0
if [ ! -x "$SIDECAR_BIN" ]; then
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
  echo "== sidecar 仍是最新，跳过 =="
fi

need_cli=0
if [ ! -x "$CLI_BIN" ] || [ ! -d "$CLI_LIB" ]; then
  need_cli=1
elif [ -n "$(find tools/kikusub -name '*.py' -newer "$CLI_BIN" -print -quit 2>/dev/null || true)" ]; then
  need_cli=1
fi
if [ "$need_cli" = "1" ]; then
  echo "== CLI 有改动：重打 kikusub =="
  bash tools/pack/build_cli.sh
else
  echo "== kikusub CLI 仍是最新，跳过 =="
fi

echo "== 构建渲染层 =="
(cd desktop && npm run build)

echo "== 装配隔离试用版：$APP =="
KIKUSUB_APP_NAME="$APP_NAME" \
KIKUSUB_BUNDLE_ID="$BUNDLE_ID" \
KIKUSUB_PACK_DIR="$PACK_DIR" \
KIKUSUB_DATA_DIR_NAME="$DATA_DIR_NAME" \
KIKUSUB_ISOLATION=1 \
bash tools/pack/build_app.sh

[ -d "$APP" ] || { echo "❌ 装配后没有找到 $APP" >&2; exit 1; }

# 装配后硬校验：身份与现役包必须不同，且隔离配置真的在包里。
APP_BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Contents/Info.plist")"
[ "$APP_BUNDLE_ID" = "$BUNDLE_ID" ] || {
  echo "❌ 包内 bundle id 是 ${APP_BUNDLE_ID}，期望 ${BUNDLE_ID}" >&2
  exit 1
}
[ -f "$APP/Contents/Resources/app-isolation.json" ] || {
  echo "❌ 缺少 app-isolation.json，主进程不会切到独立数据根" >&2
  exit 1
}
grep -Fq "\"$DATA_DIR_NAME\"" "$APP/Contents/Resources/app-isolation.json" || {
  echo "❌ app-isolation.json 的数据根不是 $DATA_DIR_NAME" >&2
  exit 1
}

echo
echo "完成（未打开窗口）：$APP"
echo "身份：bundle id ${BUNDLE_ID}；数据根 ~/Library/Application Support/${DATA_DIR_NAME}"
du -sh "$APP"
