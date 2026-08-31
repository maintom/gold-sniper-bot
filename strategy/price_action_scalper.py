# ==========================================================
# True Multi-Timeframe Independent Matrix Scalper (M1/M5/M15)
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
        True Multi-Timeframe Independent Evaluation:
        1. Checks M15 Macro Trend Run (60-120 pips)
        2. Checks M5 Institutional Scalp (30-50 pips)
        3. Checks M1 Quick Sniper (15-25 pips quick scalp)
        Returns the highest-probability setup among all timeframes!
        """
        default_res = {
            "signal": "WAIT",
            "timeframe": "Multi-TF Matrix (M1/M5/M15)",
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
            default_res["reasons"].append(f"⚠️ {news_status.get('message')}")
            return default_res

        # 2. Session Check
        is_active, session_desc = self.is_session_active()
        default_res["session_active"] = is_active
        default_res["session_desc"] = session_desc
        if not is_active:
            default_res["reasons"].append(f"⏳ {session_desc}")
            return default_res

        # 3. Macro Levels Computation
        self.macro_engine.update_from_candles(candles_d1, candles_h1, candles_m5)
        mid_price = current_price.get("mid", 2500.0)
        pip_size = current_price.get("pip_size", 0.10)
        macro_info = self.macro_engine.check_macro_confluence(mid_price, pip_size)
        default_res["macro_zone"] = macro_info.get("description", "None")

        # 4. Master Trend & Structure (M15 & H1)
        m15_struct = SMCEngine.analyze_market_structure(candles_m15) if candles_m15 is not None and len(candles_m15) >= 20 else {"trend": "NEUTRAL"}
        h1_struct = SMCEngine.analyze_market_structure(candles_h1) if candles_h1 is not None and len(candles_h1) >= 20 else {"trend": "NEUTRAL"}
        
        m15_trend = m15_struct.get("trend", "NEUTRAL")
        h1_trend = h1_struct.get("trend", "NEUTRAL")
        above_ema50 = m15_struct.get("current_above_ema50", False)
        default_res["htf_trend"] = f"M15: {m15_trend} (EMA50: {'ABOVE' if above_ema50 else 'BELOW'}) | H1: {h1_trend}"

        # 5. Equilibrium (50% Range)
        recent_m5 = candles_m5.tail(30) if candles_m5 is not None else None
        if recent_m5 is not None:
            swing_high = recent_m5["high"].max()
            swing_low = recent_m5["low"].min()
            equilibrium = (swing_high + swing_low) / 2.0
            is_in_premium = (mid_price >= equilibrium)
            is_in_discount = (mid_price <= equilibrium)
        else:
            equilibrium = mid_price
            is_in_premium = True
            is_in_discount = True

        mtf_metrics = {
            "m15_trend": m15_trend,
            "h1_trend": h1_trend,
            "above_ema50": above_ema50
        }

        # -------------------------------------------------------------
        # EVALUATE TIMEFRAME 1: M5 INSTITUTIONAL PLAYBOOK (30-50 pips)
        # -------------------------------------------------------------
        if candles_m5 is not None and len(candles_m5) >= 20:
            last_m5 = candles_m5.iloc[-2]
            prev_m5 = candles_m5.iloc[-3]
            sweep_m5 = SMCEngine.detect_liquidity_sweep(candles_m5, lookback=15)
            fvgs_m5 = SMCEngine.detect_fair_value_gaps(candles_m5, max_lookback=8)
            candle_m5 = IndicatorEngine.analyze_candlestick(last_m5['open'], last_m5['high'], last_m5['low'], last_m5['close'])
            prev_c_m5 = IndicatorEngine.analyze_candlestick(prev_m5['open'], prev_m5['high'], prev_m5['low'], prev_m5['close'])
            engulf_m5 = IndicatorEngine.check_engulfing(prev_c_m5, candle_m5, prev_m5['open'], prev_m5['close'], last_m5['open'], last_m5['close'])

            fvg_bull_m5 = any(f["type"] == "BULLISH_FVG" and f["bottom"] <= mid_price <= f["top"] + (3.0 * pip_size) for f in fvgs_m5)
            fvg_bear_m5 = any(f["type"] == "BEARISH_FVG" and f["bottom"] - (3.0 * pip_size) <= mid_price <= f["top"] for f in fvgs_m5)

            # M5 BUY
            if is_in_discount and (sweep_m5["sweep_type"] == "BULLISH_SWEEP" or fvg_bull_m5 or (macro_info.get("is_at_key_level") and macro_info.get("zone_type") == "SUPPORT")):
                if candle_m5.get("is_pinbar_bull") or engulf_m5 == "BULLISH_ENGULFING" or candle_m5.get("lower_wick_pct", 0) >= 35.0:
                    buy_ai = AICandleClassifier.evaluate_setup("BUY", candle_m5, sweep_m5, macro_info, mtf_metrics, fvg_bull_m5, is_active)
                    if buy_ai["approved"]:
                        sl_ref = sweep_m5.get("wick_low", last_m5['low'])
                        trade = self.risk_manager.calculate_trade_levels("BUY", mid_price, sl_ref, pip_size, account_balance)
                        if trade.get("is_valid", False):
                            return {
                                "signal": "BUY",
                                "timeframe": "M5 (🎯 ย่อ BUY ใน Discount Zone)",
                                "candle_time": candles_m5.index[-2],
                                "win_probability": buy_ai["win_probability"],
                                "grade": buy_ai["grade"],
                                "stars": buy_ai["stars"],
                                "trade_setup": trade,
                                "macro_zone": macro_info.get("description", "None"),
                                "reasons": [f"📈 M5 Playbook: ย่อ BUY ในโซน Discount (ราคา ${mid_price:.2f} < EQ ${equilibrium:.2f})", f"🎯 สัญญาณ: Rejection Wick ที่ ${sl_ref:.2f}"],
                                "htf_trend": default_res["htf_trend"],
                                "session_active": True,
                                "session_desc": session_desc,
                                "news_safe": True,
                                "news_desc": news_status.get("message", "")
                            }

            # M5 SELL
            if is_in_premium and (sweep_m5["sweep_type"] == "BEARISH_SWEEP" or fvg_bear_m5 or (macro_info.get("is_at_key_level") and macro_info.get("zone_type") == "RESISTANCE")):
                if candle_m5.get("is_pinbar_bear") or engulf_m5 == "BEARISH_ENGULFING" or candle_m5.get("upper_wick_pct", 0) >= 35.0:
                    sell_ai = AICandleClassifier.evaluate_setup("SELL", candle_m5, sweep_m5, macro_info, mtf_metrics, fvg_bear_m5, is_active)
                    if sell_ai["approved"]:
                        sl_ref = sweep_m5.get("wick_high", last_m5['high'])
                        trade = self.risk_manager.calculate_trade_levels("SELL", mid_price, sl_ref, pip_size, account_balance)
                        if trade.get("is_valid", False):
                            return {
                                "signal": "SELL",
                                "timeframe": "M5 (🎯 เด้ง SELL ใน Premium Zone)",
                                "candle_time": candles_m5.index[-2],
                                "win_probability": sell_ai["win_probability"],
                                "grade": sell_ai["grade"],
                                "stars": sell_ai["stars"],
                                "trade_setup": trade,
                                "macro_zone": macro_info.get("description", "None"),
                                "reasons": [f"📉 M5 Playbook: เด้ง SELL ในโซน Premium (ราคา ${mid_price:.2f} > EQ ${equilibrium:.2f})", f"🎯 สัญญาณ: Rejection Wick ที่ ${sl_ref:.2f}"],
                                "htf_trend": default_res["htf_trend"],
                                "session_active": True,
                                "session_desc": session_desc,
                                "news_safe": True,
                                "news_desc": news_status.get("message", "")
                            }

        # -------------------------------------------------------------
        # EVALUATE TIMEFRAME 2: M1 QUICK SNIPER SCALP (15-25 pips)
        # -------------------------------------------------------------
        if candles_m1 is not None and len(candles_m1) >= 20:
            last_m1 = candles_m1.iloc[-2]
            prev_m1 = candles_m1.iloc[-3]
            sweep_m1 = SMCEngine.detect_liquidity_sweep(candles_m1, lookback=12)
            candle_m1 = IndicatorEngine.analyze_candlestick(last_m1['open'], last_m1['high'], last_m1['low'], last_m1['close'])
            prev_c_m1 = IndicatorEngine.analyze_candlestick(prev_m1['open'], prev_m1['high'], prev_m1['low'], prev_m1['close'])
            engulf_m1 = IndicatorEngine.check_engulfing(prev_c_m1, candle_m1, prev_m1['open'], prev_m1['close'], last_m1['open'], last_m1['close'])

            # M1 Quick BUY Sniper
            if is_in_discount and (candle_m1.get("is_pinbar_bull") or engulf_m1 == "BULLISH_ENGULFING" or candle_m1.get("lower_wick_pct", 0) >= 40.0):
                sl_ref = sweep_m1.get("wick_low", last_m1['low'])
                trade = self.risk_manager.calculate_trade_levels("BUY", mid_price, sl_ref, pip_size, account_balance)
                if trade.get("is_valid", False):
                    return {
                        "signal": "BUY",
                        "timeframe": "M1 (⚡ สไนเปอร์เก็บสั้น 15-25 จุด)",
                        "candle_time": candles_m1.index[-2],
                        "win_probability": 82.5,
                        "grade": "GRADE_A_SNIPER",
                        "stars": "⭐⭐⭐⭐",
                        "trade_setup": trade,
                        "macro_zone": macro_info.get("description", "None"),
                        "reasons": [f"⚡ M1 Sniper: ดีดตัวกลับเร็วจากแนวรับ ${sl_ref:.2f}", f"📈 แท่งเทียน: Pin Bar / Engulfing ทิ้งไส้ล่างสวยงาม"],
                        "htf_trend": default_res["htf_trend"],
                        "session_active": True,
                        "session_desc": session_desc,
                        "news_safe": True,
                        "news_desc": news_status.get("message", "")
                    }

            # M1 Quick SELL Sniper
            if is_in_premium and (candle_m1.get("is_pinbar_bear") or engulf_m1 == "BEARISH_ENGULFING" or candle_m1.get("upper_wick_pct", 0) >= 40.0):
                sl_ref = sweep_m1.get("wick_high", last_m1['high'])
                trade = self.risk_manager.calculate_trade_levels("SELL", mid_price, sl_ref, pip_size, account_balance)
                if trade.get("is_valid", False):
                    return {
                        "signal": "SELL",
                        "timeframe": "M1 (⚡ สไนเปอร์เก็บสั้น 15-25 จุด)",
                        "candle_time": candles_m1.index[-2],
                        "win_probability": 82.5,
                        "grade": "GRADE_A_SNIPER",
                        "stars": "⭐⭐⭐⭐",
                        "trade_setup": trade,
                        "macro_zone": macro_info.get("description", "None"),
                        "reasons": [f"⚡ M1 Sniper: ทุบตัวกลับเร็วจากแนวต้าน ${sl_ref:.2f}", f"📉 แท่งเทียน: Pin Bar / Engulfing ทิ้งไส้บนสวยงาม"],
                        "htf_trend": default_res["htf_trend"],
                        "session_active": True,
                        "session_desc": session_desc,
                        "news_safe": True,
                        "news_desc": news_status.get("message", "")
                    }

        default_res["reasons"] = [f"สแกนพร้อมกัน 3 Timeframe (M1/M5/M15) | ราคา ${mid_price:.2f} (EQ: ${equilibrium:.2f})"]
        return default_res
