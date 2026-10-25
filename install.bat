@echo off
chcp 65001 >nul
echo ==========================================================
echo 🎬 KoeSub Studio (声影) Windows 极速安装向导
echo ==========================================================

where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    echo [警告] 未在环境变量 PATH 中找到 ffmpeg！
    echo 请先安装 ffmpeg (例如通过 winget install Gyan.FFmpeg)
    pause
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
echo [*] 环境就绪！正在启动 KoeSub Studio...
python app.py
pause
