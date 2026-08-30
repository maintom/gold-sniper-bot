# ==========================================================
# 24/7 Cloud Gold Precision Scalper & Telegram Assistant
# ==========================================================
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import os
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import yaml
import pandas as pd
from datetime import datetime, timedelta

from core.cloud_gold_feed import CloudGoldFeed
from core.news_engine import NewsEngine
from strategy.price_action_scalper import PriceActionScalper
from notifications.telegram_bot import TelegramNotifier
from notifications.telegram_interactive import TelegramInteractive

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("CloudBot")

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple web server to satisfy Render Web Service port requirements."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Gold Precision AI Scalper is RUNNING 24/7 OK!")

    def log_message(self, format, *args):
        return  # Suppress HTTP request spam

def start_health_server(port: int):
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Render health check web server listening on port {port} OK.")
    except Exception as e:
        logger.warning(f"Health check server notice on port {port}: {e}")

def clear_webhook(bot_token: str):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
        requests.get(url, timeout=5)
    except Exception:
        pass

def main():
    print("=" * 60)
    print("Starting Gold Precision AI Assistant (24/7 Cloud Edition)")
    print("=" * 60)

    # 1. Start HTTP Server for Render port binding (Default: 10000 or env PORT)
    port = int(os.environ.get("PORT", 10000))
    start_health_server(port)

    # 2. Load Configuration
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    bot_token = config.get("telegram", {}).get("bot_token", "")
    if bot_token:
        clear_webhook(bot_token)

    # 3. Initialize Strategy & Bot Components
    gold_feed = CloudGoldFeed()
    news_engine = NewsEngine(config)
    scalper = PriceActionScalper(config)
    telegram = TelegramNotifier(config)

    # 4. Start Interactive Telegram Listener
    tg_interactive = TelegramInteractive("config.yaml", news_engine, gold_feed, scalper)
    tg_interactive.start()

    logger.info("24/7 Cloud Bot Initialized. Monitoring Gold market & Telegram commands...")

    scan_interval = 10
    last_signal_hash = None
    last_signal_time = None
    cooldown_minutes = 20

    # 5. Real-time Market Monitoring Loop
    while True:
        try:
            # Fetch Real-time price & candles
            price_info = gold_feed.get_price()
            candles_m1 = gold_feed.get_candles("M1", count=100)
            candles_m5 = gold_feed.get_candles("M5", count=100)
            candles_m15 = gold_feed.get_candles("M15", count=100)
            candles_h1 = gold_feed.get_candles("H1", count=100)
            candles_d1 = gold_feed.get_candles("D1", count=60)

            # Check News Shield
            news_status = news_engine.check_shield()

            # Analyze with AI & Macro Confluence
            scalper_result = scalper.analyze(
                candles_m1=candles_m1,
                candles_m5=candles_m5,
                candles_m15=candles_m15,
                candles_h1=candles_h1,
                candles_d1=candles_d1,
                current_price=price_info,
                news_status=news_status,
                account_balance=1000.0
            )

            # Dispatch Signal if Grade A+ / Approved
            sig = scalper_result.get("signal", "WAIT")
            if sig in ["BUY", "SELL"]:
                now = datetime.now()
                sig_hash = f"{sig}_{scalper_result.get('trade_setup', {}).get('entry')}"
                
                can_dispatch = False
                if last_signal_hash != sig_hash:
                    can_dispatch = True
                elif last_signal_time and (now - last_signal_time) > timedelta(minutes=cooldown_minutes):
                    can_dispatch = True

                if can_dispatch:
                    last_signal_hash = sig_hash
                    last_signal_time = now
                    logger.info(f"🚀 CLOUD AI SIGNAL DETECTED: {sig} | Prob: {scalper_result.get('win_probability')}%")

                    telegram.send_trade_signal(
                        symbol="XAUUSD",
                        timeframe="M5",
                        signal_data=scalper_result,
                        news_info=news_status.get("message", "")
                    )

            time.sleep(scan_interval)

        except Exception as e:
            logger.error(f"Cloud main loop error: {e}")
            time.sleep(scan_interval)

if __name__ == "__main__":
    main()
