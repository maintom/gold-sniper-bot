# ==========================================================
# Smart Money Concepts (SMC) & Liquidity Sweep Engine
# ==========================================================
import numpy as np
import pandas as pd
from strategy.indicators import IndicatorEngine

class SMCEngine:

    @staticmethod
    def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 25) -> dict:
        """
        Detects if the most recent closed candle executed a Liquidity Sweep (Stop Hunt).
        Checks both historical swing pivots and recent range extremes (Equal Highs/Lows).
        """
        if len(df) < lookback + 3:
            return {"sweep_type": "NONE", "sweep_level": 0.0, "rejection_wick": 0.0}

        df_swing = IndicatorEngine.find_swing_points(df, window=2)
        
        # Recent closed candle is index -2 (index -1 is current open forming candle)
        curr_bar = df.iloc[-2]
        c_open, c_high, c_low, c_close = curr_bar['open'], curr_bar['high'], curr_bar['low'], curr_bar['close']
        candle_range = c_high - c_low

        if candle_range <= 0.0001:
            return {"sweep_type": "NONE", "sweep_level": 0.0, "rejection_wick": 0.0}

        # Historical window (excluding forming candle -1 and closed candle -2)
        hist_df = df.iloc[-lookback-2:-2]
        hist_swing = df_swing.iloc[-lookback-2:-2]
        
        swing_highs = hist_swing[hist_swing['swing_high']]['swing_high_price'].dropna().tolist()
        swing_lows = hist_swing[hist_swing['swing_low']]['swing_low_price'].dropna().tolist()

        # Add range extremes
        range_min_low = hist_df['low'].min()
        range_max_high = hist_df['high'].max()

        target_lows = list(set(swing_lows + [range_min_low]))
        target_highs = list(set(swing_highs + [range_max_high]))

        # Check Bullish Sweep (Sell-side liquidity grab below key lows)
        for s_low in sorted(target_lows):
            if c_low < s_low and c_close > s_low:
                lower_wick = min(c_open, c_close) - c_low
                if (lower_wick / candle_range) >= 0.35:
                    return {
                        "sweep_type": "BULLISH_SWEEP",
                        "sweep_level": s_low,
                        "rejection_wick": lower_wick,
                        "wick_low": c_low
                    }

        # Check Bearish Sweep (Buy-side liquidity grab above key highs)
        for s_high in sorted(target_highs, reverse=True):
            if c_high > s_high and c_close < s_high:
                upper_wick = c_high - max(c_open, c_close)
                if (upper_wick / candle_range) >= 0.35:
                    return {
                        "sweep_type": "BEARISH_SWEEP",
                        "sweep_level": s_high,
                        "rejection_wick": upper_wick,
                        "wick_high": c_high
                    }

        return {"sweep_type": "NONE", "sweep_level": 0.0, "rejection_wick": 0.0}

    @staticmethod
    def detect_fair_value_gaps(df: pd.DataFrame, max_lookback: int = 15) -> list:
        """
        Identifies recent Fair Value Gaps (FVG) and checks if they remain unmitigated.
        """
        fvgs = []
        if len(df) < 5:
            return fvgs

        n = len(df)
        start_idx = max(2, n - max_lookback)

        for i in range(start_idx, n - 1):
            bar_prev = df.iloc[i - 2]
            bar_curr = df.iloc[i - 1]
            bar_next = df.iloc[i]

            # Bullish FVG: Low of bar_next is strictly higher than High of bar_prev
            if bar_next['low'] > bar_prev['high'] and bar_curr['close'] > bar_curr['open']:
                gap_top = bar_next['low']
                gap_bottom = bar_prev['high']
                gap_size = gap_top - gap_bottom
                
                is_mitigated = False
                for k in range(i + 1, n):
                    if df.iloc[k]['low'] <= gap_bottom:
                        is_mitigated = True
                        break

                if not is_mitigated:
                    fvgs.append({
                        "type": "BULLISH_FVG",
                        "top": gap_top,
                        "bottom": gap_bottom,
                        "mid": (gap_top + gap_bottom) / 2.0,
                        "size": gap_size,
                        "index": i - 1
                    })

            # Bearish FVG: High of bar_next is strictly lower than Low of bar_prev
            elif bar_next['high'] < bar_prev['low'] and bar_curr['close'] < bar_curr['open']:
                gap_top = bar_prev['low']
                gap_bottom = bar_next['high']
                gap_size = gap_top - gap_bottom

                is_mitigated = False
                for k in range(i + 1, n):
                    if df.iloc[k]['high'] >= gap_top:
                        is_mitigated = True
                        break

                if not is_mitigated:
                    fvgs.append({
                        "type": "BEARISH_FVG",
                        "top": gap_top,
                        "bottom": gap_bottom,
                        "mid": (gap_top + gap_bottom) / 2.0,
                        "size": gap_size,
                        "index": i - 1
                    })

        return fvgs

    @staticmethod
    def analyze_market_structure(df: pd.DataFrame) -> dict:
        """
        Analyzes market structure trend based on Swing Highs, Lows, and EMAs.
        """
        if len(df) < 20:
            return {"trend": "NEUTRAL", "last_swing_high": 0.0, "last_swing_low": 0.0}

        df_swing = IndicatorEngine.find_swing_points(df, window=2)
        swing_highs = df_swing[df_swing['swing_high']]['swing_high_price'].dropna().tolist()
        swing_lows = df_swing[df_swing['swing_low']]['swing_low_price'].dropna().tolist()

        current_close = df.iloc[-1]['close']
        ema50 = IndicatorEngine.calculate_ema(df['close'], 50).iloc[-1] if len(df) >= 50 else current_close
        ema200 = IndicatorEngine.calculate_ema(df['close'], 200).iloc[-1] if len(df) >= 200 else ema50

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_sh, prev_sh = swing_highs[-1], swing_highs[-2]
            last_sl, prev_sl = swing_lows[-1], swing_lows[-2]

            if last_sh > prev_sh and last_sl > prev_sl:
                trend = "BULLISH"
            elif last_sh < prev_sh and last_sl < prev_sl:
                trend = "BEARISH"
            else:
                trend = "BULLISH" if current_close > ema50 else "BEARISH"
        else:
            trend = "BULLISH" if current_close > ema50 else "BEARISH"

        return {
            "trend": trend,
            "last_swing_high": swing_highs[-1] if swing_highs else 0.0,
            "last_swing_low": swing_lows[-1] if swing_lows else 0.0,
            "ema50": ema50,
            "ema200": ema200,
            "current_above_ema50": current_close > ema50,
            "current_above_ema200": current_close > ema200
        }
