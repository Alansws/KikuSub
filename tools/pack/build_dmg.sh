#!/usr/bin/env bash
# 把已装配好的 KikuSub.app 打成可分发的 DMG（带卷图标）。
#
#   bash tools/pack/build_dmg.sh                  # 用 desktop/package.json 的版本
#   VERSION=0.1.1 bash tools/pack/build_dmg.sh    # 临时指定版本
#   bash tools/pack/build_dmg.sh --no-sign        # 跳过 DMG 自签
#
# 前置：先跑 tools/pack/rebuild.sh（或 build_sidecar.sh + npm run build + build_app.sh），
# 确认 build/pack/KikuSub.app 是最新的。这里只做「装盘」，不重新编译任何东西。
#
# 为什么用 hdiutil 而不是 electron-builder：本项目手工装配 .app（见 build_app.sh 顶部说明），
# 只需要一个 UDZO 压缩镜像；hdiutil 是系统自带的，不引入额外依赖。
#
# 卷图标：直接 create -srcfolder 出来的 dmg，在访达里是一个白色通用磁盘。
# 先做 UDRW 中间镜像 → 挂载 → 放 .VolumeIcon.icns + SetFile -a C → 卸载 → 转 UDZO，
# 下载后的 .dmg 才会显示应用图标（和 .app 用同一张 docs/app-icon.png）。
#
# 产出：build/pack/dist/KikuSub-<version>-<arch>.dmg
#
# 注意：应用是 ad-hoc 签名、未经公证。从浏览器下载后 Gatekeeper 会拦一次，
# 用户需要右键「打开」，或执行 xattr -dr com.apple.quarantine /Applications/KikuSub.app。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

APP="build/pack/KikuSub.app"
SIGN_DMG=1
for arg in "$@"; do
  case "$arg" in
    --no-sign) SIGN_DMG=0 ;;
    -h|--help)
      sed -n '2,24p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数：$arg" >&2
      exit 2
      ;;
  esac
done

if [ ! -d "$APP" ]; then
  echo "❌ 缺少 $APP：先运行 bash tools/pack/rebuild.sh --no-open" >&2
  exit 1
fi

VERSION="${VERSION:-$(../.venv/bin/python -c 'import json;print(json.load(open("desktop/package.json"))["version"])' 2>/dev/null || true)}"
if [ -z "$VERSION" ]; then
  VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' desktop/package.json | head -1)"
fi
[ -n "$VERSION" ] || { echo "❌ 无法确定版本号，请传 VERSION=x.y.z" >&2; exit 1; }

ARCH="$(uname -m)"
OUT="build/pack/dist/KikuSub-${VERSION}-${ARCH}.dmg"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/kikusub-dmg.XXXXXX")"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/kikusub-dmgwork.XXXXXX")"
VOLUME=""
cleanup() {
  [ -n "$VOLUME" ] && hdiutil detach "$VOLUME" >/dev/null 2>&1 || true
  rm -rf "$STAGE" "$WORK"
}
trap cleanup EXIT

echo "== 1/4 准备磁盘内容 =="
# ditto 保留扩展属性与符号链接；cp -R 会丢掉部分元数据，签名可能因此失效。
ditto "$APP" "$STAGE/KikuSub.app"
[ -L "$STAGE/Applications" ] || ln -s /Applications "$STAGE/Applications"

echo "== 2/4 准备卷图标 =="
ICON_SRC="docs/app-icon.png"
ICNS="desktop/build/icon.icns"
HAVE_VOLICON=0
if [ -f "$ICON_SRC" ]; then
  if [ ! -f "$ICNS" ] || [ "$ICON_SRC" -nt "$ICNS" ]; then
    swift tools/pack/make_icon.swift "$ICON_SRC" "$WORK/icon.iconset"
    mkdir -p desktop/build
    iconutil -c icns "$WORK/icon.iconset" -o "$ICNS"
  fi
  cp "$ICNS" "$STAGE/.VolumeIcon.icns"
  HAVE_VOLICON=1
else
  echo "⚠️ 缺少 $ICON_SRC，dmg 会退回通用磁盘图标" >&2
fi

echo "== 3/4 生成读写镜像并写入卷图标 =="
mkdir -p "$(dirname "$OUT")"
RW_IMG="$WORK/KikuSub.rw.dmg"
rm -f "$OUT"
hdiutil create \
  -volname "KikuSub" \
  -srcfolder "$STAGE" \
  -ov \
  -format UDRW \
  "$RW_IMG" >/dev/null

if [ "$HAVE_VOLICON" = "1" ]; then
  VOLUME="$(hdiutil attach -nobrowse -noautoopen "$RW_IMG" | tail -1 | awk '{print $NF}')"
  if [ -d "$VOLUME" ]; then
    cp "$ICNS" "$VOLUME/.VolumeIcon.icns"
    # 只有卷根目录带 kHasCustomIcon 位，访达才会把卷图标用于 .dmg 文件本身。
    SetFile -a C "$VOLUME" || echo "⚠️ SetFile -a C 失败，卷图标可能不生效" >&2
    sync
    hdiutil detach "$VOLUME" >/dev/null && VOLUME=""
  else
    echo "⚠️ 挂载读写镜像失败，跳过卷图标" >&2
  fi
fi

hdiutil convert "$RW_IMG" -format UDZO -imagekey zlib-level=9 -ov -o "$OUT" >/dev/null
rm -f "$RW_IMG"

if [ "$SIGN_DMG" = "1" ]; then
  echo "== 4/4 自签 DMG =="
  codesign --force --sign - "$OUT" 2>&1 | tail -2 || echo "（DMG 自签失败，不影响挂载）"
fi

echo
echo "完成：$OUT"
du -sh "$OUT"
