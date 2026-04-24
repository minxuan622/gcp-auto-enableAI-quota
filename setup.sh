#!/bin/bash
# ──────────────────────────────────────────────
# Mac / Linux 一鍵安裝腳本
# 用法：chmod +x setup.sh && ./setup.sh
# ──────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════╗"
echo "║  GCP Claude Manager — 環境安裝           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# 1. 檢查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 找不到 python3，請先安裝 Python 3.10+"
    exit 1
fi
echo "✓ Python: $(python3 --version)"

# 2. 檢查 gcloud
if ! command -v gcloud &> /dev/null; then
    echo ""
    echo "❌ 找不到 gcloud CLI"
    echo "  請先安裝：brew install --cask google-cloud-sdk"
    echo "  或至 https://cloud.google.com/sdk/docs/install"
    exit 1
fi
echo "✓ gcloud: $(gcloud --version 2>&1 | head -1)"

# 3. 建立虛擬環境
echo ""
echo "→ 建立 Python 虛擬環境 (.venv) ..."
python3 -m venv .venv
source .venv/bin/activate
echo "✓ 虛擬環境已建立並啟用"

# 4. 安裝套件
echo ""
echo "→ 安裝 Python 套件 ..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✓ Python 套件安裝完成"

# 5. 安裝 Playwright 瀏覽器
echo ""
echo "→ 安裝 Playwright Chromium ..."
playwright install chromium
echo "✓ Chromium 安裝完成"

# 6. 建立設定檔
if [ ! -f config.json ]; then
    cp config.json.example config.json
    echo ""
    echo "✓ 已建立 config.json（請用編輯器打開填入你的個人資料）"
else
    echo ""
    echo "✓ config.json 已存在，跳過"
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "✓ 已建立 .env（預設值即可使用，有需要再修改）"
else
    echo "✓ .env 已存在，跳過"
fi

# 7. GCP 登入提示
echo ""
echo "════════════════════════════════════════════"
echo "  安裝完成！"
echo ""
echo "  下一步："
echo "    1. 編輯 config.json 填入你的姓名/公司/職稱等"
echo "    2. 執行 GCP 授權（只需一次）："
echo "       gcloud auth application-default login"
echo "    3. 執行工具："
echo "       ./run.sh"
echo "════════════════════════════════════════════"
