# ==========================================================
# 24/7 Telegram Webhook Web App (Flask for PythonAnywhere)
# ==========================================================
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import os
import json
import logging
import requests
import yaml
from flask import Flask, request, jsonify

from core.cloud_gold_feed import CloudGoldFeed
from core.news_engine import NewsEngine
from core.ai_nlp_engine import AINLPEngine
from strategy.price_action_scalper import PriceActionScalper
from notifications.telegram_bot import TelegramNotifier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FlaskApp")

app = Flask(__name__)

# Load config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(BASE_DIR, "config.yaml")

with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Initialize singletons
gold_feed = CloudGoldFeed()
news_engine = NewsEngine(config)
scalper = PriceActionScalper(config)
telegram = TelegramNotifier(config)
nlp_engine = AINLPEngine(gemini_api_key=config.get("telegram", {}).get("gemini_api_key", ""))

bot_token = config.get("telegram", {}).get("bot_token", "")

@app.route("/", methods=["GET"])
def home():
    return "<h3>🪙 Gold Precision AI Assistant Web App is RUNNING 24/7 OK!</h3><p>Server Status: Active</p>"

@app.route("/set_webhook", methods=["GET"])
def setup_webhook():
    """Sets the Telegram webhook URL automatically."""
    domain = request.host
    webhook_url = f"https://{domain}/webhook"
    tg_url = f"https://api.telegram.org/bot{bot_token}/setWebhook?url={webhook_url}"
    
    try:
        res = requests.get(tg_url, timeout=10)
        return jsonify({
            "status": "success",
            "webhook_url": webhook_url,
            "telegram_response": res.json()
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
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

    # Build real-time market context
    try:
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

        # Process Natural Language
        reply = nlp_engine.process_message(text, market_context)
        telegram.send_message(reply, target_chat_id=sender_chat_id)

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        telegram.send_message("⚠️ เกิดข้อผิดพลาดในการประมวลผล กรุณาลองใหม่อีกครั้งครับ", target_chat_id=sender_chat_id)

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
