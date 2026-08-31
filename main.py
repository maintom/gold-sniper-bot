# ==========================================================
# Gold MT5 Auto-Execution Precision Scalper (Local Master Engine)
# ==========================================================
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import time
import logging
import yaml
import pandas as pd
from datetime import datetime, timedelta

from core.mt5_connector import MT5Connector
from core.news_engine import NewsEngine
from core.order_executor import OrderExecutor
from strategy.price_action_scalper import PriceActionScalper
from notifications.telegram_bot import TelegramNotifier
from notifications.telegram_interactive import TelegramInteractive
from notifications.console_ui import ConsoleDashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("MainBot")

def main():
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    ui = ConsoleDashboard()
    ui.render_header("Gold AI Sniper (MT5 Auto-Trading Edition)")

    # 1. Connect to MT5
    mt5_conn = MT5Connector(config)
    if not mt5_conn.connect():
        ui.render_error("Failed to connect to MetaTrader 5. Please ensure MT5 terminal is open.")
        return

    # 2. Initialize Core Engines
    news_engine = NewsEngine(config)
    scalper = PriceActionScalper(config)
    executor = OrderExecutor(config, mt5_conn)
    telegram = TelegramNotifier(config)

    # 3. Start Interactive Telegram Listener
    tg_interactive = TelegramInteractive("config.yaml", news_engine, mt5_conn, scalper)
    tg_interactive.start()

    logger.info("Master Auto-Trading Bot initialized successfully.")
    ui.render_system_ready(mt5_conn.active_symbol)

    scan_interval = config.get("system", {}).get("scan_interval_seconds", 3)
    last_dispatched_candle = None
    last_dispatched_direction = None
    last_dispatched_time = None
    cooldown_minutes = 30

    while True:
        try:
            # A. Fetch Real-time Tick & Account Info
            price_info = mt5_conn.get_price()
            account_info = mt5_conn.get_account_info()

            # B. Manage Active Open Trades (Auto Break-Even & Trailing)
            trade_updates = executor.manage_open_positions(price_info)
            for upd in trade_updates:
                telegram.send_message(f"🛡️ <b>[Auto Trade Manager]</b>\n{upd}")

            # C. Fetch Multi-Timeframe OHLCV Candles
            candles_m1 = mt5_conn.get_candles("M1", count=100)
            candles_m5 = mt5_conn.get_candles("M5", count=100)
            candles_m15 = mt5_conn.get_candles("M15", count=100)
            candles_h1 = mt5_conn.get_candles("H1", count=100)
            candles_d1 = mt5_conn.get_candles("D1", count=60)

            # D. Check News Shield
            news_status = news_engine.check_shield()

            # E. Run Top-Down Institutional Analysis
            scalper_result = scalper.analyze(
                candles_m1=candles_m1,
                candles_m5=candles_m5,
                candles_m15=candles_m15,
                candles_h1=candles_h1,
                candles_d1=candles_d1,
                current_price=price_info,
                news_status=news_status,
                account_balance=account_info.get("balance", 1000.0)
            )

            # F. Signal Trigger & Instant Auto-Execution
            sig = scalper_result.get("signal", "WAIT")
            candle_time = scalper_result.get("candle_time")
            now = datetime.now()

            if sig in ["BUY", "SELL"]:
                is_new_candle = (last_dispatched_candle != candle_time)
                time_ok = (last_dispatched_time is None or (now - last_dispatched_time) > timedelta(minutes=cooldown_minutes))
                is_reversal = (last_dispatched_direction is not None and last_dispatched_direction != sig)

                if is_new_candle and (time_ok or is_reversal):
                    last_dispatched_candle = candle_time
                    last_dispatched_direction = sig
                    last_dispatched_time = now

                    logger.info(f"🚀 SNIPER SIGNAL DETECTED: {sig} ({scalper_result.get('win_probability')}%)")

                    # 1. INSTANT AUTO-EXECUTION ON MT5 (0.02s)
                    exec_result = executor.execute_trade(scalper_result, price_info)

                    # 2. DISPATCH TELEGRAM ALERT
                    if exec_result.get("success"):
                        scalper_result["reasons"].append(f"⚡ Auto-Executed on MT5 (Ticket #{exec_result['ticket']})")
                    
                    telegram.send_trade_signal(
                        symbol=mt5_conn.active_symbol,
                        timeframe=scalper_result.get("timeframe", "M5 Early Sniper"),
                        signal_data=scalper_result,
                        news_info=news_status.get("message", "")
                    )

            # G. Update Console UI Dashboard
            ui.update(price_info, account_info, news_status, scalper_result)
            time.sleep(scan_interval)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(scan_interval)

if __name__ == "__main__":
    main()
