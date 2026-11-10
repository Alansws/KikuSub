#!/usr/bin/env bash
# 构建 Python sidecar（onedir）。
#
# 为什么必须 onedir：onefile 每次启动都要把 ~700 MB 解压到临时目录，
# 冷启动会从 0.5 s 劣化到 10 s+。
#
# 产物：build/pack/dist/sidecar/sidecar
# 最终会被放进 KikuSub.app/Contents/Resources/python/

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-../.venv/bin/python}"
NAME="sidecar"
OUT="build/pack"

"$PYTHON" -c "import PyInstaller" 2>/dev/null || {
  echo "缺少 PyInstaller：uv pip install --python $PYTHON pyinstaller" >&2
  exit 1
}

rm -rf "$OUT/dist/$NAME"

"$PYTHON" -m PyInstaller \
  --noconfirm \
  --onedir \
  --name "$NAME" \
  --paths . \
  --collect-data silero_vad \
  --hidden-import websockets \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  --exclude-module gradio \
  --exclude-module matplotlib \
  --exclude-module tkinter \
  --distpath "$OUT/dist" \
  --workpath "$OUT/work" \
  --specpath "$OUT" \
  tools/pack/sidecar_entry.py

echo
echo "构建完成：$OUT/dist/$NAME"
du -sh "$OUT/dist/$NAME"
