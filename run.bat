@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo ❌ 尚未安裝，請先執行 setup.bat
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python main.py
