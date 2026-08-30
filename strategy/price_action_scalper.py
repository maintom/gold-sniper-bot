# ==========================================================
# Gold Multi-Timeframe Precision Scalper (SMC + Macro + AI)
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
        self.entry_tf = self.strat_config.get("entry_timeframe", "M5")
        self.trend_tf = self.strat_config.get("trend_timeframe", "M15")
        self.higher_tf = self.strat_config.get("higher_timeframe", "H1")
        
        self.sessions = self.strat_config.get("sessions", {})
        self.session_filter_enabled = self.sessions.get("enable_session_filter", True)
        self.allowed_ranges = self.sessions.get("allowed_ranges_bkk", [])
        
        self.risk_manager = RiskManager(config)
        self.macro_engine = MacroLevelsEngine(tolerance_pips=30.0)
        self.local_tz = pytz.timezone("Asia/Bangkok")
        self.last_signal_time = None

    def is_session_active(self) -> tuple[bool, str]:
        """Checks if current time is within high-liquidity trading hours."""
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
        Performs full multi-timeframe precision analysis with Macro Levels & AI Probability.
        """
        result = {
            "signal": "WAIT",
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

        # 1. Check News Shield
        if not news_status.get("is_safe", True):
            result["reasons"].append(f"⚠️ {news_status.get('message')}")
            return result

        # 2. Check Session Filter
        is_active, session_desc = self.is_session_active()
        result["session_active"] = is_active
        result["session_desc"] = session_desc
        if not is_active:
            result["reasons"].append(f"⏳ {session_desc}")
            return result

        # 3. Update Macro Historical Levels (Daily / Weekly / Monthly)
        if candles_d1 is not None and len(candles_d1) >= 5:
            self.macro_engine.update_from_candles(candles_d1)

        mid_price = current_price.get("mid", 2500.0)
        pip_size = current_price.get("pip_size", 0.10)
        macro_info = self.macro_engine.check_macro_confluence(mid_price, pip_size)
        result["macro_zone"] = macro_info.get("description", "None")

        # Select primary entry DataFrame
        entry_df = candles_m5 if self.entry_tf == "M5" else candles_m1
        if len(entry_df) < 30 or len(candles_m15) < 30:
            result["reasons"].append("Insufficient historical candle data.")
            return result

        # 4. Higher Timeframe Market Structure (H1 / M15)
        h1_struct = SMCEngine.analyze_market_structure(candles_h1) if len(candles_h1) >= 20 else {"trend": "NEUTRAL"}
        m15_struct = SMCEngine.analyze_market_structure(candles_m15)
        result["htf_trend"] = f"H1:{h1_struct['trend']} | M15:{m15_struct['trend']}"

        # 5. Entry Timeframe Analysis (M5/M1)
        sweep_data = SMCEngine.detect_liquidity_sweep(entry_df, lookback=20)
        fvgs = SMCEngine.detect_fair_value_gaps(entry_df, max_lookback=10)
        
        # Analyze last closed candle (index -2) and candle before it (index -3)
        bar_prev2 = entry_df.iloc[-3]
        bar_prev1 = entry_df.iloc[-2]
        
        prev_candle = IndicatorEngine.analyze_candlestick(bar_prev2['open'], bar_prev2['high'], bar_prev2['low'], bar_prev2['close'])
        curr_candle = IndicatorEngine.analyze_candlestick(bar_prev1['open'], bar_prev1['high'], bar_prev1['low'], bar_prev1['close'])
        engulfing_type = IndicatorEngine.check_engulfing(
            prev_candle, curr_candle, 
            bar_prev2['open'], bar_prev2['close'], 
            bar_prev1['open'], bar_prev1['close']
        )

        mtf_metrics = {
            "m15_trend": m15_struct["trend"],
            "h1_trend": h1_struct["trend"],
            "above_ema50": m15_struct.get("current_above_ema50", False)
        }

        # Check FVG tap
        fvg_bullish_tap = any(f["type"] == "BULLISH_FVG" and f["bottom"] <= mid_price <= f["top"] + (2.0 * pip_size) for f in fvgs)
        fvg_bearish_tap = any(f["type"] == "BEARISH_FVG" and f["bottom"] - (2.0 * pip_size) <= mid_price <= f["top"] for f in fvgs)

        # -------------------------------------------------------------
        # AI EVALUATION: BUY SETUP
        # -------------------------------------------------------------
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
            buy_reasons = []
            if macro_info.get("is_at_key_level", False):
                buy_reasons.append(f"🏛️ {macro_info['description']}")
            if sweep_data["sweep_type"] == "BULLISH_SWEEP":
                buy_reasons.append(f"🎯 SSL Grab / Liquidity Sweep at ${sweep_data['sweep_level']:.2f}")
            if curr_candle["is_pinbar_bull"]:
                buy_reasons.append("🔨 Bullish Pin Bar (Hammer) Rejection Wick")
            elif engulfing_type == "BULLISH_ENGULFING":
                buy_reasons.append("🔥 Bullish Engulfing Confirmation")
            if fvg_bullish_tap:
                buy_reasons.append("📦 Price mitigating Bullish FVG Zone")
            if mtf_metrics["above_ema50"]:
                buy_reasons.append("✅ Higher Timeframe Trend Alignment")

            sl_ref = sweep_data.get("wick_low", bar_prev1['low'])
            trade = self.risk_manager.calculate_trade_levels("BUY", mid_price, sl_ref, pip_size, account_balance)
            
            if trade.get("is_valid", False):
                result["signal"] = "BUY"
                result["win_probability"] = buy_ai["win_probability"]
                result["grade"] = buy_ai["grade"]
                result["stars"] = buy_ai["stars"]
                result["trade_setup"] = trade
                result["reasons"] = buy_reasons
                return result

        # -------------------------------------------------------------
        # AI EVALUATION: SELL SETUP
        # -------------------------------------------------------------
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
            sell_reasons = []
            if macro_info.get("is_at_key_level", False):
                sell_reasons.append(f"🏛️ {macro_info['description']}")
            if sweep_data["sweep_type"] == "BEARISH_SWEEP":
                sell_reasons.append(f"🎯 BSL Grab / Liquidity Sweep at ${sweep_data['sweep_level']:.2f}")
            if curr_candle["is_pinbar_bear"]:
                sell_reasons.append("🌠 Bearish Pin Bar (Shooting Star) Rejection Wick")
            elif engulfing_type == "BEARISH_ENGULFING":
                sell_reasons.append("🔥 Bearish Engulfing Confirmation")
            if fvg_bearish_tap:
                sell_reasons.append("📦 Price mitigating Bearish FVG Zone")
            if not mtf_metrics["above_ema50"]:
                sell_reasons.append("✅ Higher Timeframe Trend Alignment")

            sl_ref = sweep_data.get("wick_high", bar_prev1['high'])
            trade = self.risk_manager.calculate_trade_levels("SELL", mid_price, sl_ref, pip_size, account_balance)

            if trade.get("is_valid", False):
                result["signal"] = "SELL"
                result["win_probability"] = sell_ai["win_probability"]
                result["grade"] = sell_ai["grade"]
                result["stars"] = sell_ai["stars"]
                result["trade_setup"] = trade
                result["reasons"] = sell_reasons
                return result

        result["reasons"] = ["Market in consolidation / waiting for sniper confluence setup."]
        return result
