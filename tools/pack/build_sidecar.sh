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

# Finder 可能在 build/pack 里写 `.DS_Store`，`rm -rf` 会因此在 rmdir 时失败
# （见 _rmtree.sh 顶部注释）。所有大目录清理都走 rm_tree。
source tools/pack/_rmtree.sh

PYTHON="${PYTHON:-../.venv/bin/python}"
NAME="sidecar"
OUT="build/pack"

"$PYTHON" -c "import PyInstaller" 2>/dev/null || {
  echo "缺少 PyInstaller：uv pip install --python $PYTHON pyinstaller" >&2
  exit 1
}

# PyInstaller 默认把二进制缓存写到 ~/Library/Application Support/pyinstaller。
# 本机文件策略不允许写那里，COLLECT 阶段会 PermissionError。把缓存钉在工作区内。
export PYINSTALLER_CONFIG_DIR="$REPO_ROOT/$OUT/.pyinstaller"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

rm_tree "$OUT/dist/$NAME" "$OUT/work/$NAME"

# 人声分离只用 demucs.pretrained/apply；--collect-data 带 remote 权重索引。
# torchvision/onnx/ml_dtypes/Cython 是实验环境的可选包，运行时不参与；
# torchvision 若被打进冻结包，会让 transformers.image_utils 导入失败。
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
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --hidden-import PIL.ImageFont \
  --hidden-import omnivoice \
  --hidden-import omnivoice.models.omnivoice \
  --hidden-import sherpa_onnx \
  --collect-all sherpa_onnx \
  --hidden-import onnxruntime \
  --collect-all onnxruntime \
  --collect-all jieba \
  --collect-data demucs \
  --collect-data certifi \
  --hidden-import core.separate \
  --hidden-import demucs.pretrained \
  --hidden-import demucs.apply \
  --hidden-import demucs.repo \
  --hidden-import demucs.states \
  --hidden-import demucs.htdemucs \
  --hidden-import demucs.hdemucs \
  --hidden-import demucs.demucs \
  --hidden-import demucs.spec \
  --hidden-import demucs.transformer \
  --hidden-import demucs.utils \
  --hidden-import openunmix.filtering \
  --hidden-import dora.log \
  --hidden-import julius \
  --hidden-import einops \
  --hidden-import omegaconf \
  --exclude-module torchcodec \
  --exclude-module torchvision \
  --exclude-module onnx \
  --exclude-module ml_dtypes \
  --exclude-module Cython \
  --exclude-module matplotlib \
  --exclude-module tkinter \
  --distpath "$OUT/dist" \
  --workpath "$OUT/work" \
  --specpath "$OUT" \
  tools/pack/sidecar_entry.py

echo
echo "构建完成：$OUT/dist/$NAME"
du -sh "$OUT/dist/$NAME"
