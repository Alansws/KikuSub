#!/usr/bin/env bash
# 下载「随 .app 分发」的静态 arm64 ffmpeg / ffprobe（Step 7）。
#
#   bash tools/pack/fetch_ffmpeg.sh          # 下载到 build/pack/vendor/ffmpeg/bin/
#   bash tools/pack/fetch_ffmpeg.sh --force  # 已存在也重下
#
# 为什么是下载而不是入库：两个二进制合计约 130 MB，进 git 会让每次 clone 都是
# 一场灾难。版本、来源、sha256 全部钉死在本脚本里，校验不过就不落盘——「来源清晰」
# 指的是这里：谁编译的、哪个版本、什么许可，都写在同目录生成的 NOTICE.txt 里，
# 装配时一起拷进 .app（见 build_app.sh 第 6 步）。
#
# 来源：Martin Riedl 的 FFmpeg Build Server（https://ffmpeg.martin-riedl.de/）。
# 静态链接（只依赖 macOS 系统框架）、Developer ID 签名 + 公证、含 x264/x265/libass。
# 许可：GPLv3（`--enable-gpl --enable-version3`），全文见 tools/pack/ffmpeg-COPYING.GPLv3.txt。
#
# 为什么不用 Homebrew 的 ffmpeg：那是动态库版本，拷进别的机器 / 别的 .app 里
# 会因为 dylib 路径（/opt/homebrew/opt/…）找不到而直接起不来。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------- 钉死的版本
FFMPEG_VERSION="9.1"
# 构建时间戳 + 版本号，服务器用它给每次构建一个固定 URL（不会随「最新版」漂移）。
BUILD_DIR="1795207104_9.1"
BASE_URL="https://ffmpeg.martin-riedl.de/download/macos/arm64/${BUILD_DIR}"
# zip 的 sha256，与服务器同目录的 *.zip.sha256 一致；同时写死在这里，
# 防止「服务器被换掉」时我们跟着信任一份陌生的二进制。
FFMPEG_ZIP_SHA256="1f66e9a690a7f1c9e60b012379f8869c11818d1797f45b21dbb2f2564ba61ae1"
FFPROBE_ZIP_SHA256="6ef2df5f575042923a28537ab37adf936f28bf3e7b85de23a1447ed447ec1dbd"

OUT_DIR="$REPO_ROOT/build/pack/vendor/ffmpeg"
BIN_DIR="$OUT_DIR/bin"
STAMP="$OUT_DIR/.fetched"

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

if [ "$FORCE" = "0" ] && [ -x "$BIN_DIR/ffmpeg" ] && [ -x "$BIN_DIR/ffprobe" ] \
   && [ "$(cat "$STAMP" 2>/dev/null || true)" = "$FFMPEG_VERSION" ]; then
  echo "已存在内置 ffmpeg ${FFMPEG_VERSION}：${BIN_DIR}（--force 可重下）"
  du -sh "$BIN_DIR"
  exit 0
fi

[ "$(uname -s)" = "Darwin" ] || { echo "这个脚本只服务 macOS 打包" >&2; exit 1; }
[ "$(uname -m)" = "arm64" ] || {
  echo "内置二进制是 arm64；当前机器是 $(uname -m)，无法用于本机打包验收" >&2
  exit 1
}

mkdir -p "$OUT_DIR"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/kikusub-ffmpeg.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

fetch() {
  local url="$1" dest="$2"
  echo "  ← $url"
  # 这台机器上直连偶发 SSL_ERROR_SYSCALL（长下载被中间设备掐断），
  # 断点续传 + 重试比「再跑一次脚本」可靠。
  curl -fSL --retry 5 --retry-all-errors --http1.1 -C - -o "$dest" "$url"
}

verify() {
  local file="$1" expected="$2" label="$3"
  local actual
  actual="$(shasum -a 256 "$file" | awk '{print $1}')"
  if [ "$actual" != "$expected" ]; then
    echo "❌ ${label} sha256 不符" >&2
    echo "   期望 $expected" >&2
    echo "   实际 $actual" >&2
    echo "   拒绝使用来历不明的二进制；检查下载源是否被改过。" >&2
    exit 1
  fi
}

echo "== 下载 FFmpeg ${FFMPEG_VERSION}（macOS arm64 静态构建）=="
fetch "$BASE_URL/ffmpeg.zip" "$TMP/ffmpeg.zip"
fetch "$BASE_URL/ffprobe.zip" "$TMP/ffprobe.zip"
verify "$TMP/ffmpeg.zip" "$FFMPEG_ZIP_SHA256" "ffmpeg.zip"
verify "$TMP/ffprobe.zip" "$FFPROBE_ZIP_SHA256" "ffprobe.zip"

echo "== 解包 =="
( cd "$TMP" && unzip -q -o ffmpeg.zip && unzip -q -o ffprobe.zip )
rm -rf "$BIN_DIR"
mkdir -p "$BIN_DIR"
mv "$TMP/ffmpeg" "$TMP/ffprobe" "$BIN_DIR/"
chmod 755 "$BIN_DIR/ffmpeg" "$BIN_DIR/ffprobe"

# 架构与「能不能在这台机器上跑」双重确认：manifest 写错或拿到 Intel 包时，
# 这一步会在真正装配 .app 之前失败。
for tool in ffmpeg ffprobe; do
  file "$BIN_DIR/$tool" | grep -q "arm64" || {
    echo "❌ $BIN_DIR/$tool 不是 arm64" >&2
    exit 1
  }
  # 故意清掉环境：证明它不依赖 Homebrew 的 dylib / PATH
  env -i PATH=/usr/bin:/bin "$BIN_DIR/$tool" -version >/dev/null || {
    echo "❌ $BIN_DIR/$tool 无法独立运行（不是静态构建？）" >&2
    exit 1
  }
done

FFMPEG_SHA256="$(shasum -a 256 "$BIN_DIR/ffmpeg" | awk '{print $1}')"
FFPROBE_SHA256="$(shasum -a 256 "$BIN_DIR/ffprobe" | awk '{print $1}')"
FFMPEG_SIZE="$(stat -f%z "$BIN_DIR/ffmpeg")"
FFPROBE_SIZE="$(stat -f%z "$BIN_DIR/ffprobe")"

cat > "$OUT_DIR/NOTICE.txt" <<NOTICE
KikuSub 随包内置的 FFmpeg 静态二进制
=====================================

版本        : FFmpeg ${FFMPEG_VERSION}（macOS arm64 / 静态链接）
构建来源    : Martin Riedl's FFmpeg Build Server
              https://ffmpeg.martin-riedl.de/
下载地址    : ${BASE_URL}/
下载日期    : $(date '+%Y-%m-%d %H:%M:%S %z')
构建配置    : --enable-gpl --enable-version3 --pkg-config-flags=--static
              （含 libx264 / libx265 / libass / libfreetype / libvpx / libopus 等，
                完整清单见 \`ffmpeg -version\` 第一段）
许可        : GPL v3 —— 全文见随包 LICENSE-ffmpeg-GPLv3.txt，
              上游源码 https://ffmpeg.org/download.html
              该构建的编译脚本 https://git.martin-riedl.de/ffmpeg/build-script
签名        : 上游以 Developer ID（Martin Riedl, KU3N25YGLU）签名；装配 KikuSub.app
              时会被 ad-hoc 重新签名，与主程序一致。

校验（sha256）
-------------
ffmpeg.zip  ${FFMPEG_ZIP_SHA256}
ffprobe.zip ${FFPROBE_ZIP_SHA256}
bin/ffmpeg  ${FFMPEG_SHA256}  (${FFMPEG_SIZE} bytes)
bin/ffprobe ${FFPROBE_SHA256}  (${FFPROBE_SIZE} bytes)

为什么要随包：macOS 不自带 ffmpeg，而从访达启动的 .app 拿不到 Homebrew 的
/opt/homebrew/bin。内置这一份以后，没装过 Homebrew 的用户下载 .app 双击即可导入视频。
NOTICE

echo "$FFMPEG_VERSION" > "$STAMP"

echo
echo "== 完成 =="
echo "  $BIN_DIR"
du -sh "$BIN_DIR"
"$BIN_DIR/ffmpeg" -version | head -1
"$BIN_DIR/ffprobe" -version | head -1
