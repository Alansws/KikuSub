#!/usr/bin/env bash
# 打 `kikusub` 外部 CLI（PyInstaller onedir，**绝不用 onefile**）。
#
# 为什么不能用 onefile：onefile 每次启动都要把内嵌的 CPython 运行时解压到临时目录，
# 然后系统还要对每个新解压出来的 Mach-O 重新做一次校验。实测（M4 Pro、8.2 MB 产物）：
#   time kikusub --help   → real 4.7–9.6s（user 仅 0.15s，时间全花在解压/校验）
#   time kikusub project  → real 4.5–6.1s
# 换成 onedir 后是「免解压」：启动只做 dylib 加载，实测 ~0.06s。
#
# 产物：
#   build/pack/dist/kikusub              ← 可执行文件（设置页软链的入口）
#   build/pack/dist/kikusub-internal/    ← 解压态运行时（Python + stdlib + dylib）
# 两者一起装配进 KikuSub.app/Contents/Resources/bin/，所以 `~/.local/bin/kikusub`
# 直接指向真实可执行文件即可，不需要包装脚本，也不依赖系统 Python。
#
#   bash tools/pack/build_cli.sh
#   PYTHON=python3.12 bash tools/pack/build_cli.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

source tools/pack/_rmtree.sh

PYTHON="${PYTHON:-../.venv/bin/python}"
NAME="kikusub"
# PyInstaller 6 的 --contents-directory：运行时目录叫这个，紧挨着可执行文件。
# 名字带 kikusub 前缀，装进 Resources/bin 后和 ffmpeg / ffprobe 不会混淆。
CONTENTS="$NAME-internal"
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
# PyInstaller 的 onedir 产物固定是「dist/<name>/<exe> + dist/<name>/<contents>/」这一层
# 包装目录；我们先收到暂存目录，再把两件产物摊平到 dist/ 下，得到最终布局：
#   dist/kikusub（可执行文件） + dist/kikusub-internal/（运行时）
# 展开的理由：现有 `~/.local/bin/kikusub` 软链指向 app 里的 `Resources/bin/kikusub`
#（一个可执行文件），摊平后软链和开发态路径都不用改。
STAGE="$OUT/dist/.${NAME}-stage"
rm_tree "$STAGE" "$OUT/dist/$NAME" "$OUT/dist/$CONTENTS" "$OUT/work/$NAME"
rm -f "$OUT/$NAME.spec"

echo "== PyInstaller onedir → ${OUT}/dist/${NAME}（运行时 ${CONTENTS}/）=="
"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name "$NAME" \
  --contents-directory "$CONTENTS" \
  --distpath "$STAGE" \
  --workpath "$OUT/work/$NAME" \
  --specpath "$OUT" \
  --paths "$REPO_ROOT" \
  --log-level WARN \
  "$ENTRY"

STAGED_EXE="$STAGE/$NAME/$NAME"
STAGED_LIB="$STAGE/$NAME/$CONTENTS"
[ -x "$STAGED_EXE" ] || { echo "❌ 没有产出可执行文件：$STAGED_EXE" >&2; exit 1; }
[ -d "$STAGED_LIB" ] || { echo "❌ 没有产出运行时目录：$STAGED_LIB" >&2; exit 1; }
mv "$STAGED_EXE" "$OUT/dist/$NAME"
mv "$STAGED_LIB" "$OUT/dist/$CONTENTS"
rm_tree "$STAGE"

BIN="$OUT/dist/$NAME"
LIB="$OUT/dist/$CONTENTS"
[ -x "$BIN" ] || { echo "❌ 没有产出可执行文件：$BIN" >&2; exit 1; }
[ -d "$LIB" ] || { echo "❌ 没有产出运行时目录：$LIB" >&2; exit 1; }

# 自签：它会被放进 .app 的 Resources/bin，不签会让 `codesign --verify --strict` 失败。
# 运行时里的 dylib/.so 由 PyInstaller 逐个自签，这里只补主可执行文件。
codesign --force --sign - "$BIN" >/dev/null 2>&1 || true
codesign --verify --strict "$BIN" >/dev/null 2>&1 || echo "⚠️ kikusub 自签校验未通过（本机运行通常仍可启动）" >&2

# 冷启动是这次改动的核心指标：构建完顺手量一次，回归时一眼能看见。
HELP_MS="$("$PYTHON" - "$BIN" <<'PY'
import subprocess, sys, time
bin_path = sys.argv[1]
best = None
for _ in range(3):
    started = time.perf_counter()
    subprocess.run([bin_path, "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    elapsed = time.perf_counter() - started
    best = elapsed if best is None else min(best, elapsed)
print(f"{best * 1000:.0f}")
PY
)"
echo "完成：${REPO_ROOT}/${BIN}（可执行 $(du -h "$BIN" | cut -f1) + 运行时 $(du -sh "$LIB" | cut -f1)，--help 最快 ${HELP_MS}ms）"
