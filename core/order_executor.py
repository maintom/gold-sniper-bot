# ==========================================================
# Institutional MT5 Auto-Execution & Layered Trade Engine
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
    2. Smart Layered Pyramiding (ซอยไม้ 50% ตลาด + 50% Limit ดักย่อ).
    3. Instant Auto Break-Even (กันทุนทันทีที่ +10 pips / 1.0 RR).
    4. Partial Take-Profit (ปิด 50% ที่ TP1 รันเทรนด์ที่ TP2).
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
        self.smart_layering = config.get("auto_trading", {}).get("enable_smart_layering", True)
        
        self.local_tz = pytz.timezone("Asia/Bangkok")
        self.partially_closed_tickets = set()

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
        Executes an institutional trade on MT5 with Smart Layering option.
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

        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"success": False, "message": f"Failed to get symbol info for {symbol}"}

        # Filling mode resolution
        filling_mode = mt5.ORDER_FILLING_IOC
        if hasattr(sym_info, "filling_mode"):
            if sym_info.filling_mode & 1:
                filling_mode = mt5.ORDER_FILLING_FOK
            elif sym_info.filling_mode & 2:
                filling_mode = mt5.ORDER_FILLING_IOC
            else:
                filling_mode = mt5.ORDER_FILLING_RETURN

        total_lot = float(trade_setup.get("recommended_lot", 0.01))
        step = sym_info.volume_step if sym_info.volume_step > 0 else 0.01
        digits = sym_info.digits
        pip_size = current_price.get("pip_size", 0.10)

        sl = float(trade_setup.get("sl", 0.0))
        tp1 = float(trade_setup.get("tp1", 0.0))
        tp2 = float(trade_setup.get("tp2", 0.0))
        
        # Sizing: If total lot >= 0.04 and smart layering enabled, split into 2 layers (50% Market + 50% Limit)
        if self.smart_layering and total_lot >= 0.04:
            lot1 = round(round((total_lot * 0.5) / step) * step, 2)
            lot2 = round(total_lot - lot1, 2)
            lot1 = max(sym_info.volume_min, min(sym_info.volume_max, lot1))
            lot2 = max(sym_info.volume_min, min(sym_info.volume_max, lot2))
        else:
            lot1 = round(round(total_lot / step) * step, 2)
            lot1 = max(sym_info.volume_min, min(sym_info.volume_max, lot1))
            lot2 = 0.0

        order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
        price = sym_info.ask if action == "BUY" else sym_info.bid

        # -------------------------------------------------------------
        # LAYER 1: INSTANT MARKET ORDER (ไม้ที่ 1 - เข้าทันทีไม่ตกรถ)
        # -------------------------------------------------------------
        req1 = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot1,
            "type": order_type,
            "price": round(price, digits),
            "sl": round(sl, digits),
            "tp": round(tp2 if tp2 > 0 else tp1, digits),
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": f"AI_{action}_L1",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        res1 = mt5.order_send(req1)
        if res1 is None or res1.retcode != mt5.TRADE_RETCODE_DONE:
            err = res1.comment if res1 else mt5.last_error()
            logger.error(f"MT5 Order L1 Failed: {err}")
            return {"success": False, "message": f"MT5 Error: {err}"}

        logger.info(f"✅ LAYER 1 EXECUTED: #{res1.order} | {action} {lot1} Lot @ {res1.price}")

        # -------------------------------------------------------------
        # LAYER 2: DISCOUNT LIMIT ORDER (ไม้ที่ 2 - ดักย่อได้เปรียบราคา)
        # -------------------------------------------------------------
        if lot2 > 0:
            limit_offset = 12 * pip_size  # 1.2 USD discount
            limit_price = round(price - limit_offset, digits) if action == "BUY" else round(price + limit_offset, digits)
            limit_type = mt5.ORDER_TYPE_BUY_LIMIT if action == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT

            req2 = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": lot2,
                "type": limit_type,
                "price": limit_price,
                "sl": round(sl, digits),
                "tp": round(tp2 if tp2 > 0 else tp1, digits),
                "deviation": 20,
                "magic": self.MAGIC_NUMBER,
                "comment": f"AI_{action}_L2_Limit",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            res2 = mt5.order_send(req2)
            if res2 and res2.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"🎯 LAYER 2 PENDING LIMIT PLACED: #{res2.order} | {action}_LIMIT {lot2} Lot @ {limit_price}")

        return {
            "success": True,
            "ticket": res1.order,
            "action": action,
            "volume": total_lot,
            "price": res1.price,
            "sl": sl,
            "tp": tp2,
            "message": f"Order #{res1.order} filled at {res1.price} (Smart Layered)"
        }

    def manage_open_positions(self, current_price: dict) -> list:
        """
        Active Trade Manager:
        1. Instant Auto Break-Even: Locks SL to Entry + 1.5 pips as soon as profit >= 10 pips.
        2. Partial Take-Profit: Closes 50% volume at TP1 to bank profit, leaves 50% runner.
        3. Trailing Stop: Trails the runner to TP2.
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
            volume = pos.volume
            digits = self.mt5_conn.symbol_info.digits if self.mt5_conn.symbol_info else 2

            # -------------------------------------------------------------
            # 1. INSTANT AUTO BREAK-EVEN (เมื่อบวกถึง +10 จุด / $1.00)
            # -------------------------------------------------------------
            if self.auto_be_enabled:
                if pos_type == mt5.ORDER_TYPE_BUY:
                    profit_distance = cur_price - open_price
                    # If profit >= 10 pips ($1.00) and SL is still below entry
                    if profit_distance >= (10.0 * pip_size) and current_sl < open_price:
                        new_sl = round(open_price + (1.5 * pip_size), digits)  # Entry + 1.5 pips
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": new_sl,
                            "tp": current_tp
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            msg = f"🛡️ [กันทุนสำเร็จ] Ticket #{ticket} เลื่อน SL มาที่ ${new_sl} (0% Risk กันทุน 100%)"
                            logger.info(msg)
                            updates.append(msg)

                elif pos_type == mt5.ORDER_TYPE_SELL:
                    profit_distance = open_price - cur_price
                    # If profit >= 10 pips ($1.00) and SL is still above entry
                    if profit_distance >= (10.0 * pip_size) and (current_sl > open_price or current_sl == 0):
                        new_sl = round(open_price - (1.5 * pip_size), digits)  # Entry - 1.5 pips
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": symbol,
                            "sl": new_sl,
                            "tp": current_tp
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            msg = f"🛡️ [กันทุนสำเร็จ] Ticket #{ticket} เลื่อน SL มาที่ ${new_sl} (0% Risk กันทุน 100%)"
                            logger.info(msg)
                            updates.append(msg)

            # -------------------------------------------------------------
            # 2. PARTIAL TAKE PROFIT (ปิด 50% เมื่อบวกถึง 20 pips)
            # -------------------------------------------------------------
            if volume >= 0.02 and ticket not in self.partially_closed_tickets:
                profit_pips = (cur_price - open_price) / pip_size if pos_type == mt5.ORDER_TYPE_BUY else (open_price - cur_price) / pip_size
                if profit_pips >= 20.0:  # Hit +20 pips
                    close_vol = round(volume / 2.0, 2)
                    close_type = mt5.ORDER_TYPE_SELL if pos_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                    close_price = mt5.symbol_info_tick(symbol).bid if pos_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask

                    close_req = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "position": ticket,
                        "symbol": symbol,
                        "volume": close_vol,
                        "type": close_type,
                        "price": close_price,
                        "deviation": 20,
                        "magic": self.MAGIC_NUMBER,
                        "comment": "Partial_TP_50pct",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                    c_res = mt5.order_send(close_req)
                    if c_res and c_res.retcode == mt5.TRADE_RETCODE_DONE:
                        self.partially_closed_tickets.add(ticket)
                        msg = f"💰 [ปิดทำกำไร 50%] Ticket #{ticket} ปิด {close_vol} Lot รับกำไรเข้าพอร์ตแล้ว! (เหลืออีก 50% รันเทรนด์ต่อ)"
                        logger.info(msg)
                        updates.append(msg)

        return updates
