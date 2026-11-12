#!/usr/bin/env bash
# 发版前置检查 —— 把"发版前确认"从三句口头要求变成可执行的闸门。
#
#   bash tools/release/preflight.sh                 # 快速检查（默认约 2 秒）
#   bash tools/release/preflight.sh --with-tests    # 加跑 pytest 全量（约 45 秒）
#   bash tools/release/preflight.sh --no-fast-tests # 连 npm test:main 也不跑（CI 已跑时用）
#
# 检查项：工作区干净、版本号格式、tag 是否已存在（"没改版本号不许发"）、HEAD 是否已合入
# main（主线口径）、package-lock 一致、sidecar 新鲜度、渲染层产物、应用图标尺寸、
# ruff 与主进程用例。
#
# 退出码：0 全部通过；1 有阻塞项（**不许发版**）；2 参数错误。
# 规范见 docs/release.md；检查项与"谁负责"的对照表在 §7。

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

WITH_TESTS=0
FAST_TESTS=1
for arg in "$@"; do
  case "$arg" in
    --with-tests) WITH_TESTS=1 ;;
    --no-fast-tests) FAST_TESTS=0 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

FAIL=0
pass() { printf '  ✅ %s\n' "$1"; }
warn() { printf '  ⚠️  %s\n' "$1"; }
fail() { printf '  ❌ %s\n' "$1"; FAIL=$((FAIL + 1)); }

# 优先用工作区根的 venv（本项目约定：venv 在工作区根，不在 repo/ 里）
if [ -x "../.venv/bin/python" ]; then
  PY="../.venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi

echo "== 发版前置检查（$(basename "${REPO_ROOT}")）=="

# ---------------------------------------------------------------- 1. 工作区
echo
echo "[1/8] 工作区"
if [ -n "$(git status --porcelain)" ]; then
  fail "有未提交改动（发版必须从一个干净的工作区出发）："
  git status --short | sed 's/^/       /'
else
  pass "工作区干净"
fi

# ---------------------------------------------------------------- 2. 版本号
echo
echo "[2/8] 版本号"
VERSION=""
if [ -n "${PY}" ]; then
  VERSION="$("${PY}" - <<'PY'
import json, sys
try:
    print(json.load(open("desktop/package.json", encoding="utf-8"))["version"])
except Exception:
    sys.exit(1)
PY
)"
fi
if [ -z "${VERSION}" ]; then
  fail "读不到 desktop/package.json 的 version（唯一版本来源）"
elif printf '%s' "${VERSION}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  pass "version = ${VERSION}（tag 应为 v${VERSION}）"
else
  fail "version 不是 x.y.z：${VERSION}"
fi

# ---------------------------------------------------------------- 3. tag 是否已发过
echo
echo "[3/8] 版本号是否已发过"
if [ -z "${VERSION}" ]; then
  warn "版本号未知，跳过"
elif git rev-parse -q --verify "refs/tags/v${VERSION}" >/dev/null; then
  fail "tag v${VERSION} 已存在 —— 没改版本号不许发；先 bump desktop/package.json"
  TAG_SHA="$(git rev-list -n1 "v${VERSION}")"
  printf '       tag 指向：%s\n' "$(git log -1 --format='%h %s' "${TAG_SHA}")"
else
  pass "v${VERSION} 尚未发布"
fi

# ---------------------------------------------------------------- 4. 主线口径
echo
echo "[4/8] 是否已合入主线（main）"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '(detached)')"
if ! git rev-parse -q --verify refs/heads/main >/dev/null; then
  warn "本地没有 main 分支，跳过（发版必须从 main 打 tag）"
elif git merge-base --is-ancestor HEAD main 2>/dev/null; then
  AHEAD="$(git rev-list --count main..HEAD 2>/dev/null || echo 0)"
  if [ "${AHEAD}" = "0" ]; then
    pass "HEAD 在 main 上（当前分支 ${BRANCH}）"
  else
    pass "HEAD 已包含在 main 里（main 比 HEAD 多 ${AHEAD} 个提交，当前分支 ${BRANCH}）"
  fi
else
  fail "HEAD 还没合入 main —— 先把 ${BRANCH} 合入 main，tag 只从 main 打"
fi

# ---------------------------------------------------------------- 5. 依赖锁
echo
echo "[5/8] package-lock 与 package.json"
if [ -n "${PY}" ] && [ -f desktop/package-lock.json ]; then
  if "${PY}" - "${VERSION}" <<'PY'
import json, sys
want = sys.argv[1]
lock = json.load(open("desktop/package-lock.json", encoding="utf-8"))
got = lock.get("version", "")
root = lock.get("packages", {}).get("", {}).get("version", "")
sys.exit(0 if got == want and (not root or root == want) else 1)
PY
  then
    pass "根版本一致"
  else
    fail "package-lock.json 根版本与 package.json 不一致（会导致 npm ci 报错）"
  fi
else
  warn "缺少 python 或 desktop/package-lock.json，跳过"
fi

# ---------------------------------------------------------------- 6. sidecar
echo
echo "[6/8] sidecar 新鲜度"
SIDECAR_BIN="build/pack/dist/sidecar/sidecar"
if [ ! -x "${SIDECAR_BIN}" ]; then
  fail "还没有 sidecar —— 先跑 bash tools/pack/build_sidecar.sh"
else
  STALE="$(find core server -name '*.py' -newer "${SIDECAR_BIN}" -print -quit 2>/dev/null || true)"
  if [ -z "${STALE}" ] && [ tools/pack/sidecar_entry.py -nt "${SIDECAR_BIN}" ]; then
    STALE="tools/pack/sidecar_entry.py"
  fi
  if [ -n "${STALE}" ]; then
    fail "sidecar 比 Python 源码旧（${STALE}）—— 发版前必须重打"
  else
    pass "sidecar 比 core/ server/ 源码新"
  fi
fi

# 渲染层产物：build_app.sh 会因缺它退出，这里提前说一句
if [ -d desktop/renderer/dist ]; then
  RENDER_STALE="$(find desktop/renderer/src -type f -newer desktop/renderer/dist 2>/dev/null | head -1 || true)"
  if [ -n "${RENDER_STALE}" ]; then
    warn "渲染层源码比 dist 新 —— rebuild.sh 会重新构建；手工装配时别忘 npm run build"
  else
    pass "渲染层产物存在"
  fi
else
  fail "缺少 desktop/renderer/dist —— 先 cd desktop && npm run build"
fi

# ---------------------------------------------------------------- 7. 图标
echo
echo "[7/8] 应用图标（唯一源 docs/app-icon.png）"
ICON="docs/app-icon.png"
if [ ! -f "${ICON}" ]; then
  fail "缺少 ${ICON} —— build_app.sh 会直接退出"
else
  SIZE=""
  if [ -n "${PY}" ]; then
    SIZE="$("${PY}" - <<'PY' 2>/dev/null || true
try:
    from PIL import Image
    with Image.open("docs/app-icon.png") as im:
        print("%dx%d/%s" % (im.width, im.height, im.mode))
except Exception:
    pass
PY
)"
  fi
  if [ -z "${SIZE}" ] && command -v sips >/dev/null 2>&1; then
    W="$(sips -g pixelWidth "${ICON}" 2>/dev/null | awk '/pixelWidth/{print $2}')"
    H="$(sips -g pixelHeight "${ICON}" 2>/dev/null | awk '/pixelHeight/{print $2}')"
    [ -n "${W}" ] && [ -n "${H}" ] && SIZE="${W}x${H}"
  fi
  case "${SIZE}" in
    1024x1024*) pass "1024×1024（${SIZE}）" ;;
    "") warn "无法读取尺寸（缺 Pillow 与 sips），跳过" ;;
    *) fail "图标不是 1024×1024：${SIZE}（iconutil 会生成模糊的 icns）" ;;
  esac
fi

# ---------------------------------------------------------------- 8. 快速测试
echo
echo "[8/8] 快速检查"
if command -v ruff >/dev/null 2>&1; then
  if ruff check . >/dev/null 2>&1; then
    pass "ruff clean"
  else
    fail "ruff 有告警：ruff check ."
  fi
elif [ -x "../.venv/bin/ruff" ]; then
  if ../.venv/bin/ruff check . >/dev/null 2>&1; then
    pass "ruff clean"
  else
    fail "ruff 有告警：../.venv/bin/ruff check ."
  fi
else
  warn "没找到 ruff，跳过（CI 会跑）"
fi

if [ "${FAST_TESTS}" = "1" ]; then
  if [ -d desktop/node_modules ]; then
    if (cd desktop && npm run test:main >/dev/null 2>&1); then
      pass "npm run test:main 通过"
    else
      fail "npm run test:main 失败（cd desktop && npm run test:main）"
    fi
  else
    warn "desktop/node_modules 不存在，跳过主进程用例"
  fi
fi

if [ "${WITH_TESTS}" = "1" ]; then
  echo "  … 跑 pytest 全量（约 45 秒）"
  if [ -n "${PY}" ] && "${PY}" -m pytest -q >/tmp/kikusub-preflight-pytest.log 2>&1; then
    pass "pytest 全量通过"
  else
    fail "pytest 失败，日志：/tmp/kikusub-preflight-pytest.log"
  fi
else
  warn "未跑 pytest 全量（加 --with-tests）；CI 会跑，但发版本地必须跑一次"
fi

# ---------------------------------------------------------------- 汇总
echo
if [ "${FAIL}" = "0" ]; then
  echo "✅ 发版前置检查通过。下一步按 docs/release.md §② 走本地实测。"
  exit 0
fi
echo "❌ 有 ${FAIL} 项阻塞，**不许发版**。逐条修完后重跑本脚本。"
exit 1
