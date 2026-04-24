#!/bin/bash
# ──────────────────────────────────────────────
# Mac / Linux 執行腳本
# 自動啟用虛擬環境並執行 main.py
# ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "❌ 尚未安裝，請先執行 ./setup.sh"
    exit 1
fi

source .venv/bin/activate
python main.py
