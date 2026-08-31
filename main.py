# ==========================================================
# Gold MT5 Auto-Execution Precision Scalper (Local Master Engine)
# ==========================================================
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import time
import logging
import yaml
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta

from core.mt5_connector import MT5Connector
from core.news_engine import NewsEngine
from core.order_executor import OrderExecutor
from strategy.price_action_scalper import PriceActionScalper
from notifications.telegram_bot import TelegramNotifier
from notifications.telegram_interactive import TelegramInteractive
from notifications.console_ui import ConsoleUI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("MainBot")

def main():
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    ui = ConsoleUI()

    # 1. Connect to MT5
    mt5_conn = MT5Connector(config)
    if not mt5_conn.connect():
        print("[-] Failed to connect to MetaTrader 5. Please ensure MT5 terminal is open.")
        return

    # 2. Initialize Core Engines
    news_engine = NewsEngine(config)
    scalper = PriceActionScalper(config)
    executor = OrderExecutor(config, mt5_conn)
    telegram = TelegramNotifier(config)

    # 3. Start Interactive Telegram Listener
    tg_interactive = TelegramInteractive("config.yaml", news_engine, mt5_conn, scalper)
    tg_interactive.start()

    scan_interval = config.get("system", {}).get("scan_interval_seconds", 3)
    max_open_trades = config.get("auto_trading", {}).get("max_open_trades", 1)
    last_dispatched_candle = None

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

            # F. Signal Trigger & Dynamic Auto-Execution
            sig = scalper_result.get("signal", "WAIT")
            candle_time = scalper_result.get("candle_time")

            if sig in ["BUY", "SELL"]:
                # Check active bot positions in MT5
                active_bot_positions = [
                    p for p in (mt5.positions_get(symbol=mt5_conn.active_symbol) or [])
                    if p.magic == OrderExecutor.MAGIC_NUMBER
                ]

                is_new_candle = (last_dispatched_candle != candle_time)
                has_capacity = (len(active_bot_positions) < max_open_trades)

                if is_new_candle and has_capacity:
                    # 1. INSTANT AUTO-EXECUTION ON MT5 (0.02s)
                    exec_result = executor.execute_trade(scalper_result, price_info)

                    if exec_result.get("success"):
                        last_dispatched_candle = candle_time
                        scalper_result["reasons"].append(f"⚡ Auto-Executed on MT5 (Ticket #{exec_result['ticket']})")
                        telegram.send_trade_signal(
                            symbol=mt5_conn.active_symbol,
                            timeframe=scalper_result.get("timeframe", "M5 Early Sniper"),
                            signal_data=scalper_result,
                            news_info=news_status.get("message", "")
                        )
                    else:
                        logger.warning(f"Order not executed: {exec_result.get('message')}")

            # G. Update Console UI Dashboard
            ui.render_dashboard(
                symbol=mt5_conn.active_symbol,
                price_info=price_info,
                account_info=account_info,
                news_status=news_status,
                scalper_result=scalper_result,
                session_desc=scalper_result.get("session_desc", "Active")
            )
            time.sleep(scan_interval)

        except KeyboardInterrupt:
            print("Bot stopped by user.")
            break
        except Exception as e:
            time.sleep(scan_interval)

if __name__ == "__main__":
    main()
