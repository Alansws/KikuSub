#!/usr/bin/env bash
# 验收「随包内置的静态 ffmpeg/ffprobe」（界面重构 Step 7）。
#
#   bash tools/pack/verify_bundled_ffmpeg.sh
#   KIKUSUB_STEP7_MEDIA=/path/to/film.mkv bash tools/pack/verify_bundled_ffmpeg.sh
#
# 为什么需要这个脚本：`pytest` 只能证明「解析函数按写好的顺序返回路径」，证明不了
# **打包后的 sidecar 在真实的、没有 Homebrew 的 PATH 下**真的能用包内二进制导入视频。
# Step 7 第一版就翻过车——PyInstaller onedir 下 `core/paths.py` 的 `__file__` 比源码
# 布局深一层，解析到了 `Resources/python/bin`（不存在）。只有把 PATH 清成
# `/usr/bin:/bin:/usr/sbin:/sbin` 并把打包产物真跑一遍，才会暴露。
#
# 前置：`bash tools/pack/rebuild.sh --no-open`（装配出 build/pack/KikuSub.app）。
# 全程无窗口：只起 sidecar、只读 HTTP 接口，不打开 .app。
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$REPO/build/pack/KikuSub.app"
SIDE="$APP/Contents/Resources/python/sidecar"
BIN="$APP/Contents/Resources/bin"
CLEAN_PATH="/usr/bin:/bin:/usr/sbin:/sbin"
TMP="$(mktemp -d /tmp/kikusub-bundled-ffmpeg.XXXXXX)"

for tool in "$SIDE" "$BIN/ffmpeg" "$BIN/ffprobe"; do
  if [ ! -x "$tool" ]; then
    echo "❌ 缺少 $tool" >&2
    echo "   先装配：bash tools/pack/fetch_ffmpeg.sh && bash tools/pack/rebuild.sh --no-open" >&2
    exit 1
  fi
done

PY="${PYTHON:-$REPO/../.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"

fail=0
ok() { printf '  ✅ %s\n' "$1"; }
bad() { printf '  ❌ %s\n' "$1"; fail=$((fail + 1)); }

echo "== 1) 干净 PATH 里确实没有 ffmpeg =="
env -i PATH="$CLEAN_PATH" /bin/sh -c 'command -v ffmpeg' >/dev/null 2>&1 \
  && bad "干净 PATH 里居然有 ffmpeg，本脚本的前提不成立" \
  || ok "PATH=${CLEAN_PATH}（没有 Homebrew）"

echo "== 2) 起打包后的 sidecar，全程只用这份 PATH =="
env -i PATH="$CLEAN_PATH" HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" LANG=zh_CN.UTF-8 \
  KIKUSUB_OUTPUT_DIR="$TMP/out" KIKUSUB_MODELS_DIR="$TMP/models" \
  KIKUSUB_PRESETS_PATH="$TMP/presets.json" KIKUSUB_SETTINGS_PATH="$TMP/settings.json" \
  "$SIDE" --port 0 > "$TMP/stdout.log" 2> "$TMP/stderr.log" &
PID=$!
trap 'kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null' EXIT

for _ in $(seq 1 300); do
  head -1 "$TMP/stdout.log" 2>/dev/null | grep -q '"event"' && break
  sleep 0.2
done
READY="$(head -1 "$TMP/stdout.log")"
PORT="$(printf '%s' "$READY" | sed -n 's/.*"port": *\([0-9]*\).*/\1/p')"
TOKEN="$(printf '%s' "$READY" | sed -n 's/.*"token": *"\([^"]*\)".*/\1/p')"
if [ -z "$PORT" ] || [ -z "$TOKEN" ]; then
  bad "sidecar 没起来（端口/token 为空）"
  tail -20 "$TMP/stderr.log" | sed 's/^/     /'
  exit 1
fi
ok "sidecar 已就绪（port=${PORT}）"
AUTH="Authorization: Bearer $TOKEN"

echo "== 3) /api/settings 必须指向包内 ffmpeg（source=bundled）=="
curl -s -H "$AUTH" "http://127.0.0.1:$PORT/api/settings" > "$TMP/settings.json"
"$PY" - "$TMP/settings.json" "$BIN/ffmpeg" <<'PY' || fail=$((fail + 1))
import json
import sys

data = json.load(open(sys.argv[1]))
expected = sys.argv[2]
info = data.get("ffmpeg") or {}
print("  path   :", info.get("path"))
print("  source :", info.get("source"))
print("  version:", (info.get("version") or "")[:70])
ok = info.get("ok") and info.get("path") == expected and info.get("source") == "bundled"
print("  " + ("✅ 用的是包内 ffmpeg" if ok else "❌ 不是包内 ffmpeg"))
raise SystemExit(0 if ok else 1)
PY

echo "== 4) 真的跑一次 ffprobe（POST /api/media 会探媒体）=="
MEDIA="${KIKUSUB_STEP7_MEDIA:-}"
if [ -z "$MEDIA" ] || [ ! -f "$MEDIA" ]; then
  # 没有真实片源时用包内 ffmpeg 造一段 2 秒测试片：同样能证明「探得到时长」。
  MEDIA="$TMP/clip.mp4"
  "$BIN/ffmpeg" -y -v error -f lavfi -i "testsrc=size=320x240:rate=10:duration=2" \
    -pix_fmt yuv420p "$MEDIA"
  echo "  （没有传 KIKUSUB_STEP7_MEDIA，改用自造测试片）"
fi
printf '{"path": "%s"}' "$MEDIA" > "$TMP/import.json"
curl -s -H "$AUTH" -H 'Content-Type: application/json' -X POST --data @"$TMP/import.json" \
  "http://127.0.0.1:$PORT/api/media" > "$TMP/media.json"
"$PY" - "$TMP/media.json" <<'PY' || fail=$((fail + 1))
import json
import sys

data = json.load(open(sys.argv[1]))
print("  duration:", data.get("duration"), "| codec:", data.get("video_codec"))
ok = bool(data.get("duration"))
print("  " + ("✅ 包内 ffprobe 工作正常" if ok else f"❌ ffprobe 失败：{data}"))
raise SystemExit(0 if ok else 1)
PY

echo "== 5) 真的跑一次 ffmpeg（缩略图接口）=="
curl -s -H "$AUTH" --get --data-urlencode "path=$MEDIA" --data-urlencode "width=640" \
  "http://127.0.0.1:$PORT/api/media/thumb" -o "$TMP/thumb.jpg" \
  -w '  http=%{http_code} bytes=%{size_download}\n'
SIZE="$(stat -f%z "$TMP/thumb.jpg" 2>/dev/null || echo 0)"
[ "$SIZE" -gt 2048 ] && ok "包内 ffmpeg 生成了缩略图（$SIZE bytes）" || bad "缩略图失败（$SIZE bytes）"

echo "== 6) sidecar 日志里的「运行环境」行 =="
grep -h "运行环境" "$TMP/out/logs/kikusub.log" 2>/dev/null | tail -1 | sed 's/^/  /'

echo
if [ "$fail" = "0" ]; then
  echo "✅ 全部通过：没有 Homebrew 的机器也能用包内 ffmpeg/ffprobe"
  echo "   临时目录：${TMP}（可删）"
else
  echo "❌ 有 $fail 项失败" >&2
  exit 1
fi
