# ==========================================================
# Technical Indicators & Candlestick Pattern Engine
# ==========================================================
import numpy as np
import pandas as pd

class IndicatorEngine:

    @staticmethod
    def calculate_ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average"""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range"""
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        
        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def find_swing_points(df: pd.DataFrame, window: int = 2) -> pd.DataFrame:
        """
        Finds Swing Highs and Swing Lows (Fractal pivots).
        """
        df = df.copy()
        df['swing_high'] = False
        df['swing_low'] = False
        df['swing_high_price'] = np.nan
        df['swing_low_price'] = np.nan

        highs = df['high'].values
        lows = df['low'].values
        n = len(df)

        for i in range(window, n - window):
            if all(highs[i] >= highs[i - k] for k in range(1, window + 1)) and \
               all(highs[i] > highs[i + k] for k in range(1, window + 1)):
                df.iat[i, df.columns.get_loc('swing_high')] = True
                df.iat[i, df.columns.get_loc('swing_high_price')] = highs[i]

            if all(lows[i] <= lows[i - k] for k in range(1, window + 1)) and \
               all(lows[i] < lows[i + k] for k in range(1, window + 1)):
                df.iat[i, df.columns.get_loc('swing_low')] = True
                df.iat[i, df.columns.get_loc('swing_low_price')] = lows[i]

        return df

    @staticmethod
    def analyze_candlestick(open_p: float, high_p: float, low_p: float, close_p: float) -> dict:
        """
        Analyzes a single candlestick structure.
        """
        candle_range = high_p - low_p
        if candle_range <= 0.0001:
            return {
                "type": "DOJI",
                "body_pct": 0.0,
                "upper_wick_pct": 0.0,
                "lower_wick_pct": 0.0,
                "is_bullish": False,
                "is_bearish": False,
                "is_pinbar_bull": False,
                "is_pinbar_bear": False,
                "is_displacement": False
            }

        body = abs(close_p - open_p)
        body_pct = (body / candle_range) * 100.0
        is_bullish = close_p > open_p
        is_bearish = close_p < open_p

        if is_bullish:
            upper_wick = high_p - close_p
            lower_wick = open_p - low_p
        else:
            upper_wick = high_p - open_p
            lower_wick = close_p - low_p

        upper_wick_pct = (upper_wick / candle_range) * 100.0
        lower_wick_pct = (lower_wick / candle_range) * 100.0

        # Bullish Pin Bar (Hammer): Long lower wick (>= 50%), small upper wick (<= 25%), small body
        is_pinbar_bull = lower_wick_pct >= 50.0 and upper_wick_pct <= 25.0 and body_pct <= 38.0

        # Bearish Pin Bar (Shooting Star): Long upper wick (>= 50%), small lower wick (<= 25%), small body
        is_pinbar_bear = upper_wick_pct >= 50.0 and lower_wick_pct <= 25.0 and body_pct <= 38.0

        # Institutional Displacement (Expansion candle with minimal wicks)
        is_displacement = body_pct >= 65.0

        return {
            "candle_range": candle_range,
            "body": body,
            "body_pct": round(body_pct, 1),
            "upper_wick_pct": round(upper_wick_pct, 1),
            "lower_wick_pct": round(lower_wick_pct, 1),
            "is_bullish": is_bullish,
            "is_bearish": is_bearish,
            "is_pinbar_bull": is_pinbar_bull,
            "is_pinbar_bear": is_pinbar_bear,
            "is_displacement": is_displacement
        }

    @staticmethod
    def check_engulfing(prev_candle: dict, curr_candle: dict, 
                        prev_open: float, prev_close: float, 
                        curr_open: float, curr_close: float) -> str:
        if not prev_candle['is_bullish'] and curr_candle['is_bullish']:
            if curr_close > prev_open and curr_open <= prev_close:
                return "BULLISH_ENGULFING"

        if prev_candle['is_bullish'] and not curr_candle['is_bullish']:
            if curr_close < prev_open and curr_open >= prev_close:
                return "BEARISH_ENGULFING"

        return "NONE"
