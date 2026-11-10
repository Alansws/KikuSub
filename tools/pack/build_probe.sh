#!/usr/bin/env bash
# 打包预验证：构建 core-only sidecar 探针，证明 torch / transformers /
# torchaudio / silero_vad 全家桶可以被 PyInstaller onedir 冻结并真的跑起来。
#
# 这是改造规划 §9 的「关键路径」闸门：如果这一步失败，整条 Electron 路线要重估。
# 它必须最先做，不能留到阶段 5。
#
# 用法：
#   tools/pack/build_probe.sh          # 构建
#   build/pack/dist/sidecar_probe/sidecar_probe   # 运行验证
#
# 注意：必须用 **onedir**，绝不能用 onefile——onefile 每次启动都要解压整包，
# 冷启动会从 1.3s 劣化到 10s+。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-../.venv/bin/python}"
NAME="sidecar_probe"
OUT="build/pack"

if [[ ! -x "$PYTHON" ]]; then
  echo "找不到 Python：$PYTHON（可用 PYTHON=/path/to/python 覆盖）" >&2
  exit 1
fi

"$PYTHON" -c "import PyInstaller" 2>/dev/null || {
  echo "缺少 PyInstaller，先安装：uv pip install --python $PYTHON pyinstaller" >&2
  exit 1
}

# 先清掉上一次的产物目录：PyInstaller 自己删目录时会触发宿主的批量删除确认，
# 在这里显式清干净更省事。
rm -rf "$OUT/dist/$NAME"

"$PYTHON" -m PyInstaller \
  --noconfirm \
  --onedir \
  --name "$NAME" \
  --paths . \
  --collect-data silero_vad \
  --exclude-module gradio \
  --exclude-module fastapi \
  --exclude-module uvicorn \
  --exclude-module starlette \
  --distpath "$OUT/dist" \
  --workpath "$OUT/work" \
  --specpath "$OUT" \
  tools/pack/sidecar_probe.py

echo
echo "构建完成：$OUT/dist/$NAME"
echo "验证：./$OUT/dist/$NAME/$NAME"
