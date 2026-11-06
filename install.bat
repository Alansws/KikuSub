@echo off
chcp 65001 >nul
echo ==========================================================
echo 🎬 KikuSub (听幕) Windows 极速安装向导
echo ==========================================================

where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    echo [警告] 未在环境变量 PATH 中找到 ffmpeg！
    echo 请先安装 ffmpeg (例如通过 winget install Gyan.FFmpeg)
    pause
)

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH。
    pause
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if %errorlevel% neq 0 (
    echo [错误] Python 版本过低，需要 3.10+。
    python --version
    pause
    exit /b 1
)

if not exist .venv (
    echo [*] 正在创建 Python 虚拟环境...
    python -m venv .venv
)

echo [*] 正在激活虚拟环境并安装核心依赖...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [*] 环境就绪！正在启动 KikuSub...
python app.py
pause
