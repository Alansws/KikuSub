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
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "❌ 未检测到 Python 3，请先安装 Python 3.10+。"
    exit 1
fi
if ! $PYTHON_CMD -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "❌ Python 版本过低：$($PYTHON_CMD --version 2>&1)；需要 3.10+。"
    exit 1
fi
echo "✅ 检测到 $($PYTHON_CMD --version 2>&1)"

# 模型缓存约 6.6GB，再加上代理/音频缓存；空间不足只提示，不阻塞安装。
AVAILABLE_KB=$(df -Pk . | awk 'NR==2 {print $4}')
if [ -n "$AVAILABLE_KB" ] && [ "$AVAILABLE_KB" -lt 15728640 ]; then
    echo "⚠️ 当前磁盘可用空间不足 15GB，下载模型/生成代理时可能失败：$(df -h . | awk 'NR==2 {print $4}')"
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
