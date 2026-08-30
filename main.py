# ==========================================================
# Gold Precision Scalping Assistant Bot - Main Orchestrator
# ==========================================================
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import time
import logging
from datetime import datetime, timedelta
import yaml
import pytz

from core.mt5_connector import MT5Connector
from core.news_engine import NewsEngine
from strategy.price_action_scalper import PriceActionScalper
from notifications.telegram_bot import TelegramNotifier
from notifications.telegram_interactive import TelegramInteractive
from notifications.console_ui import ConsoleUI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("Main")

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    print("=" * 60)
    print("Starting Gold Precision Scalping Assistant Bot (Exness MT5)")
    print("=" * 60)

    config = load_config()

    # Initialize Components
    news_engine = NewsEngine(config)
    mt5_conn = MT5Connector(config)
    scalper = PriceActionScalper(config)
    telegram = TelegramNotifier(config)
    ui = ConsoleUI()

    # Start Telegram Interactive Bot
    tg_interactive = TelegramInteractive("config.yaml", news_engine, mt5_conn, scalper)
    tg_interactive.start()

    # Connect to MT5
    print("Connecting to MetaTrader 5...")
    if not mt5_conn.connect():
        print("\n[ERROR] Could not connect to MT5 or find Gold symbol.")
        print("Please ensure:")
        print("1. MetaTrader 5 is open and logged into your Exness account.")
        print("2. Algo Trading / DLL imports are enabled in MT5 Tools -> Options -> Expert Advisors.")
        print("3. Symbol XAUUSD / XAUUSDm is visible in Market Watch.")
        sys.exit(1)

    print(f"Connected to MT5! Active Gold Symbol: {mt5_conn.active_symbol}")

    scan_interval = config.get("system", {}).get("scan_interval_seconds", 5)
    last_signal_hash = None
    last_signal_time = None
    cooldown_minutes = 15  # Avoid spamming the same signal repeatedly

    try:
        while True:
            # 1. Fetch Real-time price and account info
            price_info = mt5_conn.get_price()
            account_info = mt5_conn.get_account_info()
            balance = account_info.get("balance", 1000.0)

            # 2. Fetch Multi-Timeframe Candle Data (including D1 for Macro levels)
            candles_m1 = mt5_conn.get_candles("M1", count=100)
            candles_m5 = mt5_conn.get_candles("M5", count=100)
            candles_m15 = mt5_conn.get_candles("M15", count=100)
            candles_h1 = mt5_conn.get_candles("H1", count=100)
            candles_d1 = mt5_conn.get_candles("D1", count=60)

            # 3. Check News Shield Status
            news_status = news_engine.check_shield()

            # 4. Run Precision Scalper Analysis with Macro Levels & AI Probability
            scalper_result = scalper.analyze(
                candles_m1=candles_m1,
                candles_m5=candles_m5,
                candles_m15=candles_m15,
                candles_h1=candles_h1,
                candles_d1=candles_d1,
                current_price=price_info,
                news_status=news_status,
                account_balance=balance
            )

            # 5. Handle Signal Dispatch & Cooldown
            sig = scalper_result.get("signal", "WAIT")
            if sig in ["BUY", "SELL"]:
                now = datetime.now()
                sig_hash = f"{sig}_{scalper_result.get('trade_setup', {}).get('entry')}"
                
                # Check cooldown
                can_dispatch = False
                if last_signal_hash != sig_hash:
                    can_dispatch = True
                elif last_signal_time and (now - last_signal_time) > timedelta(minutes=cooldown_minutes):
                    can_dispatch = True

                if can_dispatch:
                    last_signal_hash = sig_hash
                    last_signal_time = now
                    logger.info(f"NEW SIGNAL: {sig} on {mt5_conn.active_symbol} | Win Prob: {scalper_result.get('win_probability')}%")
                    
                    # Reload latest chat_id if updated
                    current_cfg = load_config()
                    telegram.chat_id = current_cfg.get("telegram", {}).get("chat_id", telegram.chat_id)
                    telegram.enabled = current_cfg.get("telegram", {}).get("enable", True)

                    # Dispatch to Telegram
                    telegram.send_trade_signal(
                        symbol=mt5_conn.active_symbol,
                        timeframe=config.get("strategy", {}).get("entry_timeframe", "M5"),
                        signal_data=scalper_result,
                        news_info=news_status.get("message", "")
                    )

            # 6. Render Terminal Dashboard
            is_active, session_desc = scalper.is_session_active()
            ui.render_dashboard(
                symbol=mt5_conn.active_symbol,
                price_info=price_info,
                account_info=account_info,
                news_status=news_status,
                scalper_result=scalper_result,
                session_desc=session_desc
            )

            time.sleep(scan_interval)

    except KeyboardInterrupt:
        print("\nStopping bot gracefully...")
    finally:
        tg_interactive.stop()
        mt5_conn.shutdown()
        print("MT5 connection closed. Bot stopped.")

if __name__ == '__main__':
    main()
