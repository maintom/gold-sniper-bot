# ==========================================================
# Telegram Signal Dispatcher (Proxy & Cloud Resilient)
# ==========================================================
import os
import logging
import requests

logger = logging.getLogger("TelegramBot")

class TelegramNotifier:

    def __init__(self, config: dict):
        self.tg_config = config.get("telegram", {})
        self.enabled = self.tg_config.get("enable", False)
        self.bot_token = self.tg_config.get("bot_token", "").strip()
        self.chat_id = self.tg_config.get("chat_id", "").strip()

        # PythonAnywhere Proxy Configuration
        self.proxies = None
        if "PYTHONANYWHERE_SITE" in os.environ or os.path.exists("/var/log/"):
            self.proxies = {
                "http": "http://proxy.server:3128",
                "https": "http://proxy.server:3128"
            }

    def send_message(self, text: str, target_chat_id=None) -> bool:
        cid = target_chat_id or self.chat_id
        if not self.enabled or not self.bot_token or not cid:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": cid,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        try:
            res = requests.post(url, json=payload, timeout=10, proxies=self.proxies)
            return res.status_code == 200
        except Exception:
            # Fallback without proxy
            try:
                res = requests.post(url, json=payload, timeout=10)
                return res.status_code == 200
            except Exception as e:
                logger.error(f"Error sending Telegram message: {e}")

        return False

    def send_trade_signal(self, symbol: str, timeframe: str, signal_data: dict, news_info: str = "") -> bool:
        if not self.enabled:
            return False

        action = signal_data.get("signal", "WAIT")
        stars = signal_data.get("stars", "⭐⭐⭐⭐⭐")
        trade = signal_data.get("trade_setup", {})
        reasons = signal_data.get("reasons", [])
        win_prob = signal_data.get("win_probability", 85.0)
        grade = signal_data.get("grade", "GRADE_A")
        macro_zone = signal_data.get("macro_zone", "None")

        if not trade:
            return False

        icon = "🟢" if action == "BUY" else "🔴"
        grade_badge = "🏆 [Grade A+ Sniper]" if "PLUS" in grade else "✨ [Grade A High Precision]"
        reasons_text = "\n".join([f"  • {r}" for r in reasons])

        entry = trade.get('entry', 0.0)
        sl = trade.get('sl', 0.0)
        sl_pips = trade.get('sl_pips', 0)
        tp1 = trade.get('tp1', 0.0)
        tp2 = trade.get('tp2', 0.0)
        rr = trade.get('risk_reward', '1:2.5')
        lot = trade.get('recommended_lot', 0.01)
        risk_usd = trade.get('risk_usd', 0.0)

        msg = (
            f"<b>{icon} GOLD PRECISION SNIPER SIGNAL {stars}</b>\n"
            f"<b>{grade_badge}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Asset:</b> <code>{symbol}</code> | <b>TF:</b> <code>{timeframe}</code>\n"
            f"<b>Action:</b> <b><u>{action}</u></b>\n"
            f"🧠 <b>AI Win Probability:</b> <code>{win_prob:.1f}%</code>\n"
            f"🏛️ <b>Macro Zone:</b> <code>{macro_zone}</code>\n\n"
            f"📍 <b>Entry Zone:</b> <code>${entry:.2f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>${sl:.2f}</code> ({sl_pips} pips)\n"
            f"🎯 <b>Take Profit 1:</b> <code>${tp1:.2f}</code> (1:1.5 RR)\n"
            f"🎯 <b>Take Profit 2:</b> <code>${tp2:.2f}</code> ({rr})\n\n"
            f"⚖️ <b>Recommended Lot:</b> <code>{lot}</code> (Risk ${risk_usd:.2f})\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <b>Confluence / เหตุผลในการเข้า:</b>\n"
            f"{reasons_text}\n\n"
            f"📰 <b>News Status:</b> {news_info}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <i>ระบบวิเคราะห์ด้วย Price Action + AI กรุณาบริหารความเสี่ยงก่อนออกออเดอร์</i>"
        )
        return self.send_message(msg.strip())

    def send_news_alert(self, title: str, status: str, mins_left: float) -> bool:
        if not self.enabled:
            return False

        msg = (
            "<b>🚨 NEWS SHIELD ALERT: PAUSE TRADING</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Event:</b> {title} (USD High Impact)\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Time:</b> In approx <b>{mins_left} minutes</b>\n\n"
            "🛡️ <i>ระบบหยุดส่งสัญญาณชั่วคราวเพื่อป้องกันความผันผวนและการโดนลาก</i>"
        )
        return self.send_message(msg.strip())
