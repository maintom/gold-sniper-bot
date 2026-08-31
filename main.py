# ==========================================================
# Gold MT5 Auto-Execution Precision Scalper (Master AI Engine)
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
from core.trade_reflection import TradeReflectionEngine
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

def prompt_daily_goal_setup(config: dict, account_balance: float):
    """Allows user to set manual daily profit target and loss limits on startup."""
    mm = config.get("money_management", {})
    default_target = float(mm.get("daily_profit_target_usd", 300.0))
    default_loss = float(mm.get("daily_max_loss_usd", round(account_balance * 0.10, 2)))

    print("\n" + "=" * 60)
    print(" 🎯 INSTITUTIONAL DAILY GOAL & MONEY MANAGEMENT SETUP")
    print("=" * 60)
    print(f" 💰 ยอดบาลานซ์พอร์ตปัจจุบัน : ${account_balance:,.2f}")
    print(f" 🎯 ค่าเริ่มต้นเป้าหมายกำไร  : +${default_target:,.2f}")
    print(f" 🛑 ค่าเริ่มต้นขีดจำกัดขาดทุน : -${default_loss:,.2f} (10% MM Rule)")
    print("-" * 60)

    try:
        user_target = input(f" 👉 ใส่เป้าหมายกำไรวันนี้ (ดอลลาร์) [กด Enter = {default_target}]: ").strip()
        if user_target:
            default_target = float(user_target)

        user_loss = input(f" 👉 ใส่ขีดจำกัดขาดทุนสูงสุด (ดอลลาร์) [กด Enter = {default_loss}]: ").strip()
        if user_loss:
            default_loss = float(user_loss)

        config["money_management"]["daily_profit_target_usd"] = default_target
        config["money_management"]["daily_max_loss_usd"] = default_loss
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        print(f" ✅ บันทึกเป้าหมาย: กำไร +${default_target:,.2f} | ขาดทุนสูงสุด -${default_loss:,.2f}")
        print("=" * 60 + "\n")
        time.sleep(1)
    except Exception as e:
        print(f" ใช้ค่าเริ่มต้นอัตโนมัติ: กำไร +${default_target:,.2f}")

def main():
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 1. Connect to MT5
    mt5_conn = MT5Connector(config)
    if not mt5_conn.connect():
        print("[-] Failed to connect to MetaTrader 5. Please ensure MT5 terminal is open.")
        return

    account_info = mt5_conn.get_account_info()
    balance = account_info.get("balance", 1000.0)

    # Interactive Daily Goal Setup Prompt
    prompt_daily_goal_setup(config, balance)

    ui = ConsoleUI()

    # 2. Initialize Core Engines
    telegram = TelegramNotifier(config)
    news_engine = NewsEngine(config)
    scalper = PriceActionScalper(config)
    executor = OrderExecutor(config, mt5_conn)
    reflection_engine = TradeReflectionEngine(config, telegram)

    # 3. Start Interactive Telegram Listener
    tg_interactive = TelegramInteractive("config.yaml", news_engine, mt5_conn, scalper)
    tg_interactive.start()

    scan_interval = config.get("system", {}).get("scan_interval_seconds", 3)
    max_open_trades = config.get("auto_trading", {}).get("max_open_trades", 1)
    last_dispatched_candle = None

    while True:
        try:
            # Refresh config dynamically (in case updated via Telegram /setgoal)
            mm_cfg = config.get("money_management", {})

            # A. Fetch Real-time Tick, Account Info & Daily Performance
            price_info = mt5_conn.get_price()
            account_info = mt5_conn.get_account_info()
            perf_info = executor.get_daily_performance()

            # B. AI Self-Learning: Inspect Closed Trades & Generate Post-Mortems
            reflection_engine.inspect_and_learn_from_deals(OrderExecutor.MAGIC_NUMBER)

            # C. Active Trade Management (Instant Auto Break-Even & Partial TP)
            trade_updates = executor.manage_open_positions(price_info)
            for upd in trade_updates:
                telegram.send_message(f"🛡️ <b>[Auto Trade Manager]</b>\n{upd}")

            # D. Fetch Multi-Timeframe OHLCV Candles
            candles_m1 = mt5_conn.get_candles("M1", count=100)
            candles_m5 = mt5_conn.get_candles("M5", count=100)
            candles_m15 = mt5_conn.get_candles("M15", count=100)
            candles_h1 = mt5_conn.get_candles("H1", count=100)
            candles_d1 = mt5_conn.get_candles("D1", count=60)

            # E. Check News Shield
            news_status = news_engine.check_shield()

            # F. Run Adaptive Multi-Timeframe Playbook Analysis
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

            # G. Signal Trigger & Smart Layered Auto-Execution
            sig = scalper_result.get("signal", "WAIT")
            candle_time = scalper_result.get("candle_time")

            if sig in ["BUY", "SELL"]:
                active_bot_positions = [
                    p for p in (mt5.positions_get(symbol=mt5_conn.active_symbol) or [])
                    if p.magic == OrderExecutor.MAGIC_NUMBER
                ]

                is_new_candle = (last_dispatched_candle != candle_time)
                has_capacity = (len(active_bot_positions) < max_open_trades)

                if is_new_candle and has_capacity:
                    exec_result = executor.execute_trade(scalper_result, price_info)

                    if exec_result.get("success"):
                        last_dispatched_candle = candle_time
                        scalper_result["reasons"].append(f"⚡ Auto-Executed on MT5 (Ticket #{exec_result['ticket']})")
                        telegram.send_trade_signal(
                            symbol=mt5_conn.active_symbol,
                            timeframe=scalper_result.get("timeframe", "M5 Playbook"),
                            signal_data=scalper_result,
                            news_info=news_status.get("message", "")
                        )
                    else:
                        logger.warning(f"Order skipped: {exec_result.get('message')}")

            # H. Update Console UI Dashboard
            ui.render_dashboard(
                symbol=mt5_conn.active_symbol,
                price_info=price_info,
                account_info=account_info,
                news_status=news_status,
                scalper_result=scalper_result,
                session_desc=scalper_result.get("session_desc", "Active"),
                perf_info=perf_info,
                mm_config=mm_cfg
            )
            time.sleep(scan_interval)

        except KeyboardInterrupt:
            print("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(scan_interval)

if __name__ == "__main__":
    main()
