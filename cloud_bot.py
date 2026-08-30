# ==========================================================
# 24/7 Cloud Gold Precision Scalper & Telegram Assistant
# (Render Webhook + Auto-KeepAlive + Market Scanner)
# ==========================================================
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import os
import time
import logging
import threading
import requests
import yaml
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

from core.cloud_gold_feed import CloudGoldFeed
from core.news_engine import NewsEngine
from core.ai_nlp_engine import AINLPEngine
from strategy.price_action_scalper import PriceActionScalper
from notifications.telegram_bot import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("CloudBot")

app = Flask(__name__)

# Load config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(BASE_DIR, "config.yaml")

with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Global Singletons
gold_feed = CloudGoldFeed()
news_engine = NewsEngine(config)
scalper = PriceActionScalper(config)
telegram = TelegramNotifier(config)
nlp_engine = AINLPEngine(gemini_api_key=config.get("telegram", {}).get("gemini_api_key", ""))

bot_token = config.get("telegram", {}).get("bot_token", "").strip()
chat_id = config.get("telegram", {}).get("chat_id", "8949868154")

@app.route("/", methods=["GET"])
def health_check():
    return "<h3>🪙 Gold Precision AI Assistant is LIVE & RUNNING 24/7 OK!</h3><p>Status: Active</p>", 200

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """Handles real-time incoming messages from Telegram."""
    update = request.get_json(force=True, silent=True)
    if not update:
        return "No data", 400

    message = update.get("message")
    if not message:
        return "OK", 200

    chat = message.get("chat", {})
    sender_chat_id = str(chat.get("id"))
    text = message.get("text", "").strip()

    if not text:
        return "OK", 200

    logger.info(f"Incoming Telegram Message from {sender_chat_id}: {text}")

    try:
        # Fetch live market data
        price_info = gold_feed.get_price() or {}
        news_status = news_engine.check_shield() or {}

        candles_m1 = gold_feed.get_candles("M1", count=80)
        candles_m5 = gold_feed.get_candles("M5", count=80)
        candles_m15 = gold_feed.get_candles("M15", count=80)
        candles_h1 = gold_feed.get_candles("H1", count=80)
        candles_d1 = gold_feed.get_candles("D1", count=50)

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

        market_context = {
            "price": price_info,
            "account": gold_feed.get_account_info(),
            "news": news_status,
            "macro": scalper.macro_engine.levels,
            "scalper_result": scalper_result
        }

        # Process Natural Language & reply immediately
        reply = nlp_engine.process_message(text, market_context)
        telegram.send_message(reply, target_chat_id=sender_chat_id)

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        telegram.send_message("⚠️ เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่อีกครั้งครับ", target_chat_id=sender_chat_id)

    return "OK", 200

def keep_alive_worker():
    """Pings the Render app every 5 minutes so it NEVER sleeps."""
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://gold-sniper-bot-h3m1.onrender.com")
    time.sleep(30)
    while True:
        try:
            res = requests.get(render_url, timeout=15)
            logger.info(f"Keep-Alive ping sent to {render_url} (Status: {res.status_code})")
        except Exception as e:
            logger.warning(f"Keep-alive ping notice: {e}")
        time.sleep(300)

def market_scanner_worker():
    """Background real-time market scanner that auto-sends Grade A+ signals."""
    logger.info("Market scanner background thread started.")
    scan_interval = 10
    last_signal_hash = None
    last_signal_time = None
    cooldown_minutes = 20

    time.sleep(10)
    while True:
        try:
            price_info = gold_feed.get_price()
            candles_m1 = gold_feed.get_candles("M1", count=100)
            candles_m5 = gold_feed.get_candles("M5", count=100)
            candles_m15 = gold_feed.get_candles("M15", count=100)
            candles_h1 = gold_feed.get_candles("H1", count=100)
            candles_d1 = gold_feed.get_candles("D1", count=60)

            news_status = news_engine.check_shield()

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
            logger.error(f"Market scanner loop error: {e}")
            time.sleep(scan_interval)

def setup_telegram_webhook():
    """Registers Webhook directly with Telegram."""
    webhook_url = "https://gold-sniper-bot-h3m1.onrender.com/webhook"
    tg_url = f"https://api.telegram.org/bot{bot_token}/setWebhook?url={webhook_url}"
    try:
        res = requests.get(tg_url, timeout=10)
        logger.info(f"Telegram Webhook Registration: {res.json()}")
    except Exception as e:
        logger.warning(f"Error registering Telegram webhook: {e}")

# Start background workers on module import (Gunicorn / Direct)
_workers_started = False
def init_background_workers():
    global _workers_started
    if not _workers_started:
        _workers_started = True
        setup_telegram_webhook()
        t_ping = threading.Thread(target=keep_alive_worker, daemon=True)
        t_ping.start()
        t_scan = threading.Thread(target=market_scanner_worker, daemon=True)
        t_scan.start()

init_background_workers()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
