import os
import logging
import threading
import time
import requests
import yaml

from core.ai_nlp_engine import AINLPEngine

logger = logging.getLogger("TelegramInteractive")

class TelegramInteractive:

    def __init__(self, config_path: str, news_engine, mt5_connector, scalper_engine):
        self.config_path = config_path
        self.news_engine = news_engine
        self.mt5_conn = mt5_connector
        self.scalper = scalper_engine
        
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
            
        self.tg_config = self.config.get("telegram", {})
        self.bot_token = self.tg_config.get("bot_token", "").strip()
        self.chat_id = self.tg_config.get("chat_id", "")
        self.gemini_key = self.tg_config.get("gemini_api_key", "")
        
        self.nlp_engine = AINLPEngine(gemini_api_key=self.gemini_key)
        self.last_update_id = 0
        self.running = False
        self.thread = None

        # PythonAnywhere Proxy Configuration
        self.proxies = None
        if "PYTHONANYWHERE_SITE" in os.environ or os.path.exists("/var/log/"):
            self.proxies = {
                "http": "http://proxy.server:3128",
                "https": "http://proxy.server:3128"
            }

    def start(self):
        if not self.bot_token:
            logger.warning("No Telegram bot_token provided. Interactive bot disabled.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        logger.info("Telegram interactive listener started.")

    def stop(self):
        self.running = False

    def send_message(self, text: str, target_chat_id=None) -> bool:
        cid = target_chat_id or self.chat_id
        if not self.bot_token or not cid:
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
            try:
                res = requests.post(url, json=payload, timeout=10)
                return res.status_code == 200
            except Exception as e:
                logger.error(f"Error sending telegram message: {e}")

        return False

    def _poll_loop(self):
        session = requests.Session()
        while self.running:
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                params = {"offset": self.last_update_id + 1, "timeout": 2}
                
                try:
                    res = session.get(url, params=params, timeout=8, proxies=self.proxies)
                except Exception:
                    res = session.get(url, params=params, timeout=8)

                if res.status_code == 200:
                    data = res.json()
                    if data.get("ok") and data.get("result"):
                        for upd in data["result"]:
                            self.last_update_id = upd["update_id"]
                            self._handle_update(upd)
                time.sleep(2)
            except Exception:
                time.sleep(4)

    def _handle_update(self, update: dict):
        message = update.get("message")
        if not message:
            return

        chat = message.get("chat", {})
        sender_chat_id = str(chat.get("id"))
        user_name = chat.get("first_name", "Trader")
        text = message.get("text", "").strip()

        if not text:
            return
        # Command: /setgoal or natural goal setting
        if text.startswith("/setgoal") or text.startswith("/target") or "????????" in text:
            parts = re.findall(r"[-+]?(?:\d*\.\d+|\d+)", text)
            if parts:
                target_p = float(parts[0])
                max_l = float(parts[1]) if len(parts) > 1 else round(account_info.get("balance", 1000.0) * 0.10, 2)
                
                # Update config
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f)
                    cfg["money_management"]["daily_profit_target_usd"] = target_p
                    cfg["money_management"]["daily_max_loss_usd"] = max_l
                    with open(self.config_path, "w", encoding="utf-8") as f:
                        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
                    
                    reply = (
                        f"?? <b>????????????????????????????!</b>\n"
                        f"????????????????????\n"
                        f"?? <b>????????????:</b> <code>+${target_p:.2f}</code>\n"
                        f"?? <b>?????????????????:</b> <code>-${max_l:.2f}</code> (10% MM)\n"
                        f"?? <b>???????????????:</b> ${account_info.get('balance', 0.0):,.2f}\n"
                        f"?? <b>???????????????:</b> ${account_info.get('balance', 0.0) + target_p:,.2f}\n"
                        f"????????????????????\n"
                        f"?? <i>????????????????????????????????????????????????!</i>"
                    )
                    self.send_message(reply, target_chat_id=sender_chat_id)
                    return
                except Exception as e:
                    logger.error(f"Error setting goal via telegram: {e}")


        # Save chat_id if not present
        if not self.chat_id or str(self.chat_id) != sender_chat_id:
            self.chat_id = sender_chat_id
            self._save_chat_id_to_config(sender_chat_id)

        # Build real-time market context
        price_info = self.mt5_conn.get_price() or {}
        account_info = self.mt5_conn.get_account_info() or {}
        news_status = self.news_engine.check_shield() or {}

        candles_m1 = self.mt5_conn.get_candles("M1", count=80)
        candles_m5 = self.mt5_conn.get_candles("M5", count=80)
        candles_m15 = self.mt5_conn.get_candles("M15", count=80)
        candles_h1 = self.mt5_conn.get_candles("H1", count=80)
        candles_d1 = self.mt5_conn.get_candles("D1", count=50)

        scalper_result = self.scalper.analyze(
            candles_m1=candles_m1,
            candles_m5=candles_m5,
            candles_m15=candles_m15,
            candles_h1=candles_h1,
            candles_d1=candles_d1,
            current_price=price_info,
            news_status=news_status,
            account_balance=account_info.get("balance", 1000.0)
        )

        market_context = {
            "price": price_info,
            "account": account_info,
            "news": news_status,
            "macro": self.scalper.macro_engine.levels,
            "scalper_result": scalper_result
        }

        # Process message naturally via AINLPEngine
        reply = self.nlp_engine.process_message(text, market_context)
        self.send_message(reply, target_chat_id=sender_chat_id)

    def _save_chat_id_to_config(self, new_chat_id: str):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            cfg["telegram"]["enable"] = True
            cfg["telegram"]["chat_id"] = str(new_chat_id)
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            logger.info(f"Saved chat_id {new_chat_id} to config.yaml successfully.")
        except Exception as e:
            logger.error(f"Error saving chat_id to config: {e}")
