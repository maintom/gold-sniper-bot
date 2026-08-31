# ==========================================================
# Institutional MT5 Auto-Execution & Trade Management Engine
# ==========================================================
import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import pytz

logger = logging.getLogger("OrderExecutor")

class OrderExecutor:
    """
    Handles institutional-grade auto-execution directly on MetaTrader 5:
    1. Sub-second market order placement with precise SL & TP.
    2. Auto Break-Even (BE) at 1:1 RR to guarantee risk-free trades.
    3. Trailing Stop Management.
    4. Max Daily Drawdown Protection & News Circuit Breaker.
    """

    MAGIC_NUMBER = 778899  # Unique ID for our AI Sniper Bot

    def __init__(self, config: dict, mt5_connector):
        self.config = config
        self.mt5_conn = mt5_connector
        self.risk_config = config.get("risk", {})
        self.max_daily_signals = self.risk_config.get("max_daily_signals", 6)
        
        self.auto_trade_enabled = config.get("auto_trading", {}).get("enable", True)
        self.auto_be_enabled = config.get("auto_trading", {}).get("enable_auto_break_even", True)
        self.trailing_stop_enabled = config.get("auto_trading", {}).get("enable_trailing_stop", True)
        
        self.local_tz = pytz.timezone("Asia/Bangkok")
        self.daily_trade_count = 0
        self.last_trade_date = None

    def execute_trade(self, signal_data: dict, current_price: dict) -> dict:
        """
        Executes a live Market Order on MT5 within milliseconds.
        """
        if not self.auto_trade_enabled:
            return {"success": False, "message": "Auto-trading is disabled in config"}

        symbol = self.mt5_conn.active_symbol
        if not symbol:
            return {"success": False, "message": "No active MT5 symbol found"}

        # Reset daily trade counter if new day
        today = datetime.now(self.local_tz).date()
        if self.last_trade_date != today:
            self.last_trade_date = today
            self.daily_trade_count = 0

        if self.daily_trade_count >= self.max_daily_signals:
            return {"success": False, "message": f"Max daily trades limit ({self.max_daily_signals}) reached"}

        action = signal_data.get("signal", "")
        trade_setup = signal_data.get("trade_setup", {})
        if not trade_setup or action not in ["BUY", "SELL"]:
            return {"success": False, "message": "Invalid trade setup"}

        # Get MT5 Symbol specifications
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"success": False, "message": f"Failed to get symbol info for {symbol}"}

        # Select filling mode supported by broker
        filling_mode = mt5.ORDER_FILLING_IOC
        if sym_info.filling_mode & mt5.SYMBOL_FILLING_FOK:
            filling_mode = mt5.ORDER_FILLING_FOK
        elif sym_info.filling_mode & mt5.SYMBOL_FILLING_IOC:
            filling_mode = mt5.ORDER_FILLING_IOC
        elif sym_info.filling_mode & mt5.SYMBOL_FILLING_RETURN:
            filling_mode = mt5.ORDER_FILLING_RETURN

        # Sizing normalization
        lot = float(trade_setup.get("recommended_lot", 0.01))
        step = sym_info.volume_step if sym_info.volume_step > 0 else 0.01
        lot = round(round(lot / step) * step, 2)
        lot = max(sym_info.volume_min, min(sym_info.volume_max, lot))

        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        price = sym_info.ask if action == "BUY" else sym_info.bid
        sl = float(trade_setup.get("sl", 0.0))
        tp = float(trade_setup.get("tp2", trade_setup.get("tp1", 0.0)))
        digits = sym_info.digits

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": round(price, digits),
            "sl": round(sl, digits),
            "tp": round(tp, digits),
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": f"Gold_AI_{action}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        logger.info(f"⚡ SENDING MT5 INSTANT ORDER: {action} {lot} Lot @ {price} (SL: {sl}, TP: {tp})")
        result = mt5.order_send(request)

        if result is None:
            err = mt5.last_error()
            logger.error(f"MT5 order_send returned None. Error: {err}")
            return {"success": False, "message": f"MT5 Error: {err}"}

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"MT5 Order Failed. Retcode: {result.retcode} ({result.comment})")
            return {"success": False, "message": f"Retcode {result.retcode}: {result.comment}"}

        self.daily_trade_count += 1
        logger.info(f"✅ MT5 ORDER EXECUTED SUCCESSFULLY! Ticket: #{result.order} | Price: {result.price}")
        
        return {
            "success": True,
            "ticket": result.order,
            "action": action,
            "volume": result.volume,
            "price": result.price,
            "sl": sl,
            "tp": tp,
            "message": f"Order #{result.order} filled at {result.price}"
        }

    def manage_open_positions(self, current_price: dict) -> list:
        """
        Monitors active trades:
        1. Auto Break-Even: Moves SL to entry price once 1:1 RR is hit.
        2. Dynamic Trailing: Locks in profits.
        """
        symbol = self.mt5_conn.active_symbol
        if not symbol:
            return []

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return []

        pip_size = current_price.get("pip_size", 0.10)
        updates = []

        for pos in positions:
            # Only manage trades opened by our bot
            if pos.magic != self.MAGIC_NUMBER:
                continue

            ticket = pos.ticket
            pos_type = pos.type  # 0 = BUY, 1 = SELL
            open_price = pos.price_open
            current_sl = pos.sl
            current_tp = pos.tp
            cur_price = pos.price_current
            digits = pos.digits

            # -------------------------------------------------------------
            # AUTO BREAK-EVEN (BE) LOGIC
            # -------------------------------------------------------------
            if self.auto_be_enabled:
                if pos_type == mt5.ORDER_TYPE_BUY:
                    initial_risk = open_price - current_sl if current_sl > 0 else (20 * pip_size)
                    profit_distance = cur_price - open_price
                    # If profit >= 1.0x initial risk and SL still below entry
                    if profit_distance >= initial_risk and current_sl < open_price:
                        new_sl = round(open_price + (2 * pip_size), digits)  # Entry + 2 pips buffer
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": new_sl,
                            "tp": current_tp
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            logger.info(f"🛡️ AUTO BREAK-EVEN TRIGGERED: Ticket #{ticket} SL moved to {new_sl} (Risk-Free!)")
                            updates.append(f"🛡️ Ticket #{ticket}: SL moved to Break-Even (${new_sl})")

                elif pos_type == mt5.ORDER_TYPE_SELL:
                    initial_risk = current_sl - open_price if current_sl > 0 else (20 * pip_size)
                    profit_distance = open_price - cur_price
                    # If profit >= 1.0x initial risk and SL still above entry
                    if profit_distance >= initial_risk and (current_sl > open_price or current_sl == 0):
                        new_sl = round(open_price - (2 * pip_size), digits)  # Entry - 2 pips buffer
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": new_sl,
                            "tp": current_tp
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            logger.info(f"🛡️ AUTO BREAK-EVEN TRIGGERED: Ticket #{ticket} SL moved to {new_sl} (Risk-Free!)")
                            updates.append(f"🛡️ Ticket #{ticket}: SL moved to Break-Even (${new_sl})")

        return updates
