@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ==========================================
echo   GCP Claude Manager - Setup (Windows)
echo ==========================================
echo.

REM ── 1. Check Python exists ────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo.
    echo   Please install Python 3.10 or newer:
    echo     https://www.python.org/downloads/
    echo.
    echo   IMPORTANT: during install, tick "Add Python to PATH".
    echo   After installing, open a NEW PowerShell window and run setup.bat again.
    echo.
    echo   Opening the download page in your browser...
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

REM ── 1b. Check Python version >= 3.10 ──────
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    set "PYMAJOR=%%a"
    set "PYMINOR=%%b"
)
set "PYOLD="
if !PYMAJOR! LSS 3 set "PYOLD=1"
if !PYMAJOR!==3 if !PYMINOR! LSS 10 set "PYOLD=1"
if defined PYOLD (
    echo [ERROR] Python !PYVER! is too old. This project needs Python 3.10 or newer.
    echo.
    echo   Please install a newer Python ^(3.12 / 3.13 recommended^):
    echo     https://www.python.org/downloads/
    echo.
    echo   IMPORTANT: during install, tick "Add Python to PATH".
    echo   After installing, open a NEW PowerShell window and run setup.bat again.
    echo.
    echo   Opening the download page in your browser...
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)
echo [OK] Python !PYVER! found

REM ── 2. Check gcloud ───────────────────────
REM NOTE: 'call' is required - gcloud is a .cmd file; without 'call' this
REM       batch script would hand off control and never run the rest.
call gcloud --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] gcloud CLI not found.
    echo.
    echo   Please install the Google Cloud SDK using the official installer:
    echo     https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe
    echo   ^(Reference: https://cloud.google.com/sdk/docs/install ^)
    echo.
    echo   Run the installer and click Next through to the end.
    echo   After installing, open a NEW PowerShell window and run setup.bat again.
    echo.
    echo   Opening the installer download in your browser...
    start "" "https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe"
    pause
    exit /b 1
)
echo [OK] gcloud found

REM ── 3. Create virtual environment ─────────
echo.
echo [1/4] Creating Python virtual environment (.venv) ...
python -m venv .venv
call .venv\Scripts\activate.bat
echo [OK] Virtual environment created and activated

REM ── 4. Install packages ───────────────────
echo.
echo [2/4] Installing Python packages ...
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q
echo [OK] Python packages installed

REM ── 5. Install Playwright browser ─────────
echo.
echo [3/4] Installing Playwright Chromium ...
playwright install chromium
echo [OK] Chromium installed

REM ── 6. Create config files ────────────────
echo.
echo [4/4] Creating config files ...
if not exist config.json (
    copy config.json.example config.json >nul
    echo [OK] config.json created - please edit it with your company info
) else (
    echo [SKIP] config.json already exists
)

if not exist .env (
    copy .env.example .env >nul
    echo [OK] .env created
) else (
    echo [SKIP] .env already exists
)

REM ── 7. Done ───────────────────────────────
echo.
echo ==========================================
echo   Setup Complete!
echo.
echo   Next steps:
echo     1. Edit config.json with your company info
echo        (business_name / business_website / contact_email / use_cases)
echo     2. GCP auth (one-time):
echo        gcloud auth application-default login
echo     3. Run the tool:
echo        run.bat
echo ==========================================
pause
endlocal
