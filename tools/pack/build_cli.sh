#!/usr/bin/env bash
# 打 `kikusub` 外部 CLI（PyInstaller onefile）。
#
# 为什么单独打：CLI 必须能脱离仓库与系统 Python 运行（macOS 自带没有 python3）。
# 它只依赖 stdlib，所以 onefile 产物只有 ~10MB；打进 .app 的 Contents/Resources/bin/kikusub（避开 MacOS/KikuSub 大小写冲突）。
#
#   bash tools/pack/build_cli.sh
#   PYTHON=python3.12 bash tools/pack/build_cli.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

source tools/pack/_rmtree.sh

PYTHON="${PYTHON:-../.venv/bin/python}"
NAME="kikusub"
OUT="build/pack"
ENTRY="tools/kikusub/kikusub.py"

[ -f "$ENTRY" ] || { echo "❌ 缺少 $ENTRY" >&2; exit 1; }
"$PYTHON" -c "import PyInstaller" 2>/dev/null || {
  echo "❌ $PYTHON 没有 PyInstaller：pip install pyinstaller" >&2
  exit 1
}

# 和 build_sidecar.sh 同一个原因：PyInstaller 默认把 bincache 放在
# ~/Library/Application Support/pyinstaller，`--clean` 会去删工作区外的缓存；
# 在受限环境里那一步会被拒绝（PermissionError: Operation not permitted）。
export PYINSTALLER_CONFIG_DIR="$REPO_ROOT/$OUT/.pyinstaller"
mkdir -p "$PYINSTALLER_CONFIG_DIR" "$OUT/dist"
rm_tree "$OUT/work/$NAME" "$OUT/dist/$NAME"
rm -f "$OUT/dist/$NAME"
rm -f "$OUT/$NAME.spec"

echo "== PyInstaller onefile → $OUT/dist/$NAME =="
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name "$NAME" \
  --distpath "$OUT/dist" \
  --workpath "$OUT/work/$NAME" \
  --specpath "$OUT" \
  --paths "$REPO_ROOT" \
  --log-level WARN \
  "$ENTRY"

BIN="$OUT/dist/$NAME"
[ -x "$BIN" ] || { echo "❌ 没有产出可执行文件：$BIN" >&2; exit 1; }
# 自签：它会被放进 .app 的 Contents/MacOS，不签会让 `codesign --verify --strict` 失败。
codesign --force --sign - "$BIN" >/dev/null 2>&1 || true

echo "完成：$REPO_ROOT/${BIN}（$(du -h "$BIN" | cut -f1)）"
