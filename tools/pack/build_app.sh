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

source tools/pack/_rmtree.sh

APP="build/pack/KikuSub.app"
ELECTRON_APP="desktop/node_modules/electron/dist/Electron.app"
SIDECAR="build/pack/dist/sidecar"
CLI="build/pack/dist/kikusub"
# onedir CLI 的免解压运行时；必须和可执行文件成对装配，否则启动会找不到 Python。
CLI_LIB="build/pack/dist/kikusub-internal"

[ -d "$ELECTRON_APP" ] || { echo "缺少 Electron：cd desktop && npm install" >&2; exit 1; }
[ -d "$SIDECAR" ] || { echo "缺少 sidecar：先跑 build_sidecar.sh" >&2; exit 1; }
[ -x "$CLI" ] || { echo "缺少 kikusub CLI：先跑 build_cli.sh" >&2; exit 1; }
[ -d "$CLI_LIB" ] || { echo "缺少 kikusub 运行时目录 ${CLI_LIB}：先跑 build_cli.sh" >&2; exit 1; }
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

# CLI 也必须比源码新：`kikusub` 是独立二进制，旧版会跟新 sidecar 的接口对不上。
if [ -x "$CLI" ]; then
  STALE_CLI="$(find tools/kikusub -name '*.py' -newer "$CLI" -print -quit 2>/dev/null || true)"
  if [ -n "$STALE_CLI" ]; then
    echo "❌ kikusub CLI 比源码旧：$STALE_CLI" >&2
    echo "   先运行：bash tools/pack/build_cli.sh" >&2
    exit 1
  fi
fi

echo "== 0/8 生成应用图标 =="
# 唯一图标源是 docs/app-icon.png（1024×1024、带 alpha、圆角与投影已烘进图里）。
# 用它重渲染整套 iconset，而不是把某张扁平 PNG 直接转 icns：
# 直接转的话 Finder 在深色背景下会露出白角，或者沿用上一版缓存图。
# 旧波形 logo（docs/archive/logo-waveform.*）只是历史资产，不再参与打包——
# 缺图标必须立刻失败，否则会静默装出一个图标过时的 .app。
if [ ! -f "docs/app-icon.png" ]; then
  echo "❌ 缺少 docs/app-icon.png（应用图标唯一源）；没有它不允许继续装配" >&2
  exit 1
fi
rm_tree "build/pack/icon.iconset"
swift tools/pack/make_icon.swift docs/app-icon.png "build/pack/icon.iconset"
mkdir -p desktop/build
iconutil -c icns "build/pack/icon.iconset" -o desktop/build/icon.icns
# 开发模式（npx electron .）没有 Info.plist，Dock 图标走 desktop/build/icon.png。
# 这里一起刷新，否则改完图标跑开发模式仍是上一次拷进去的旧图。
cp docs/app-icon.png desktop/build/icon.png

echo "== 1/8 复制 Electron 框架 =="
# 旧实例还在跑时 rm -rf 会把它的 cwd 和正在读的文件一起抽走：sidecar 是 detached 的，
# 父进程退出它不会跟着死，之后它每一次 os.getcwd() 都是 ENOENT——torch 在 import 期
# 就会踩（torch/_dynamo/config.py: default_debug_dir_root），于是界面上只剩一句
# "[Errno 2] No such file or directory"，跟视频/模型毫无关系，极难排查。
# rebuild.sh 里也有收尾，但排在这步**之后**；所以这里必须自己挡在前面。
APP_EXE="$APP/Contents/MacOS/KikuSub"
if pgrep -f "$APP_EXE" >/dev/null 2>&1; then
  echo "== 关闭正在运行的旧实例（避免装配时抽掉它的 cwd）=="
  pkill -TERM -f "$APP_EXE" >/dev/null 2>&1 || true
  for _ in $(seq 1 32); do
    pgrep -f "$APP_EXE" >/dev/null 2>&1 || break
    sleep 0.25
  done
  if pgrep -f "$APP_EXE" >/dev/null 2>&1; then
    echo "⚠️ 旧实例没有及时退出（可能停在退出清理面板），强制结束" >&2
    pkill -9 -f "$APP_EXE" >/dev/null 2>&1 || true
    sleep 2
  fi
  if pgrep -f "$APP_EXE" >/dev/null 2>&1; then
    echo "❌ 旧实例仍在运行，拒绝删除 $APP" >&2
    exit 1
  fi
  # 主进程没了也可能留下孤儿 sidecar（detached 进程组）；它会占着模型与日志句柄。
  pkill -TERM -f "$APP/Contents/Resources/python/sidecar" >/dev/null 2>&1 || true
  sleep 1
fi

rm_tree "$APP"
mkdir -p "$(dirname "$APP")"
# default_app.asar 是 Electron 的占位应用，会被我们自己的 app 取代；
# 本机策略可能拒绝复制它，允许失败。
cp -R "$ELECTRON_APP" "$APP" || true
rm -rf "$APP/Contents/Resources/default_app.asar"
# Electron 自带的 electron.icns 留着会让 IconServices/Finder 偶尔沿用旧图标；
# 我们的 Info.plist 已经指向 icon.icns，这份完全是噪声。
rm -f "$APP/Contents/Resources/electron.icns"

echo "== 2/8 改名主可执行文件 =="
mv "$APP/Contents/MacOS/Electron" "$APP/Contents/MacOS/KikuSub"

echo "== 3/8 写入 Info.plist =="
# 版本号只有一个来源：desktop/package.json。Info.plist 的 CFBundleShortVersionString
# 与包内 package.json 必须同值，否则访达「显示简介」、About 面板与 tag 会各说各话
# （0.4.0 发版前这里写死过 "0.2.0"，tests/test_pack_version.py 已加守卫）。
APP_VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' desktop/package.json | head -1)"
[ -n "$APP_VERSION" ] || { echo "❌ 无法从 desktop/package.json 读到 version" >&2; exit 1; }
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
  <key>CFBundleShortVersionString</key><string>${APP_VERSION}</string>
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
# 硬断言：plist 短版本必须等于 package.json。装配阶段就拦住，不等到用户看「显示简介」。
PLIST_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist" 2>/dev/null || true)"
[ "$PLIST_VERSION" = "$APP_VERSION" ] || {
  echo "❌ Info.plist 版本 ${PLIST_VERSION:-<空>} 与 package.json ${APP_VERSION} 不一致" >&2
  exit 1
}

echo "== 4/8 放入应用代码（main + renderer + package.json）=="
mkdir -p "$APP/Contents/Resources/app"
cp -R desktop/main "$APP/Contents/Resources/app/main"
cp -R desktop/renderer/dist "$APP/Contents/Resources/app/renderer-dist"
mkdir -p "$APP/Contents/Resources/app/renderer"
mv "$APP/Contents/Resources/app/renderer-dist" "$APP/Contents/Resources/app/renderer/dist"
# 包内 package.json 用同一个 APP_VERSION（第 3 步已读取并校验过）。
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

echo "== 5/8 放入 Python sidecar（$(du -sh "$SIDECAR" | cut -f1)，慢）=="
cp -R "$SIDECAR" "$APP/Contents/Resources/python"
cp presets.json "$APP/Contents/Resources/python/presets.json" 2>/dev/null || true

# 外部 CLI：**不能放在 Contents/MacOS**。macOS 默认 APFS 大小写不敏感，
# `Contents/MacOS/kikusub` 会解析到主可执行文件 `KikuSub`，`cp` 直接把 Electron
# 主二进制覆盖成 CLI（2026-11-21 实际踩到：装配“成功”、签名通过，
# 但双击启动的是 CLI）。放在 Resources/bin，和 ffmpeg 同一层；设置页负责软链。
#
# onedir 产物是「可执行文件 + kikusub-internal/ 免解压运行时」一对。onefile 会把
# 运行时塞进单文件、每次启动再解压到临时目录，实测 --help 要 4.5–9.6s；这里必须
# 两个一起复制，否则 `~/.local/bin/kikusub` 启动会找不到 libpython。
mkdir -p "$APP/Contents/Resources/bin"
cp "$CLI" "$APP/Contents/Resources/bin/kikusub"
rm_tree "$APP/Contents/Resources/bin/kikusub-internal"
cp -R "$CLI_LIB" "$APP/Contents/Resources/bin/kikusub-internal"
chmod 755 "$APP/Contents/Resources/bin/kikusub"
# 运行时里的 dylib/.so 已由 PyInstaller 自签；主可执行文件单独补签。
codesign --force --sign - "$APP/Contents/Resources/bin/kikusub" >/dev/null 2>&1 || true
echo "已内置 CLI：$(du -h "$APP/Contents/Resources/bin/kikusub" | cut -f1) + 运行时 $(du -sh "$APP/Contents/Resources/bin/kikusub-internal" | cut -f1)"

echo "== 6/8 放入内置 ffmpeg / ffprobe（没有 Homebrew 也能导入视频）=="
# 为什么要随包：macOS 不自带 ffmpeg，而从访达启动的 .app 只拿到
# /usr/bin:/bin:/usr/sbin:/sbin，Homebrew 的 /opt/homebrew/bin 不在里面——今天
# 用户的第一道门槛就是「brew install ffmpeg」。内置这一份以后，下载 .app 双击即可用。
# 核心的查找顺序在 core/paths.py（包内 bin → 系统 PATH），主进程在 main.cjs 里
# 把同一个目录前置进 sidecar 的 PATH。
BUNDLED_SRC="build/pack/vendor/ffmpeg"
BUNDLED_DST="$APP/Contents/Resources/bin"
if [ -x "$BUNDLED_SRC/bin/ffmpeg" ] && [ -x "$BUNDLED_SRC/bin/ffprobe" ]; then
  mkdir -p "$BUNDLED_DST"
  cp "$BUNDLED_SRC/bin/ffmpeg" "$BUNDLED_SRC/bin/ffprobe" "$BUNDLED_DST/"
  chmod 755 "$BUNDLED_DST/ffmpeg" "$BUNDLED_DST/ffprobe"
  # GPLv3：分发二进制就必须带上许可全文与来源/校验信息。
  cp tools/pack/ffmpeg-COPYING.GPLv3.txt "$BUNDLED_DST/LICENSE-ffmpeg-GPLv3.txt"
  cp "$BUNDLED_SRC/NOTICE.txt" "$BUNDLED_DST/NOTICE-ffmpeg.txt"
  # 先单独签这两个二进制：它们在 Resources/ 下，`codesign --deep` 不保证会扫到，
  # 而 .app 的整体签名会把它们当普通资源封存——不签的嵌套 Mach-O 会让
  # `codesign --verify --strict` 报「code object is not signed at all」。
  codesign --force --sign - "$BUNDLED_DST/ffmpeg" >/dev/null 2>&1 || true
  codesign --force --sign - "$BUNDLED_DST/ffprobe" >/dev/null 2>&1 || true
  echo "已内置：$(du -sh "$BUNDLED_DST" | cut -f1)（$("$BUNDLED_DST/ffmpeg" -version 2>/dev/null | head -1 | cut -d' ' -f1-3)）"
else
  if [ "${KIKUSUB_REQUIRE_BUNDLED_FFMPEG:-0}" = "1" ]; then
    echo "❌ 缺少内置 ffmpeg/ffprobe（KIKUSUB_REQUIRE_BUNDLED_FFMPEG=1）：先跑 bash tools/pack/fetch_ffmpeg.sh" >&2
    exit 1
  fi
  echo "⚠️ 没有 $BUNDLED_SRC/bin —— 这个 .app 只能在装了 ffmpeg 的机器上用。" >&2
  echo "   要做出「双击即用」的包：bash tools/pack/fetch_ffmpeg.sh" >&2
fi

echo "== 7/8 模型目录（本机自用：指向仓库里已下载的 6.6 GB）=="
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

# 硬断言：主可执行文件必须还是 Electron 那一份。Electron 的主二进制只有 33KB
# （真正的框架在 Frameworks/），所以不能按体积判断；用逐字节比较最可靠。
# 放在 MacOS 下的 CLI 会被大小写不敏感文件系统当成同一个文件，把 App 静默换成
# CLI——这里必须在签名前拦住。
if ! cmp -s "$APP/Contents/MacOS/KikuSub" "$ELECTRON_APP/Contents/MacOS/Electron"; then
  echo "❌ 主可执行文件与 Electron 不一致，疑似被覆盖（大小写冲突）" >&2
  exit 1
fi
[ -x "$APP/Contents/Resources/bin/kikusub" ] || { echo "❌ 缺少包内 CLI" >&2; exit 1; }
[ -d "$APP/Contents/Resources/bin/kikusub-internal" ] || { echo "❌ 缺少包内 CLI 运行时" >&2; exit 1; }

echo "== 8/8 自签 =="
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
