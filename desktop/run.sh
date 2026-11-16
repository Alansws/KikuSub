#!/usr/bin/env bash
# 启动 KikuSub 桌面版（开发模式：真实内核 + 真实界面）
#
# 这是**人的入口**：它显式设置 KIKUSUB_ALLOW_WINDOW=1，所以窗口会出现。
# 智能体/自动化不要用它——无窗口铁律见 AGENTS.md §0.5；验证走
# `npx electron . --screenshot=…` 或 tools/shots/ 里的静默脚本。
#
# 为什么要 env -u：本机 shell 里有 ELECTRON_RUN_AS_NODE=1（WorkBuddy 的 Electron
# 宿主注入的），它会让 Electron 二进制退化成纯 Node，表现是
# "Cannot read properties of undefined (reading 'isPackaged')"。
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d node_modules ]; then
  echo "首次运行，安装依赖…"
  ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ npm install --no-audit --no-fund
fi

npm run build --silent

exec env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS KIKUSUB_ALLOW_WINDOW=1 npx electron .
