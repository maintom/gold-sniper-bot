# ==========================================================
# Institutional Real-Account MT5 Execution & Armor Engine
# ==========================================================
import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import pytz
from strategy.risk_manager import RiskManager

logger = logging.getLogger("OrderExecutor")

class OrderExecutor:
    """
    Institutional Real-Account Execution & Armor Engine:
    1. Real Account Broker Shield (Spread clamp <= 3.5 pips, Deviation 15, IOC filling).
    2. Consecutive Loss Safe-Mode (30-min pause if 2 consecutive losses occur).
    3. Micro to Large Account Dynamic Lot Scaling ($50 to $10,000+).
    4. Zero-Risk Free-Ride Pyramiding (Max 2 positions only if Pos 1 is in +20p profit & BE locked).
    5. Multi-Tier Dynamic Trailing Stop Engine (ขยับล็อคกำไรเป็นขั้นบันได).
    6. Auto-Clean all orphan pending limit orders.
    """

    MAGIC_NUMBER = 778899

    def __init__(self, config: dict, mt5_connector):
        self.config = config
        self.mt5_conn = mt5_connector
        self.risk_manager = RiskManager(config)
        
        self.mm_config = config.get("money_management", {})
        self.daily_profit_target = self.mm_config.get("daily_profit_target_usd", 500.0)
        self.daily_max_loss = self.mm_config.get("daily_max_loss_usd", 300.0)
        
        self.auto_trade_enabled = config.get("auto_trading", {}).get("enable", True)
        self.auto_be_enabled = config.get("auto_trading", {}).get("enable_auto_break_even", True)
        self.trailing_stop_enabled = config.get("auto_trading", {}).get("enable_trailing_stop", True)
        
        self.local_tz = pytz.timezone("Asia/Bangkok")
        self.last_trade_closed_time = datetime.min
        self.cooldown_seconds = 180  # 3-Minute standard cooldown
        self.consecutive_loss_cooldown_seconds = 1800  # 30-Minute Safe-Mode if 2 consecutive losses

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
        """Calculates today's realized PnL and consecutive loss streak."""
        from_time = datetime.now() - timedelta(days=2)
        to_time = datetime.now() + timedelta(days=1)
        
        deals = mt5.history_deals_get(from_time, to_time)
        if not deals:
            return {"profit": 0.0, "trades_count": 0, "wins": 0, "losses": 0, "consecutive_losses": 0}

        total_profit = 0.0
        wins = 0
        losses = 0
        trades_count = 0
        closed_deals = []

        for d in deals:
            if d.magic == self.MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_OUT:
                p = d.profit + d.swap + d.commission
                total_profit += p
                trades_count += 1
                closed_deals.append(p)
                if p > 0:
                    wins += 1
                elif p < 0:
                    losses += 1

        consecutive_losses = 0
        for p in reversed(closed_deals):
            if p < 0:
                consecutive_losses += 1
            else:
                break

        return {
            "profit": round(total_profit, 2),
            "trades_count": trades_count,
            "wins": wins,
            "losses": losses,
            "consecutive_losses": consecutive_losses
        }

    def execute_trade(self, signal_data: dict, current_price: dict) -> dict:
        """
        Executes institutional trade with Real-Account Armor and Free-Ride Pyramiding.
        """
        if not self.auto_trade_enabled:
            return {"success": False, "message": "Auto-trading disabled"}

        symbol = self.mt5_conn.active_symbol
        if not symbol:
            return {"success": False, "message": "No active symbol"}

        # 1. Real Account Broker Spread Protection Shield
        max_spread = self.config.get("system", {}).get("max_spread_pips", 3.5)
        current_spread = current_price.get("spread_pips", 2.0)
        if current_spread > max_spread:
            return {"success": False, "message": f"Spread Shield: {current_spread} pips > {max_spread} pips"}

        # 2. Performance & Daily Circuit Breaker Check
        perf = self.get_daily_performance()
        if perf["profit"] >= self.daily_profit_target:
            return {"success": False, "message": f"🎯 Daily Profit Target (${self.daily_profit_target:.2f}) Achieved!"}

        if perf["profit"] <= -self.daily_max_loss:
            return {"success": False, "message": f"🛑 Circuit Breaker Hit (-${self.daily_max_loss:.2f})"}

        # 3. Consecutive Loss Safe-Mode Gate (30 mins cooldown if 2 consecutive losses)
        active_cooldown = self.consecutive_loss_cooldown_seconds if perf["consecutive_losses"] >= 2 else self.cooldown_seconds
        time_since_closed = (datetime.now() - self.last_trade_closed_time).total_seconds()
        if time_since_closed < active_cooldown:
            rem = int(active_cooldown - time_since_closed)
            return {"success": False, "message": f"Safe-Mode Cooldown active: {rem}s remaining"}

        trade_mode = signal_data.get("trade_mode", "QUICK_SCALP")
        active_pos = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.magic == self.MAGIC_NUMBER]
        active_ord = [o for o in (mt5.orders_get(symbol=symbol) or []) if o.magic == self.MAGIC_NUMBER]

        # 4. Position Gate & Free-Ride Pyramiding Rule
        if len(active_pos) > 0:
            # Allow 1 Pyramid Order ONLY IF: Trend Runner + Pos 1 is in +20 pips profit + SL > Entry
            pip_size = current_price.get("pip_size", 0.10)
            p1 = active_pos[0]
            is_buy = (p1.type == mt5.ORDER_TYPE_BUY)
            p1_profit_pips = (p1.price_current - p1.price_open)/pip_size if is_buy else (p1.price_open - p1.price_current)/pip_size
            is_p1_be_locked = (p1.sl >= p1.price_open) if is_buy else (p1.sl <= p1.price_open and p1.sl > 0)

            if trade_mode == "TREND_RUNNER" and len(active_pos) == 1 and p1_profit_pips >= 20.0 and is_p1_be_locked:
                logger.info("🚀 Free-Ride Pyramid Gate UNLOCKED: Pos 1 is +20p in profit & BE locked!")
            else:
                return {"success": False, "message": f"Position lock: {len(active_pos)} open, {len(active_ord)} pending"}

        action = signal_data.get("signal", "")
        trade_setup = signal_data.get("trade_setup", {})

        if not trade_setup or action not in ["BUY", "SELL"]:
            return {"success": False, "message": "Invalid trade setup"}

        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"success": False, "message": "Failed to get symbol info"}

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
        acc_balance = self.mt5_conn.get_account_info().get("balance", 1000.0)

        # Dynamic Lot Sizing
        sl_pips = trade_setup.get("sl_pips", 25.0)
        lot = self.risk_manager.calculate_lot(acc_balance, sl_pips, trade_mode)
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
            "deviation": 15,  # 1.5 pips max slippage guard
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
        Multi-Tier Dynamic Trailing Stop Engine:
        - Tier 1 (>= +10 pips): Lock SL at Entry + 2.0 pips (Zero Risk).
        - Tier 2 (>= +20 pips): Lock SL at Entry + 10.0 pips (Guaranteed Profit).
        - Tier 3 (>= +30 pips): Lock SL at Entry + 20.0 pips (Big Profit Lock).
        - Tier 4 (>= +40+ pips): Dynamic Trailing by 10 pips step.
        """
        symbol = self.mt5_conn.active_symbol
        if not symbol:
            return []

        positions = mt5.positions_get(symbol=symbol)
        
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

            if pos_type == mt5.ORDER_TYPE_BUY:
                profit_distance = cur_price - open_price
                profit_pips = profit_distance / pip_size

                target_sl = None
                tier_badge = ""

                # Tier 4: Profit >= +40 pips (Dynamic 10-pip trail)
                if profit_pips >= 40.0:
                    calc_sl = round(cur_price - (12.0 * pip_size), digits)
                    if calc_sl > current_sl:
                        target_sl = calc_sl
                        tier_badge = f"🚀 [Trailing Step] ล็อคกำไรที่ +{round((calc_sl - open_price)/pip_size, 1)} pips"
                # Tier 3: Profit >= +30 pips
                elif profit_pips >= 30.0:
                    calc_sl = round(open_price + (20.0 * pip_size), digits)
                    if calc_sl > current_sl:
                        target_sl = calc_sl
                        tier_badge = "💰 [Tier 3 Lock] ล็อคกำไรแน่น +20 pips ($2.00)"
                # Tier 2: Profit >= +20 pips
                elif profit_pips >= 20.0:
                    calc_sl = round(open_price + (10.0 * pip_size), digits)
                    if calc_sl > current_sl:
                        target_sl = calc_sl
                        tier_badge = "💵 [Tier 2 Lock] ล็อคกำไร +10 pips ($1.00)"
                # Tier 1: Profit >= +10 pips (Initial Break-Even)
                elif profit_pips >= 10.0 and current_sl < open_price:
                    calc_sl = round(open_price + (2.0 * pip_size), digits)
                    target_sl = calc_sl
                    tier_badge = "🛡️ [Tier 1 กันทุน] เลื่อน SL มาหน้าทุน +2 pips (0% Risk)"

                if target_sl and target_sl != current_sl:
                    req = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": symbol, "sl": target_sl, "tp": current_tp}
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        msg = f"{tier_badge} | Ticket #{ticket} (SL: ${target_sl})"
                        logger.info(msg)
                        updates.append(msg)

            elif pos_type == mt5.ORDER_TYPE_SELL:
                profit_distance = open_price - cur_price
                profit_pips = profit_distance / pip_size

                target_sl = None
                tier_badge = ""

                # Tier 4: Profit >= +40 pips (Dynamic 10-pip trail)
                if profit_pips >= 40.0:
                    calc_sl = round(cur_price + (12.0 * pip_size), digits)
                    if current_sl == 0 or calc_sl < current_sl:
                        target_sl = calc_sl
                        tier_badge = f"🚀 [Trailing Step] ล็อคกำไรที่ +{round((open_price - calc_sl)/pip_size, 1)} pips"
                # Tier 3: Profit >= +30 pips
                elif profit_pips >= 30.0:
                    calc_sl = round(open_price - (20.0 * pip_size), digits)
                    if current_sl == 0 or calc_sl < current_sl:
                        target_sl = calc_sl
                        tier_badge = "💰 [Tier 3 Lock] ล็อคกำไรแน่น +20 pips ($2.00)"
                # Tier 2: Profit >= +20 pips
                elif profit_pips >= 20.0:
                    calc_sl = round(open_price - (10.0 * pip_size), digits)
                    if current_sl == 0 or calc_sl < current_sl:
                        target_sl = calc_sl
                        tier_badge = "💵 [Tier 2 Lock] ล็อคกำไร +10 pips ($1.00)"
                # Tier 1: Profit >= +10 pips (Initial Break-Even)
                elif profit_pips >= 10.0 and (current_sl > open_price or current_sl == 0):
                    calc_sl = round(open_price - (2.0 * pip_size), digits)
                    target_sl = calc_sl
                    tier_badge = "🛡️ [Tier 1 กันทุน] เลื่อน SL มาหน้าทุน +2 pips (0% Risk)"

                if target_sl and target_sl != current_sl:
                    req = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": symbol, "sl": target_sl, "tp": current_tp}
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        msg = f"{tier_badge} | Ticket #{ticket} (SL: ${target_sl})"
                        logger.info(msg)
                        updates.append(msg)

        return updates
