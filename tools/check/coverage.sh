#!/usr/bin/env bash
# 覆盖率报告（2026-11-13 起）。**不设门槛**——先让"哪块没人管"可见，再谈数字。
#
#   bash tools/check/coverage.sh              # core/ + server/ 的行覆盖
#   bash tools/check/coverage.sh -m integration
#   bash tools/check/coverage.sh tests/test_core.py
#
# 产出：
#   - 终端里是 `term-missing`（每一行未覆盖的代码编号，直接能看到漏在哪）
#   - HTML 明细在 build/coverage/index.html（build/ 已 gitignore）
#
# 为什么不设阈值：本项目大量代码是"模型推理 / ffmpeg 子进程 / Electron 主进程"这类
# 在 CI 里跑不了的路径，硬设一个百分比只会逼人写没意义的测试——正好和方法论里
# "删掉机械化的表面单测"冲突。等结构稳定、真发现问题了再谈门槛。

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# venv 可能在仓库根（新 clone）或工作区根（本机现状），两处都认
PY=""
for cand in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/../.venv/bin/python"; do
  if [ -x "${cand}" ]; then PY="${cand}"; break; fi
done
[ -n "${PY}" ] || PY="$(command -v python3 || true)"
[ -n "${PY}" ] || { echo "找不到 python3" >&2; exit 2; }

if ! "$PY" -c "import pytest_cov" >/dev/null 2>&1; then
  echo "缺少 pytest-cov：$PY -m pip install -r requirements-dev.txt" >&2
  exit 2
fi

OUT="$REPO_ROOT/build/coverage"
mkdir -p "$OUT"

"$PY" -m pytest -q \
  --cov=core \
  --cov=server \
  --cov-report=term-missing \
  --cov-report="html:$OUT" \
  --cov-config=/dev/null \
  "$@"

echo ""
echo "HTML 明细：$OUT/index.html"
