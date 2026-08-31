# ==========================================================
# Gold Top-Down Institutional Scalper (HTF Filter -> LTF Trigger)
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
            if start <= current_hm <= end:
                return True, f"Active Session ({start} - {end} BKK)"

        return False, f"Outside optimal trading sessions (Current BKK: {current_hm})"

    def analyze(self, candles_m1: pd.DataFrame, candles_m5: pd.DataFrame, 
                candles_m15: pd.DataFrame, candles_h1: pd.DataFrame, 
                candles_d1: pd.DataFrame, current_price: dict, 
                news_status: dict, account_balance: float = 1000.0) -> dict:
        """
        Executes Institutional Top-Down Analysis:
        1. Higher Timeframe (H1/M15): Filters overall Trend & Macro Bias.
        2. Lower Timeframe (M5/M1): Scans for the ONE high-probability precision trigger.
        """
        result = {
            "signal": "WAIT",
            "timeframe": "M5 (Top-Down)",
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

        # 4. Top-Down HTF Market Structure (H1 + M15)
        h1_struct = SMCEngine.analyze_market_structure(candles_h1) if candles_h1 is not None and len(candles_h1) >= 20 else {"trend": "NEUTRAL"}
        m15_struct = SMCEngine.analyze_market_structure(candles_m15)
        result["htf_trend"] = f"H1: {h1_struct['trend']} | M15: {m15_struct['trend']}"

        # 5. LTF Trigger Scan on M5 (Primary Execution TF)
        last_closed_bar = candles_m5.iloc[-2]
        bar_time = candles_m5.index[-2]
        result["candle_time"] = bar_time

        sweep_data = SMCEngine.detect_liquidity_sweep(candles_m5, lookback=20)
        fvgs = SMCEngine.detect_fair_value_gaps(candles_m5, max_lookback=10)
        curr_candle = IndicatorEngine.analyze_candlestick(
            last_closed_bar['open'], last_closed_bar['high'], 
            last_closed_bar['low'], last_closed_bar['close']
        )

        mtf_metrics = {
            "m15_trend": m15_struct["trend"],
            "h1_trend": h1_struct["trend"],
            "above_ema50": m15_struct.get("current_above_ema50", False)
        }

        fvg_bullish_tap = any(f["type"] == "BULLISH_FVG" and f["bottom"] <= mid_price <= f["top"] + (2.5 * pip_size) for f in fvgs)
        fvg_bearish_tap = any(f["type"] == "BEARISH_FVG" and f["bottom"] - (2.5 * pip_size) <= mid_price <= f["top"] for f in fvgs)

        # -------------------------------------------------------------
        # TOP-DOWN BUY EVALUATION
        # Require HTF Alignment (H1/M15 Bullish or at Major Support)
        # -------------------------------------------------------------
        htf_allows_buy = (m15_struct["trend"] == "BULLISH" or h1_struct["trend"] == "BULLISH" or 
                          (macro_info.get("is_at_key_level") and macro_info.get("zone_type") == "SUPPORT"))

        if htf_allows_buy:
            buy_ai = AICandleClassifier.evaluate_setup(
                action="BUY",
                candle_metrics=curr_candle,
                sweep_metrics=sweep_data,
                macro_metrics=macro_info,
                mtf_metrics=mtf_metrics,
                fvg_present=fvg_bullish_tap,
                session_active=is_active
            )

            if buy_ai["approved"]:
                sl_ref = sweep_data.get("wick_low", last_closed_bar['low'])
                trade = self.risk_manager.calculate_trade_levels("BUY", mid_price, sl_ref, pip_size, account_balance)
                if trade.get("is_valid", False):
                    result["signal"] = "BUY"
                    result["timeframe"] = "M5 (Top-Down H1+M15)"
                    result["win_probability"] = buy_ai["win_probability"]
                    result["grade"] = buy_ai["grade"]
                    result["stars"] = buy_ai["stars"]
                    result["trade_setup"] = trade
                    result["reasons"] = [
                        f"🏛️ HTF Bias: {result['htf_trend']}",
                        f"🎯 M5 Trigger: SSL Sweep at ${sweep_data.get('sweep_level', mid_price):.2f}" if sweep_data.get("sweep_type") == "BULLISH_SWEEP" else "🔨 M5 Rejection Reversal",
                        f"📍 Macro: {macro_info['description']}"
                    ]
                    return result

        # -------------------------------------------------------------
        # TOP-DOWN SELL EVALUATION
        # Require HTF Alignment (H1/M15 Bearish or at Major Resistance)
        # -------------------------------------------------------------
        htf_allows_sell = (m15_struct["trend"] == "BEARISH" or h1_struct["trend"] == "BEARISH" or 
                           (macro_info.get("is_at_key_level") and macro_info.get("zone_type") == "RESISTANCE"))

        if htf_allows_sell:
            sell_ai = AICandleClassifier.evaluate_setup(
                action="SELL",
                candle_metrics=curr_candle,
                sweep_metrics=sweep_data,
                macro_metrics=macro_info,
                mtf_metrics=mtf_metrics,
                fvg_present=fvg_bearish_tap,
                session_active=is_active
            )

            if sell_ai["approved"]:
                sl_ref = sweep_data.get("wick_high", last_closed_bar['high'])
                trade = self.risk_manager.calculate_trade_levels("SELL", mid_price, sl_ref, pip_size, account_balance)
                if trade.get("is_valid", False):
                    result["signal"] = "SELL"
                    result["timeframe"] = "M5 (Top-Down H1+M15)"
                    result["win_probability"] = sell_ai["win_probability"]
                    result["grade"] = sell_ai["grade"]
                    result["stars"] = sell_ai["stars"]
                    result["trade_setup"] = trade
                    result["reasons"] = [
                        f"🏛️ HTF Bias: {result['htf_trend']}",
                        f"🎯 M5 Trigger: BSL Sweep at ${sweep_data.get('sweep_level', mid_price):.2f}" if sweep_data.get("sweep_type") == "BEARISH_SWEEP" else "🌠 M5 Rejection Reversal",
                        f"📍 Macro: {macro_info['description']}"
                    ]
                    return result

        result["reasons"] = ["Market in consolidation / waiting for HTF + LTF top-down alignment."]
        return result
