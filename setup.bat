@echo off
chcp 65001 >nul
REM ──────────────────────────────────────────────
REM Windows 一鍵安裝腳本
REM 用法：在專案資料夾中雙擊 setup.bat 或在 PowerShell 執行
REM ──────────────────────────────────────────────

cd /d "%~dp0"

echo ╔══════════════════════════════════════════╗
echo ║  GCP Claude Manager — 環境安裝           ║
echo ╚══════════════════════════════════════════╝
echo.

REM 1. 檢查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 找不到 Python，請先安裝 Python 3.10+
    echo    https://www.python.org/downloads/
    pause
    exit /b 1
)
echo ✓ Python 已安裝

REM 2. 檢查 gcloud
gcloud --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ❌ 找不到 gcloud CLI
    echo    請先安裝：winget install Google.CloudSDK
    echo    或至 https://cloud.google.com/sdk/docs/install
    pause
    exit /b 1
)
echo ✓ gcloud 已安裝

REM 3. 建立虛擬環境
echo.
echo → 建立 Python 虛擬環境 (.venv) ...
python -m venv .venv
call .venv\Scripts\activate.bat
echo ✓ 虛擬環境已建立並啟用

REM 4. 安裝套件
echo.
echo → 安裝 Python 套件 ...
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo ✓ Python 套件安裝完成

REM 5. 安裝 Playwright 瀏覽器
echo.
echo → 安裝 Playwright Chromium ...
playwright install chromium
echo ✓ Chromium 安裝完成

REM 6. 建立設定檔
if not exist config.json (
    copy config.json.example config.json >nul
    echo.
    echo ✓ 已建立 config.json（請用編輯器打開填入你的個人資料）
) else (
    echo.
    echo ✓ config.json 已存在，跳過
)

if not exist .env (
    copy .env.example .env >nul
    echo ✓ 已建立 .env（預設值即可使用，有需要再修改）
) else (
    echo ✓ .env 已存在，跳過
)

REM 7. 完成
echo.
echo ════════════════════════════════════════════
echo   安裝完成！
echo.
echo   下一步：
echo     1. 編輯 config.json 填入你的姓名/公司/職稱等
echo     2. 執行 GCP 授權（只需一次）：
echo        gcloud auth application-default login
echo     3. 執行工具：
echo        run.bat
echo ════════════════════════════════════════════
pause
