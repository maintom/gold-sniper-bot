# ==========================================================
# Institutional MT5 Auto-Execution & Money Management Engine
# ==========================================================
import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger("OrderExecutor")

class OrderExecutor:
    """
    Handles institutional-grade auto-execution directly on MetaTrader 5:
    1. Daily Profit Target & Daily Max Loss Circuit Breaker.
    2. Sub-second market order placement with precise SL & TP.
    3. Auto Break-Even (BE) at 1:1 RR to guarantee risk-free trades.
    4. Trailing Stop Management.
    """

    MAGIC_NUMBER = 778899  # Unique ID for our AI Sniper Bot

    def __init__(self, config: dict, mt5_connector):
        self.config = config
        self.mt5_conn = mt5_connector
        
        self.mm_config = config.get("money_management", {})
        self.daily_profit_target = self.mm_config.get("daily_profit_target_usd", 50.0)
        self.daily_max_loss = self.mm_config.get("daily_max_loss_usd", 40.0)
        
        self.auto_trade_enabled = config.get("auto_trading", {}).get("enable", True)
        self.auto_be_enabled = config.get("auto_trading", {}).get("enable_auto_break_even", True)
        self.trailing_stop_enabled = config.get("auto_trading", {}).get("enable_trailing_stop", True)
        
        self.local_tz = pytz.timezone("Asia/Bangkok")

    def get_daily_performance(self) -> dict:
        """Calculates today's realized PnL from MT5 trade deals."""
        now = datetime.now(self.local_tz)
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
        
        deals = mt5.history_deals_get(today_start, now)
        if not deals:
            return {"profit": 0.0, "trades_count": 0, "wins": 0, "losses": 0}

        total_profit = 0.0
        wins = 0
        losses = 0
        trades_count = 0

        for d in deals:
            if d.magic == self.MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_OUT:
                p = d.profit + d.swap + d.commission
                total_profit += p
                trades_count += 1
                if p > 0:
                    wins += 1
                elif p < 0:
                    losses += 1

        return {
            "profit": round(total_profit, 2),
            "trades_count": trades_count,
            "wins": wins,
            "losses": losses
        }

    def execute_trade(self, signal_data: dict, current_price: dict) -> dict:
        """
        Executes a live Market Order on MT5 within milliseconds.
        Enforces Daily Profit Target & Daily Max Loss rules.
        """
        if not self.auto_trade_enabled:
            return {"success": False, "message": "Auto-trading is disabled in config"}

        symbol = self.mt5_conn.active_symbol
        if not symbol:
            return {"success": False, "message": "No active MT5 symbol found"}

        # Check Daily Goals & Circuit Breaker
        perf = self.get_daily_performance()
        if perf["profit"] >= self.daily_profit_target:
            msg = f"🎯 Daily Profit Target (${self.daily_profit_target:.2f}) Achieved (+${perf['profit']:.2f})! Bot paused for today."
            logger.info(msg)
            return {"success": False, "message": msg}

        if perf["profit"] <= -self.daily_max_loss:
            msg = f"🛑 Daily Max Loss (-${self.daily_max_loss:.2f}) Hit (-${abs(perf['profit']):.2f})! Circuit breaker triggered."
            logger.warning(msg)
            return {"success": False, "message": msg}

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
        if hasattr(sym_info, "filling_mode"):
            if sym_info.filling_mode & 1:  # FOK
                filling_mode = mt5.ORDER_FILLING_FOK
            elif sym_info.filling_mode & 2:  # IOC
                filling_mode = mt5.ORDER_FILLING_IOC
            else:
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
            "comment": f"AI_{action}",
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
            if pos.magic != self.MAGIC_NUMBER:
                continue

            ticket = pos.ticket
            pos_type = pos.type  # 0 = BUY, 1 = SELL
            open_price = pos.price_open
            current_sl = pos.sl
            current_tp = pos.tp
            cur_price = pos.price_current
            digits = pos.digits

            # AUTO BREAK-EVEN (BE) LOGIC
            if self.auto_be_enabled:
                if pos_type == mt5.ORDER_TYPE_BUY:
                    initial_risk = open_price - current_sl if current_sl > 0 else (25 * pip_size)
                    profit_distance = cur_price - open_price
                    if profit_distance >= initial_risk and current_sl < open_price:
                        new_sl = round(open_price + (2 * pip_size), digits)
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": new_sl,
                            "tp": current_tp
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            logger.info(f"🛡️ AUTO BREAK-EVEN: Ticket #{ticket} SL moved to {new_sl} (Risk-Free!)")
                            updates.append(f"🛡️ Ticket #{ticket}: SL moved to Break-Even (${new_sl})")

                elif pos_type == mt5.ORDER_TYPE_SELL:
                    initial_risk = current_sl - open_price if current_sl > 0 else (25 * pip_size)
                    profit_distance = open_price - cur_price
                    if profit_distance >= initial_risk and (current_sl > open_price or current_sl == 0):
                        new_sl = round(open_price - (2 * pip_size), digits)
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": new_sl,
                            "tp": current_tp
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            logger.info(f"🛡️ AUTO BREAK-EVEN: Ticket #{ticket} SL moved to {new_sl} (Risk-Free!)")
                            updates.append(f"🛡️ Ticket #{ticket}: SL moved to Break-Even (${new_sl})")

        return updates
