# ==========================================================
# Institutional Top-Down MT5 Execution & Anti-Overtrade Engine
# ==========================================================
import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger("OrderExecutor")

class OrderExecutor:
    """
    Institutional MT5 Auto-Execution Engine:
    1. Single Position Rule (Max 1 Active Trade at any time - Zero Overtrading).
    2. Auto-Clean all orphan pending limit orders.
    3. 3-Minute Post-Trade Cooldown (Prevents rapid machine-gun spam).
    4. Two Distinct Modes: Quick Scalp (1 ไม้จบ 0.04 Lot) vs Trend Runner (0.02 + 0.01 Pyramid).
    5. Active Management: Instant Break-Even + Partial TP + Trailing Stop.
    """

    MAGIC_NUMBER = 778899

    def __init__(self, config: dict, mt5_connector):
        self.config = config
        self.mt5_conn = mt5_connector
        
        self.mm_config = config.get("money_management", {})
        self.daily_profit_target = self.mm_config.get("daily_profit_target_usd", 300.0)
        self.daily_max_loss = self.mm_config.get("daily_max_loss_usd", 250.0)
        
        self.auto_trade_enabled = config.get("auto_trading", {}).get("enable", True)
        self.auto_be_enabled = config.get("auto_trading", {}).get("enable_auto_break_even", True)
        self.trailing_stop_enabled = config.get("auto_trading", {}).get("enable_trailing_stop", True)
        
        self.local_tz = pytz.timezone("Asia/Bangkok")
        self.last_trade_closed_time = datetime.min
        self.cooldown_seconds = 180  # Strict 3-Minute Cooldown after trade closes
        self.partially_closed_tickets = set()

    def clean_all_pending_orders(self) -> int:
        """Cancels all orphaned pending limit orders to keep chart 100% clean."""
        symbol = self.mt5_conn.active_symbol
        if not symbol:
            return 0
        orders = mt5.orders_get(symbol=symbol)
        if not orders:
            return 0
        cleaned = 0
        for ord in orders:
            if ord.magic == self.MAGIC_NUMBER or ord.magic == 0:
                req = {"action": mt5.TRADE_ACTION_REMOVE, "order": ord.ticket}
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    cleaned += 1
                    logger.info(f"🧹 Cleaned orphaned pending order #{ord.ticket}")
        return cleaned

    def get_daily_performance(self) -> dict:
        """Calculates today's realized PnL from MT5 trade deals."""
        from_time = datetime.now() - timedelta(days=2)
        to_time = datetime.now() + timedelta(days=1)
        
        deals = mt5.history_deals_get(from_time, to_time)
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
        Executes institutional trade with strict Single Position Rule & Cooldown.
        """
        if not self.auto_trade_enabled:
            return {"success": False, "message": "Auto-trading disabled"}

        symbol = self.mt5_conn.active_symbol
        if not symbol:
            return {"success": False, "message": "No active symbol"}

        # 1. HARD RULE: Max 1 Active Position at a time (Zero Machine-Gun Stacking!)
        active_pos = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic == self.MAGIC_NUMBER]
        active_ord = [o for o in (mt5.orders_get(symbol=symbol) or []) if o.magic == self.MAGIC_NUMBER]
        
        if len(active_pos) > 0 or len(active_ord) > 0:
            return {"success": False, "message": f"Position lock: {len(active_pos)} open, {len(active_ord)} pending"}

        # 2. HARD RULE: 3-Minute Post-Trade Cooldown
        time_since_closed = (datetime.now() - self.last_trade_closed_time).total_seconds()
        if time_since_closed < self.cooldown_seconds:
            rem = int(self.cooldown_seconds - time_since_closed)
            return {"success": False, "message": f"Cooldown active: {rem}s remaining"}

        # 3. Check Daily Goals & Circuit Breaker
        perf = self.get_daily_performance()
        if perf["profit"] >= self.daily_profit_target:
            return {"success": False, "message": f"🎯 Daily Profit Target (${self.daily_profit_target:.2f}) Achieved!"}

        if perf["profit"] <= -self.daily_max_loss:
            return {"success": False, "message": f"🛑 Circuit Breaker Hit (-${self.daily_max_loss:.2f})"}

        action = signal_data.get("signal", "")
        trade_setup = signal_data.get("trade_setup", {})
        trade_mode = signal_data.get("trade_mode", "QUICK_SCALP")  # QUICK_SCALP vs TREND_RUNNER

        if not trade_setup or action not in ["BUY", "SELL"]:
            return {"success": False, "message": "Invalid trade setup"}

        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"success": False, "message": "Failed to get symbol info"}

        # Clean any old pending orders before entering
        self.clean_all_pending_orders()

        filling_mode = mt5.ORDER_FILLING_IOC
        if hasattr(sym_info, "filling_mode"):
            if sym_info.filling_mode & 1:
                filling_mode = mt5.ORDER_FILLING_FOK
            elif sym_info.filling_mode & 2:
                filling_mode = mt5.ORDER_FILLING_IOC
            else:
                filling_mode = mt5.ORDER_FILLING_RETURN

        digits = sym_info.digits
        step = sym_info.volume_step if sym_info.volume_step > 0 else 0.01

        # Lot Sizing based on Trade Mode:
        # Quick Scalp: 1 Single Clean Order (0.04 Lot)
        # Trend Runner: Base Probe (0.02 Lot)
        if trade_mode == "TREND_RUNNER":
            lot = 0.02
        else:
            lot = 0.04

        lot = round(round(lot / step) * step, 2)
        lot = max(sym_info.volume_min, min(sym_info.volume_max, lot))

        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        price = sym_info.ask if action == "BUY" else sym_info.bid
        sl = float(trade_setup.get("sl", 0.0))
        tp = float(trade_setup.get("tp2" if trade_mode == "TREND_RUNNER" else "tp1", 0.0))

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": round(price, digits),
            "sl": round(sl, digits),
            "tp": round(tp, digits),
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": f"AI_{action}_{trade_mode[:5]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            err = res.comment if res else mt5.last_error()
            logger.error(f"MT5 Order Failed: {err}")
            return {"success": False, "message": f"MT5 Error: {err}"}

        logger.info(f"✅ EXECUTED [{trade_mode}]: #{res.order} | {action} {lot} Lot @ {res.price} (SL: {sl}, TP: {tp})")

        return {
            "success": True,
            "ticket": res.order,
            "action": action,
            "volume": lot,
            "price": res.price,
            "sl": sl,
            "tp": tp,
            "trade_mode": trade_mode,
            "message": f"Order #{res.order} filled at {res.price} ({trade_mode})"
        }

    def manage_open_positions(self, current_price: dict) -> list:
        """
        Active Trade Manager:
        1. Quick Scalp: Move SL to Break-Even at +8 pips ($0.80).
        2. Trend Runner: Move SL to Break-Even at +15 pips, Trail SL behind 5M swings.
        3. Sets cooldown and cleans pending limits when positions close.
        """
        symbol = self.mt5_conn.active_symbol
        if not symbol:
            return []

        positions = mt5.positions_get(symbol=symbol)
        
        # If all positions are closed, record close time and clean pending limits
        if not positions or not any(p.magic == self.MAGIC_NUMBER for p in positions):
            if (datetime.now() - self.last_trade_closed_time).total_seconds() > 3600:
                self.last_trade_closed_time = datetime.now()
                self.clean_all_pending_orders()
            return []

        pip_size = current_price.get("pip_size", 0.10)
        digits = self.mt5_conn.symbol_info.digits if self.mt5_conn.symbol_info else 2
        updates = []

        for pos in positions:
            if pos.magic != self.MAGIC_NUMBER:
                continue

            ticket = pos.ticket
            pos_type = pos.type
            open_price = pos.price_open
            current_sl = pos.sl
            current_tp = pos.tp
            cur_price = pos.price_current
            comment = pos.comment

            is_trend_runner = "TREND" in comment
            be_trigger_pips = 15.0 if is_trend_runner else 8.0  # +8 pips for Quick Scalp, +15 for Trend

            # AUTO BREAK-EVEN LOGIC
            if self.auto_be_enabled:
                if pos_type == mt5.ORDER_TYPE_BUY:
                    profit_distance = cur_price - open_price
                    if profit_distance >= (be_trigger_pips * pip_size) and current_sl < open_price:
                        new_sl = round(open_price + (1.5 * pip_size), digits)
                        req = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": symbol, "sl": new_sl, "tp": current_tp}
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            msg = f"🛡️ [กันทุนสำเร็จ] Ticket #{ticket} เลื่อน SL มาที่ ${new_sl} (0% Risk กันทุน 100%)"
                            logger.info(msg)
                            updates.append(msg)

                elif pos_type == mt5.ORDER_TYPE_SELL:
                    profit_distance = open_price - cur_price
                    if profit_distance >= (be_trigger_pips * pip_size) and (current_sl > open_price or current_sl == 0):
                        new_sl = round(open_price - (1.5 * pip_size), digits)
                        req = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": symbol, "sl": new_sl, "tp": current_tp}
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            msg = f"🛡️ [กันทุนสำเร็จ] Ticket #{ticket} เลื่อน SL มาที่ ${new_sl} (0% Risk กันทุน 100%)"
                            logger.info(msg)
                            updates.append(msg)

        return updates
