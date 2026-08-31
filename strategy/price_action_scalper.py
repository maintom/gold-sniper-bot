# ==========================================================
# Institutional Adaptive Multi-TF & Playbook Scalper
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
        self.strict_trend = self.strat_config.get("strict_trend_following", True)

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
        Adaptive Multi-Timeframe Strategy Matrix:
        1. Evaluates M15/H1 Trend Runner
        2. Evaluates M5 Institutional Playbook (ย่อ Buy / เด้ง Sell)
        3. Evaluates M1 Micro Sniper Rejection
        """
        result = {
            "signal": "WAIT",
            "timeframe": "M5 (Top-Down Playbook)",
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

        if not news_status.get("is_safe", True):
            result["reasons"].append(f"⚠️ {news_status.get('message')}")
            return result

        is_active, session_desc = self.is_session_active()
        result["session_active"] = is_active
        result["session_desc"] = session_desc
        if not is_active:
            result["reasons"].append(f"⏳ {session_desc}")
            return result

        if candles_m5 is None or len(candles_m5) < 30 or candles_m15 is None or len(candles_m15) < 25:
            result["reasons"].append("Insufficient historical candle data.")
            return result

        # Macro Levels
        self.macro_engine.update_from_candles(candles_d1, candles_h1, candles_m5)
        mid_price = current_price.get("mid", 2500.0)
        pip_size = current_price.get("pip_size", 0.10)
        macro_info = self.macro_engine.check_macro_confluence(mid_price, pip_size)
        result["macro_zone"] = macro_info.get("description", "None")

        # Trend Structure
        m15_struct = SMCEngine.analyze_market_structure(candles_m15)
        h1_struct = SMCEngine.analyze_market_structure(candles_h1) if candles_h1 is not None and len(candles_h1) >= 20 else {"trend": "NEUTRAL"}
        
        m15_trend = m15_struct.get("trend", "NEUTRAL")
        h1_trend = h1_struct.get("trend", "NEUTRAL")
        above_ema50 = m15_struct.get("current_above_ema50", False)
        result["htf_trend"] = f"M15: {m15_trend} (EMA50: {'ABOVE' if above_ema50 else 'BELOW'}) | H1: {h1_trend}"

        # Candle Data
        last_m5_bar = candles_m5.iloc[-2]
        bar_time = candles_m5.index[-2]
        result["candle_time"] = bar_time

        sweep_m5 = SMCEngine.detect_liquidity_sweep(candles_m5, lookback=20)
        sweep_m1 = SMCEngine.detect_liquidity_sweep(candles_m1, lookback=15) if candles_m1 is not None and len(candles_m1) >= 20 else {"sweep_type": "NONE"}
        fvgs_m5 = SMCEngine.detect_fair_value_gaps(candles_m5, max_lookback=10)

        candle_m5 = IndicatorEngine.analyze_candlestick(last_m5_bar['open'], last_m5_bar['high'], last_m5_bar['low'], last_m5_bar['close'])
        last_m1_bar = candles_m1.iloc[-2] if candles_m1 is not None and len(candles_m1) >= 5 else last_m5_bar
        candle_m1 = IndicatorEngine.analyze_candlestick(last_m1_bar['open'], last_m1_bar['high'], last_m1_bar['low'], last_m1_bar['close'])

        active_sweep = sweep_m5 if sweep_m5["sweep_type"] != "NONE" else sweep_m1
        active_candle = candle_m1 if (candle_m1["is_pinbar_bull"] or candle_m1["is_pinbar_bear"]) else candle_m5

        mtf_metrics = {
            "m15_trend": m15_trend,
            "h1_trend": h1_trend,
            "above_ema50": above_ema50
        }

        fvg_bullish_tap = any(f["type"] == "BULLISH_FVG" and f["bottom"] <= mid_price <= f["top"] + (3.0 * pip_size) for f in fvgs_m5)
        fvg_bearish_tap = any(f["type"] == "BEARISH_FVG" and f["bottom"] - (3.0 * pip_size) <= mid_price <= f["top"] for f in fvgs_m5)

        # -----------------------------------------------------------------
        # BUY EVALUATION (ย่อ BUY / M15 รันเทรนด์)
        # -----------------------------------------------------------------
        if m15_trend == "BULLISH" or above_ema50 or (macro_info.get("is_at_key_level") and macro_info.get("zone_type") == "SUPPORT"):
            buy_ai = AICandleClassifier.evaluate_setup("BUY", active_candle, active_sweep, macro_info, mtf_metrics, fvg_bullish_tap, is_active)

            is_dip_rejection = (
                active_sweep.get("sweep_type") == "BULLISH_SWEEP" or 
                active_candle.get("is_pinbar_bull", False) or 
                fvg_bullish_tap or 
                last_m5_bar['close'] > last_m5_bar['open']
            )

            if buy_ai["approved"] and is_dip_rejection:
                sl_ref = active_sweep.get("wick_low", min(last_m5_bar['low'], last_m1_bar['low']))
                trade = self.risk_manager.calculate_trade_levels("BUY", mid_price, sl_ref, pip_size, account_balance)
                
                if trade.get("is_valid", False):
                    # Tag Mode
                    if h1_trend == "BULLISH" and m15_trend == "BULLISH":
                        mode_badge = "M15/H1 (🏃 รันเทรนด์ใหญ่ขาขึ้น)"
                    elif active_sweep.get("sweep_type") == "BULLISH_SWEEP":
                        mode_badge = "M5 (🎯 ย่อ BUY กวาดสภาพคล่อง)"
                    else:
                        mode_badge = "M5 (📈 ย่อ BUY ตามเทรนด์)"

                    result["signal"] = "BUY"
                    result["timeframe"] = mode_badge
                    result["win_probability"] = buy_ai["win_probability"]
                    result["grade"] = buy_ai["grade"]
                    result["stars"] = buy_ai["stars"]
                    result["trade_setup"] = trade
                    result["reasons"] = [
                        f"📈 กลยุทธ์: {mode_badge} ({result['htf_trend']})",
                        f"🎯 สัญญาณกลับตัว: SSL Sweep / Rejection Wick ที่ ${sl_ref:.2f}",
                        f"🏛️ แนวรับ/โซน: {macro_info['description']}"
                    ]
                    return result

        # -----------------------------------------------------------------
        # SELL EVALUATION (เด้ง SELL / M15 รันเทรนด์)
        # -----------------------------------------------------------------
        if (m15_trend == "BEARISH" or not above_ema50) and not (m15_trend == "BULLISH" and above_ema50):
            sell_ai = AICandleClassifier.evaluate_setup("SELL", active_candle, active_sweep, macro_info, mtf_metrics, fvg_bearish_tap, is_active)

            is_rally_rejection = (
                active_sweep.get("sweep_type") == "BEARISH_SWEEP" or 
                active_candle.get("is_pinbar_bear", False) or 
                fvg_bearish_tap or 
                last_m5_bar['close'] < last_m5_bar['open']
            )

            if sell_ai["approved"] and is_rally_rejection:
                sl_ref = active_sweep.get("wick_high", max(last_m5_bar['high'], last_m1_bar['high']))
                trade = self.risk_manager.calculate_trade_levels("SELL", mid_price, sl_ref, pip_size, account_balance)

                if trade.get("is_valid", False):
                    # Tag Mode
                    if h1_trend == "BEARISH" and m15_trend == "BEARISH":
                        mode_badge = "M15/H1 (🏃 รันเทรนด์ใหญ่ขาลง)"
                    elif active_sweep.get("sweep_type") == "BEARISH_SWEEP":
                        mode_badge = "M5 (🎯 เด้ง SELL กวาดสภาพคล่อง)"
                    else:
                        mode_badge = "M5 (📉 เด้ง SELL ตามเทรนด์)"

                    result["signal"] = "SELL"
                    result["timeframe"] = mode_badge
                    result["win_probability"] = sell_ai["win_probability"]
                    result["grade"] = sell_ai["grade"]
                    result["stars"] = sell_ai["stars"]
                    result["trade_setup"] = trade
                    result["reasons"] = [
                        f"📉 กลยุทธ์: {mode_badge} ({result['htf_trend']})",
                        f"🎯 สัญญาณกลับตัว: BSL Sweep / Rejection Wick ที่ ${sl_ref:.2f}",
                        f"🏛️ แนวต้าน/โซน: {macro_info['description']}"
                    ]
                    return result

        result["reasons"] = [f"รอจังหวะ ย่อ Buy / เด้ง Sell / รันเทรนด์ ({result['htf_trend']})"]
        return result
