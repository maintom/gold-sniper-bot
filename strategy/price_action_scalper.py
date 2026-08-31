# ==========================================================
# True Institutional Premium/Discount & 2-Way Scalper
# ==========================================================
import logging
from datetime import datetime
import pytz
import pandas as pd

from strategy.indicators import IndicatorEngine
from strategy.smc_engine import SMCEngine
from strategy.risk_manager import RiskManager
from strategy.macro_levels import MacroLevelsEngine
from strategy.ai_candle_classifier import AICandleClassifier

logger = logging.getLogger("PriceActionScalper")

class PriceActionScalper:

    def __init__(self, config: dict):
        self.config = config
        self.strat_config = config.get("strategy", {})
        self.risk_manager = RiskManager(config)
        self.macro_engine = MacroLevelsEngine(tolerance_pips=25.0)
        self.local_tz = pytz.timezone("Asia/Bangkok")
        
        self.sessions = self.strat_config.get("sessions", {})
        self.session_filter_enabled = self.sessions.get("enable_session_filter", True)
        self.allowed_ranges = self.sessions.get("allowed_ranges_bkk", [])

    def is_session_active(self) -> tuple[bool, str]:
        if not self.session_filter_enabled:
            return True, "Session filter disabled"

        now_bkk = datetime.now(self.local_tz)
        current_hm = now_bkk.strftime("%H:%M")

        for r in self.allowed_ranges:
            start = r.get("start", "00:00")
            end = r.get("end", "23:59")
            if start <= end:
                if start <= current_hm <= end:
                    return True, f"Active Session ({start} - {end} BKK)"
            else:  # Spans past midnight
                if current_hm >= start or current_hm <= end:
                    return True, f"Active Session ({start} - {end} BKK)"

        return False, f"Outside optimal trading sessions (Current BKK: {current_hm})"

    def analyze(self, candles_m1: pd.DataFrame, candles_m5: pd.DataFrame, 
                candles_m15: pd.DataFrame, candles_h1: pd.DataFrame, 
                candles_d1: pd.DataFrame, current_price: dict, 
                news_status: dict, account_balance: float = 1000.0) -> dict:
        """
        True Institutional SMC Engine with Equilibrium Filter:
        - BUY: Only in DISCOUNT Zone (< 50% Equilibrium) + SSL Sweep / FVG Tap + Bullish Rejection
        - SELL: Only in PREMIUM Zone (> 50% Equilibrium) + BSL Sweep / FVG Tap + Bearish Rejection
        """
        result = {
            "signal": "WAIT",
            "timeframe": "M5 Premium/Discount Scalper",
            "candle_time": None,
            "confluence_score": 0,
            "stars": "",
            "win_probability": 0.0,
            "grade": "NONE",
            "trade_setup": None,
            "macro_zone": "None",
            "reasons": [],
            "htf_trend": "NEUTRAL",
            "ltf_structure": "NEUTRAL",
            "session_active": True,
            "session_desc": "",
            "news_safe": news_status.get("is_safe", True),
            "news_desc": news_status.get("message", "")
        }

        # 1. News Shield Check
        if not news_status.get("is_safe", True):
            result["reasons"].append(f"⚠️ {news_status.get('message')}")
            return result

        # 2. Session Check
        is_active, session_desc = self.is_session_active()
        result["session_active"] = is_active
        result["session_desc"] = session_desc
        if not is_active:
            result["reasons"].append(f"⏳ {session_desc}")
            return result

        if candles_m5 is None or len(candles_m5) < 30 or candles_m15 is None or len(candles_m15) < 25:
            result["reasons"].append("Insufficient historical candle data.")
            return result

        # 3. Macro Levels Computation
        self.macro_engine.update_from_candles(candles_d1, candles_h1, candles_m5)
        mid_price = current_price.get("mid", 2500.0)
        pip_size = current_price.get("pip_size", 0.10)
        macro_info = self.macro_engine.check_macro_confluence(mid_price, pip_size)
        result["macro_zone"] = macro_info.get("description", "None")

        # 4. Swing High / Low Equilibrium (50% Range)
        recent_m5 = candles_m5.tail(30)
        swing_high = recent_m5["high"].max()
        swing_low = recent_m5["low"].min()
        equilibrium = (swing_high + swing_low) / 2.0
        is_in_premium = (mid_price >= equilibrium)
        is_in_discount = (mid_price <= equilibrium)

        # 5. Master Trend & Structure
        m15_struct = SMCEngine.analyze_market_structure(candles_m15)
        h1_struct = SMCEngine.analyze_market_structure(candles_h1) if candles_h1 is not None and len(candles_h1) >= 20 else {"trend": "NEUTRAL"}
        
        m15_trend = m15_struct.get("trend", "NEUTRAL")
        h1_trend = h1_struct.get("trend", "NEUTRAL")
        above_ema50 = m15_struct.get("current_above_ema50", False)
        result["htf_trend"] = f"M15: {m15_trend} (EMA50: {'ABOVE' if above_ema50 else 'BELOW'}) | H1: {h1_trend}"

        # 6. Candle & SMC Analysis on M5
        last_m5_bar = candles_m5.iloc[-2]
        prev_m5_bar = candles_m5.iloc[-3]
        bar_time = candles_m5.index[-2]
        result["candle_time"] = bar_time

        sweep_m5 = SMCEngine.detect_liquidity_sweep(candles_m5, lookback=20)
        fvgs_m5 = SMCEngine.detect_fair_value_gaps(candles_m5, max_lookback=10)

        candle_m5 = IndicatorEngine.analyze_candlestick(last_m5_bar['open'], last_m5_bar['high'], last_m5_bar['low'], last_m5_bar['close'])
        prev_candle_m5 = IndicatorEngine.analyze_candlestick(prev_m5_bar['open'], prev_m5_bar['high'], prev_m5_bar['low'], prev_m5_bar['close'])
        engulfing_m5 = IndicatorEngine.check_engulfing(prev_candle_m5, candle_m5, prev_m5_bar['open'], prev_m5_bar['close'], last_m5_bar['open'], last_m5_bar['close'])

        fvg_bullish_tap = any(f["type"] == "BULLISH_FVG" and f["bottom"] <= mid_price <= f["top"] + (3.0 * pip_size) for f in fvgs_m5)
        fvg_bearish_tap = any(f["type"] == "BEARISH_FVG" and f["bottom"] - (3.0 * pip_size) <= mid_price <= f["top"] for f in fvgs_m5)

        mtf_metrics = {
            "m15_trend": m15_trend,
            "h1_trend": h1_trend,
            "above_ema50": above_ema50
        }

        # -----------------------------------------------------------------
        # BUY SETUP: MUST BE IN DISCOUNT ZONE (< Equilibrium)
        # -----------------------------------------------------------------
        has_bullish_smc = (sweep_m5["sweep_type"] == "BULLISH_SWEEP") or (macro_info.get("is_at_key_level") and macro_info.get("zone_type") == "SUPPORT") or fvg_bullish_tap
        has_bullish_rejection = (
            candle_m5.get("is_pinbar_bull", False) or 
            (engulfing_m5 == "BULLISH_ENGULFING") or 
            (candle_m5.get("lower_wick_pct", 0) >= 35.0)
        )

        if is_in_discount and has_bullish_smc and has_bullish_rejection:
            buy_ai = AICandleClassifier.evaluate_setup("BUY", candle_m5, sweep_m5, macro_info, mtf_metrics, fvg_bullish_tap, is_active)

            if buy_ai["approved"]:
                sl_ref = sweep_m5.get("wick_low", last_m5_bar['low'])
                trade = self.risk_manager.calculate_trade_levels("BUY", mid_price, sl_ref, pip_size, account_balance)

                if trade.get("is_valid", False):
                    mode_badge = "M5 (🎯 ย่อ BUY ใน Discount Zone)" if not (m15_trend == "BULLISH" and h1_trend == "BULLISH") else "M15/H1 (🏃 รันเทรนด์ใหญ่ขาขึ้น)"
                    result["signal"] = "BUY"
                    result["timeframe"] = mode_badge
                    result["win_probability"] = buy_ai["win_probability"]
                    result["grade"] = buy_ai["grade"]
                    result["stars"] = buy_ai["stars"]
                    result["trade_setup"] = trade
                    result["reasons"] = [
                        f"📈 กลยุทธ์: {mode_badge} (ราคา ${mid_price:.2f} ต่ำกว่า EQ ${equilibrium:.2f})",
                        f"🎯 สัญญาณกลับตัว: SSL Sweep / Rejection Wick ที่ ${sl_ref:.2f}",
                        f"🏛️ แนวรับ/โซน: {macro_info['description']}"
                    ]
                    return result

        # -----------------------------------------------------------------
        # SELL SETUP: MUST BE IN PREMIUM ZONE (> Equilibrium)
        # -----------------------------------------------------------------
        has_bearish_smc = (sweep_m5["sweep_type"] == "BEARISH_SWEEP") or (macro_info.get("is_at_key_level") and macro_info.get("zone_type") == "RESISTANCE") or fvg_bearish_tap
        has_bearish_rejection = (
            candle_m5.get("is_pinbar_bear", False) or 
            (engulfing_m5 == "BEARISH_ENGULFING") or 
            (candle_m5.get("upper_wick_pct", 0) >= 35.0)
        )

        if is_in_premium and has_bearish_smc and has_bearish_rejection:
            sell_ai = AICandleClassifier.evaluate_setup("SELL", candle_m5, sweep_m5, macro_info, mtf_metrics, fvg_bearish_tap, is_active)

            if sell_ai["approved"]:
                sl_ref = sweep_m5.get("wick_high", last_m5_bar['high'])
                trade = self.risk_manager.calculate_trade_levels("SELL", mid_price, sl_ref, pip_size, account_balance)

                if trade.get("is_valid", False):
                    mode_badge = "M5 (🎯 เด้ง SELL ใน Premium Zone)" if not (m15_trend == "BEARISH" and h1_trend == "BEARISH") else "M15/H1 (🏃 รันเทรนด์ใหญ่ขาลง)"
                    result["signal"] = "SELL"
                    result["timeframe"] = mode_badge
                    result["win_probability"] = sell_ai["win_probability"]
                    result["grade"] = sell_ai["grade"]
                    result["stars"] = sell_ai["stars"]
                    result["trade_setup"] = trade
                    result["reasons"] = [
                        f"📉 กลยุทธ์: {mode_badge} (ราคา ${mid_price:.2f} สูงกว่า EQ ${equilibrium:.2f})",
                        f"🎯 สัญญาณกลับตัว: BSL Sweep / Rejection Wick ที่ ${sl_ref:.2f}",
                        f"🏛️ แนวต้าน/โซน: {macro_info['description']}"
                    ]
                    return result

        zone_str = f"ราคาอยู่ที่ ${mid_price:.2f} (EQ: ${equilibrium:.2f} | โซน: {'PREMIUM' if is_in_premium else 'DISCOUNT'})"
        result["reasons"] = [f"รอจังหวะ Rejection ที่ยอดขอบโซน ({zone_str})"]
        return result
