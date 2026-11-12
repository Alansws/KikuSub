#!/usr/bin/env bash
# 手工装配 KikuSub.app。
#
# 为什么不用 electron-builder：它在本机被宿主文件策略打断在 packaging 阶段
# （复制 Electron 框架时对 default_app.asar 报 Operation not permitted）。
# 手工装配的每一步都可控，出问题也看得见。
#
# 前置：bash tools/pack/build_sidecar.sh 已产出 build/pack/dist/sidecar

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

APP="build/pack/KikuSub.app"
ELECTRON_APP="desktop/node_modules/electron/dist/Electron.app"
SIDECAR="build/pack/dist/sidecar"

[ -d "$ELECTRON_APP" ] || { echo "缺少 Electron：cd desktop && npm install" >&2; exit 1; }
[ -d "$SIDECAR" ] || { echo "缺少 sidecar：先跑 build_sidecar.sh" >&2; exit 1; }
[ -d "desktop/renderer/dist" ] || { echo "缺少渲染层构建：cd desktop && npx vite build" >&2; exit 1; }

# 防止“只重打了 app、没有重打 sidecar”：渲染层会出现新按钮，而 Python 侧还是旧接口
# （典型症状：点暂存报 Method Not Allowed / 404）。sidecar 是独立二进制，必须比
# core/ 与 server/ 的源码新。
SIDECAR_BIN="$SIDECAR/sidecar"
if [ -x "$SIDECAR_BIN" ]; then
  STALE_PY="$(find core server -name '*.py' -newer "$SIDECAR_BIN" -print -quit 2>/dev/null || true)"
  if [ -z "$STALE_PY" ] && [ tools/pack/sidecar_entry.py -nt "$SIDECAR_BIN" ]; then
    STALE_PY="tools/pack/sidecar_entry.py"
  fi
  if [ -n "$STALE_PY" ]; then
    echo "❌ sidecar 比 Python 源码旧：$STALE_PY" >&2
    echo "   先运行：bash tools/pack/build_sidecar.sh" >&2
    echo "   然后再执行本脚本；否则新界面会调用旧接口。" >&2
    exit 1
  fi
fi

echo "== 0/7 生成应用图标 =="
# 唯一图标源是 docs/app-icon.png（1024×1024、带 alpha、圆角与投影已烘进图里）。
# 用它重渲染整套 iconset，而不是把某张扁平 PNG 直接转 icns：
# 直接转的话 Finder 在深色背景下会露出白角，或者沿用上一版缓存图。
# 旧波形 logo（docs/archive/logo-waveform.*）只是历史资产，不再参与打包——
# 缺图标必须立刻失败，否则会静默装出一个图标过时的 .app。
if [ ! -f "docs/app-icon.png" ]; then
  echo "❌ 缺少 docs/app-icon.png（应用图标唯一源）；没有它不允许继续装配" >&2
  exit 1
fi
rm -rf "build/pack/icon.iconset"
swift tools/pack/make_icon.swift docs/app-icon.png "build/pack/icon.iconset"
mkdir -p desktop/build
iconutil -c icns "build/pack/icon.iconset" -o desktop/build/icon.icns
# 开发模式（npx electron .）没有 Info.plist，Dock 图标走 desktop/build/icon.png。
# 这里一起刷新，否则改完图标跑开发模式仍是上一次拷进去的旧图。
cp docs/app-icon.png desktop/build/icon.png

echo "== 1/7 复制 Electron 框架 =="
rm -rf "$APP"
mkdir -p "$(dirname "$APP")"
# default_app.asar 是 Electron 的占位应用，会被我们自己的 app 取代；
# 本机策略可能拒绝复制它，允许失败。
cp -R "$ELECTRON_APP" "$APP" || true
rm -rf "$APP/Contents/Resources/default_app.asar"
# Electron 自带的 electron.icns 留着会让 IconServices/Finder 偶尔沿用旧图标；
# 我们的 Info.plist 已经指向 icon.icns，这份完全是噪声。
rm -f "$APP/Contents/Resources/electron.icns"

echo "== 2/7 改名主可执行文件 =="
mv "$APP/Contents/MacOS/Electron" "$APP/Contents/MacOS/KikuSub"

echo "== 3/7 写入 Info.plist =="
# 每次构建给 CFBundleVersion 一个唯一值：Finder/IconServices 会按 bundle 版本
# 缓存图标，版本永远不变时替换了 icon.icns 也可能继续显示旧图。
BUILD_NUMBER="$(date +%Y%m%d%H%M)"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>KikuSub</string>
  <key>CFBundleDisplayName</key><string>KikuSub</string>
  <key>CFBundleExecutable</key><string>KikuSub</string>
  <key>CFBundleIdentifier</key><string>com.kikusub.desktop</string>
  <key>CFBundleVersion</key><string>${BUILD_NUMBER}</string>
  <key>CFBundleShortVersionString</key><string>0.2.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleSignature</key><string>????</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSRequiresAquaSystemAppearance</key><false/>
  <key>LSApplicationCategoryType</key><string>public.app-category.video</string>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>视频</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array><string>public.movie</string><string>org.matroska.mkv</string></array>
    </dict>
    <dict>
      <key>CFBundleTypeName</key><string>字幕</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array><string>public.subtitle</string><string>public.text</string></array>
    </dict>
  </array>
</dict>
</plist>
PLIST

echo "== 4/7 放入应用代码（main + renderer + package.json）=="
mkdir -p "$APP/Contents/Resources/app"
cp -R desktop/main "$APP/Contents/Resources/app/main"
cp -R desktop/renderer/dist "$APP/Contents/Resources/app/renderer-dist"
mkdir -p "$APP/Contents/Resources/app/renderer"
mv "$APP/Contents/Resources/app/renderer-dist" "$APP/Contents/Resources/app/renderer/dist"
# 版本号只有一个来源：desktop/package.json（此前这里硬编码 "0.2.0"，
# 与 package.json 双写，发版时极容易漂移；build_dmg.sh 也用同一个读法）。
APP_VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' desktop/package.json | head -1)"
[ -n "$APP_VERSION" ] || { echo "❌ 无法从 desktop/package.json 读到 version" >&2; exit 1; }
cat > "$APP/Contents/Resources/app/package.json" <<JSON
{
  "name": "kikusub-desktop",
  "version": "$APP_VERSION",
  "private": true,
  "main": "main/main.cjs"
}
JSON
# 随包的 Agent 技能（设置页「一键配置」从这里复制到 ~/.agents/skills/）
if [ -d "desktop/resources/skill" ]; then
  cp -R desktop/resources "$APP/Contents/Resources/app/resources"
else
  echo "⚠️ 缺少 desktop/resources/skill，一键配置按钮会不可用" >&2
fi
cp desktop/build/icon.icns "$APP/Contents/Resources/icon.icns"
cp presets.json "$APP/Contents/Resources/python-presets.json" 2>/dev/null || true

echo "== 5/7 放入 Python sidecar（737 MB，慢）=="
cp -R "$SIDECAR" "$APP/Contents/Resources/python"
cp presets.json "$APP/Contents/Resources/python/presets.json" 2>/dev/null || true

echo "== 6/7 模型目录（本机自用：指向仓库里已下载的 6.6 GB）=="
APPSUP="${KIKUSUB_APP_SUPPORT_DIR:-$HOME/Library/Application Support/KikuSub}"
mkdir -p "$APPSUP"
MODELS_REAL="$(cd "$REPO_ROOT/models" 2>/dev/null && pwd -P || true)"
if [ -n "$MODELS_REAL" ] && [ ! -e "$APPSUP/models" ]; then
  ln -s "$MODELS_REAL" "$APPSUP/models"
  echo "已建立软链：$APPSUP/models -> $MODELS_REAL"
elif [ -e "$APPSUP/models" ]; then
  echo "已存在：$APPSUP/models（保持不动）"
else
  echo "⚠️ 仓库里没有 models/，首次转写会触发下载"
fi

echo "== 7/7 自签 =="
# 用 ad-hoc 签名即可：AI 密钥走本机加密（见 desktop/main/aikey.cjs），**不依赖钥匙串**，
# 所以"每次重打包 cdhash 变化"没有副作用。换成固定证书只在需要钥匙串/公证时才值得。
codesign --force --deep --sign - "$APP" 2>&1 | tail -3 || echo "（自签失败，本机运行通常也能启动）"

# 重新打包后 Finder/LaunchServices 仍可能缓存旧图标；touch + 重新注册能强制刷新。
# 如果用户眼前的 Finder 窗口还是旧图，执行 tools/pack/refresh_finder_icon.sh。
touch "$APP"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREGISTER" ] && "$LSREGISTER" -f -R -trusted "$APP" >/dev/null 2>&1 || true

echo
echo "完成：$APP"
du -sh "$APP"
