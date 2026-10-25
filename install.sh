#!/usr/bin/env bash
set -e

echo "=========================================================="
echo "🎬 KikuSub (听幕) 极速安装向导 (Linux / macOS)"
echo "=========================================================="

# 1. 检查 ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ 未检测到 ffmpeg，请先安装 ffmpeg："
    echo "  macOS:  brew install ffmpeg"
    echo "  Ubuntu: sudo apt update && sudo apt install ffmpeg"
    exit 1
fi
echo "✅ 检测到 FFmpeg"

# 2. 检查 Python
PYTHON_CMD="python3"
if ! command -v $PYTHON_CMD &> /dev/null; then
    PYTHON_CMD="python"
fi

# 3. 创建虚拟环境
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 正在创建虚拟环境 ($VENV_DIR)..."
    $PYTHON_CMD -m venv $VENV_DIR
fi

echo "⚡ 正在激活虚拟环境..."
source $VENV_DIR/bin/activate

# 4. 安装依赖
echo "📥 正在安装依赖包..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "🎉 安装完成！在虚拟环境中执行以下命令即可启动工作台："
echo "   source .venv/bin/activate && python app.py"
echo "=========================================================="
