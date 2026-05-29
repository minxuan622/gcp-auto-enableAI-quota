@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo [ERROR] Not installed yet. Please run setup.bat first.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python main.py
