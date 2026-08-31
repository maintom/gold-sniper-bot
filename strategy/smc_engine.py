# ==========================================================
# Smart Money Concepts (SMC) & Institutional Displacement Engine
# ==========================================================
import numpy as np
import pandas as pd
from strategy.indicators import IndicatorEngine

class SMCEngine:

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculates Average True Range (ATR) on OHLCV DataFrame."""
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        
        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    @staticmethod
    def detect_displacement_and_volume(df: pd.DataFrame) -> dict:
        """
        Detects Institutional Displacement Candles confirmed with Volume Spikes:
        - Body Size >= 1.2x ATR
        - Tick Volume >= 1.2x 10-period Volume SMA
        - Leaves Fair Value Gap (FVG) with 50% Consequent Encroachment level
        """
        if len(df) < 20:
            return {"has_displacement": False, "type": "NONE", "fvg_50_level": 0.0, "atr": 2.0}

        atr_series = SMCEngine.calculate_atr(df, period=14)
        current_atr = atr_series.iloc[-2] if not pd.isna(atr_series.iloc[-2]) else 2.0
        
        # Volume Spike Check
        vol_col = 'tick_volume' if 'tick_volume' in df.columns else 'volume' if 'volume' in df.columns else None
        has_volume_surge = True
        if vol_col:
            vol_sma = df[vol_col].rolling(10).mean()
            recent_vol = df[vol_col].iloc[-2]
            avg_vol = vol_sma.iloc[-2] if not pd.isna(vol_sma.iloc[-2]) else recent_vol
            has_volume_surge = (recent_vol >= 1.15 * avg_vol) or (avg_vol == 0)

        # Recent closed candle
        curr_bar = df.iloc[-2]
        prev_bar = df.iloc[-3]
        two_bars_ago = df.iloc[-4] if len(df) >= 4 else prev_bar

        body_size = abs(curr_bar['close'] - curr_bar['open'])
        is_large_body = (body_size >= 1.2 * current_atr) or (body_size >= 2.0)

        # Bullish Displacement
        if curr_bar['close'] > curr_bar['open'] and is_large_body and has_volume_surge:
            # Bullish FVG between two_bars_ago high and curr_bar low
            fvg_bottom = two_bars_ago['high']
            fvg_top = curr_bar['low']
            if fvg_top > fvg_bottom:
                fvg_50 = (fvg_top + fvg_bottom) / 2.0
                return {
                    "has_displacement": True,
                    "type": "BULLISH_DISPLACEMENT",
                    "fvg_top": fvg_top,
                    "fvg_bottom": fvg_bottom,
                    "fvg_50_level": fvg_50,
                    "atr": current_atr,
                    "displacement_low": curr_bar['low']
                }

        # Bearish Displacement
        if curr_bar['close'] < curr_bar['open'] and is_large_body and has_volume_surge:
            # Bearish FVG between curr_bar high and two_bars_ago low
            fvg_top = two_bars_ago['low']
            fvg_bottom = curr_bar['high']
            if fvg_top > fvg_bottom:
                fvg_50 = (fvg_top + fvg_bottom) / 2.0
                return {
                    "has_displacement": True,
                    "type": "BEARISH_DISPLACEMENT",
                    "fvg_top": fvg_top,
                    "fvg_bottom": fvg_bottom,
                    "fvg_50_level": fvg_50,
                    "atr": current_atr,
                    "displacement_high": curr_bar['high']
                }

        return {"has_displacement": False, "type": "NONE", "fvg_50_level": 0.0, "atr": current_atr}

    @staticmethod
    def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 25) -> dict:
        """
        Detects if the most recent closed candle executed a Liquidity Sweep (Stop Hunt).
        """
        if len(df) < lookback + 3:
            return {"sweep_type": "NONE", "sweep_level": 0.0, "rejection_wick": 0.0}

        df_swing = IndicatorEngine.find_swing_points(df, window=2)
        curr_bar = df.iloc[-2]
        c_open, c_high, c_low, c_close = curr_bar['open'], curr_bar['high'], curr_bar['low'], curr_bar['close']
        candle_range = c_high - c_low

        if candle_range <= 0.0001:
            return {"sweep_type": "NONE", "sweep_level": 0.0, "rejection_wick": 0.0}

        hist_df = df.iloc[-lookback-2:-2]
        hist_swing = df_swing.iloc[-lookback-2:-2]
        
        swing_highs = hist_swing[hist_swing['swing_high']]['swing_high_price'].dropna().tolist()
        swing_lows = hist_swing[hist_swing['swing_low']]['swing_low_price'].dropna().tolist()

        range_min_low = hist_df['low'].min()
        range_max_high = hist_df['high'].max()

        target_lows = list(set(swing_lows + [range_min_low]))
        target_highs = list(set(swing_highs + [range_max_high]))

        # Bullish Sweep
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

        # Bearish Sweep
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
        """Finds active unmitigated Fair Value Gaps (FVG) within the lookback window."""
        fvgs = []
        if len(df) < 5:
            return fvgs

        recent_df = df.iloc[-max_lookback-1:-1]
        for i in range(2, len(recent_df)):
            c1 = recent_df.iloc[i-2]
            c2 = recent_df.iloc[i-1]
            c3 = recent_df.iloc[i]

            # Bullish FVG
            if c3['low'] > c1['high'] and (c2['close'] > c2['open']):
                gap_size = c3['low'] - c1['high']
                if gap_size >= 0.30:
                    fvgs.append({
                        "type": "BULLISH_FVG",
                        "bottom": c1['high'],
                        "top": c3['low'],
                        "size": gap_size,
                        "mid": (c1['high'] + c3['low']) / 2.0,
                        "bar_idx": i
                    })

            # Bearish FVG
            elif c1['low'] > c3['high'] and (c2['close'] < c2['open']):
                gap_size = c1['low'] - c3['high']
                if gap_size >= 0.30:
                    fvgs.append({
                        "type": "BEARISH_FVG",
                        "bottom": c3['high'],
                        "top": c1['low'],
                        "size": gap_size,
                        "mid": (c3['high'] + c1['low']) / 2.0,
                        "bar_idx": i
                    })

        return fvgs

    @staticmethod
    def analyze_market_structure(df: pd.DataFrame) -> dict:
        """Determines market trend, BOS/CHoCH, and EMA alignment."""
        if len(df) < 25:
            return {"trend": "NEUTRAL", "current_above_ema50": False}

        df_emas = IndicatorEngine.calculate_ema(df, [20, 50])
        ema20 = df_emas['ema_20'].iloc[-2]
        ema50 = df_emas['ema_50'].iloc[-2]
        close_p = df['close'].iloc[-2]

        df_swings = IndicatorEngine.find_swing_points(df, window=2)
        recent_highs = df_swings[df_swings['swing_high']]['swing_high_price'].dropna().tail(3).tolist()
        recent_lows = df_swings[df_swings['swing_low']]['swing_low_price'].dropna().tail(3).tolist()

        is_higher_highs = len(recent_highs) >= 2 and recent_highs[-1] > recent_highs[-2]
        is_higher_lows = len(recent_lows) >= 2 and recent_lows[-1] > recent_lows[-2]
        is_lower_highs = len(recent_highs) >= 2 and recent_highs[-1] < recent_highs[-2]
        is_lower_lows = len(recent_lows) >= 2 and recent_lows[-1] < recent_lows[-2]

        if (ema20 > ema50 and close_p > ema50) or (is_higher_highs and is_higher_lows):
            trend = "BULLISH"
        elif (ema20 < ema50 and close_p < ema50) or (is_lower_highs and is_lower_lows):
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"

        return {
            "trend": trend,
            "ema20": ema20,
            "ema50": ema50,
            "current_above_ema50": bool(close_p > ema50)
        }
