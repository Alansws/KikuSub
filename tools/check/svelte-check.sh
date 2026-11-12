#!/usr/bin/env bash
# svelte-check 基线守卫（2026-11-13 起）。
#
#   cd desktop && npm run check:svelte      # 等价于 bash tools/check/svelte-check.sh
#
# 为什么是"基线"而不是"必须 0 错"：Svelte 单文件组件在 2026-11-13 之前从来没有被
# 类型检查过，存量有 10 个真实类型错误（例如 `popIn` 未定义、preload 桥的 `onQuitting` 没写进 `window.kikusub`
# 的类型、菜单命令名 `find`/`shortcuts` 不在联合类型里）。一口气全修会动到正在跑的界面，
# 风险大于收益；但"继续往上加"必须立刻被拦住。所以冻结当前数字，**只许降**。
#
# 数字变动时改 desktop/test/svelte-check-baseline.json，并在提交信息里写清理由。
# svelte-check 固定为基线里记的版本：报错口径随版本变化，漂移会制造假红。

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}/desktop"

BASELINE="test/svelte-check-baseline.json"
[ -f "${BASELINE}" ] || { echo "缺少 ${BASELINE}" >&2; exit 2; }

if [ ! -x node_modules/.bin/svelte-check ]; then
  echo "缺少 svelte-check：在 desktop/ 下跑 npm install" >&2
  exit 2
fi

# 工作区根的 venv 在 repo/../.venv；本机 python3 可能是 3.14，所以优先用 venv
PY="${REPO_ROOT}/../.venv/bin/python"
[ -x "${PY}" ] || PY="$(command -v python3 || true)"
[ -n "${PY}" ] || { echo "找不到 python3" >&2; exit 2; }

BASE_ERRORS="$("${PY}" - "${BASELINE}" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["errors"])
PY
)"
BASE_VERSION="$("${PY}" - "${BASELINE}" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("svelteCheck", "?"))
PY
)"
[ -n "${BASE_ERRORS}" ] || { echo "读不出基线数字（${BASELINE}）" >&2; exit 2; }

# svelte-check 有错误时退出码非 0，这里不关心它，只关心统计行
OUT="$(node_modules/.bin/svelte-check --threshold error 2>&1)"
SUMMARY="$(printf '%s\n' "${OUT}" | grep 'svelte-check found' | tail -1)"

# 从 "svelte-check found 33 errors and 5 warnings in 23 files" 里取错误数
COUNT="$(printf '%s\n' "${SUMMARY}" | sed -n 's/.*found \([0-9][0-9]*\) error.*/\1/p')"
if [ -z "${COUNT}" ]; then
  printf '%s\n' "${OUT}" | tail -20 >&2
  echo "解析不出错误数（svelte-check 输出格式变了？）" >&2
  exit 2
fi

echo "svelte-check: ${COUNT} 个类型错误（基线 ${BASE_ERRORS}，版本 ${BASE_VERSION}）"

if [ "${COUNT}" -gt "${BASE_ERRORS}" ]; then
  echo "" >&2
  echo "❌ 新增了 $((COUNT - BASE_ERRORS)) 个类型错误。当前全部错误里前 8 条：" >&2
  # 无法直接算出"哪几条是新增的"，所以把定位行 + 报错行配对打出来，自己比对
  printf '%s\n' "${OUT}" | awk '
    /^\/.*\.(svelte|ts):[0-9]+:[0-9]+$/ { loc = $0; next }
    /^Error:/ { print "   " loc; print "     " $0; n++; if (n >= 8) exit }
  ' >&2
  echo "" >&2
  echo "   修掉它们，不要调高基线；确实是存量误报再改 ${BASELINE} 并写明理由。" >&2
  exit 1
fi

if [ "${COUNT}" -lt "${BASE_ERRORS}" ]; then
  echo "✅ 比基线少了 $((BASE_ERRORS - COUNT)) 个 —— 请把 ${BASELINE} 的 errors 下调到 ${COUNT}。"
  exit 0
fi

echo "✅ 与基线持平（${COUNT}/${BASE_ERRORS}）。"
exit 0
