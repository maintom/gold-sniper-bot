@echo off
chcp 65001 > nul
title Gold Precision Scalping Assistant (Exness MT5)
cd /d %~dp0

echo ==========================================================
echo กำลังเริ่มต้น Gold Precision Scalping Assistant Bot...
echo ==========================================================

if not exist .venv (
    echo [.venv not found! Creating virtual environment...]
    uv venv .venv
    call .\.venv\Scripts\activate
    uv pip install MetaTrader5 pandas pyyaml beautifulsoup4 rich python-dotenv pytz requests
) else (
    call .\.venv\Scripts\activate
)

.\.venv\Scripts\python.exe main.py
pause
