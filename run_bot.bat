@echo off
chcp 65001 > nul
title Gold Precision Auto-Trading Scalper (MT5 Demo Edition)
echo ======================================================
echo Starting Gold Precision Auto-Trading Bot...
echo ======================================================

if not exist .venv (
    echo [.venv not found! Creating virtual environment...]
    uv venv .venv
    call .\.venv\Scripts\activate
    uv pip install MetaTrader5 pandas pyyaml beautifulsoup4 rich python-dotenv pytz requests flask gunicorn
) else (
    call .\.venv\Scripts\activate
)

.\.venv\Scripts\python.exe main.py
pause
