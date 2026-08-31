# ==========================================================
# Enhanced Macro & Intraday Key Levels Engine
# ==========================================================
import logging
import pandas as pd
import numpy as np
from strategy.indicators import IndicatorEngine

logger = logging.getLogger("MacroLevelsEngine")

class MacroLevelsEngine:
    """
    Computes both Historical Macro Levels (Monthly, Weekly, Daily) 
    AND Intraday Structural Levels (H1/H4 Swings, Asian Range High/Low).
    """

    def __init__(self, tolerance_pips: float = 25.0):
        self.tolerance_pips = tolerance_pips
        self.levels = {
            "pdh": 0.0, "pdl": 0.0, "pdc": 0.0,
            "pwh": 0.0, "pwl": 0.0,
            "pmh": 0.0, "pml": 0.0,
            "asian_high": 0.0, "asian_low": 0.0,
            "h1_highs": [], "h1_lows": [],
            "major_support": [],
            "major_resistance": []
        }

    def update_from_candles(self, candles_d1: pd.DataFrame, candles_h1: pd.DataFrame = None, candles_m5: pd.DataFrame = None):
        """Updates both Macro D1 levels and Intraday H1/Asian levels."""
        if candles_d1 is not None and len(candles_d1) >= 5:
            self._compute_d1_levels(candles_d1)
        
        if candles_h1 is not None and len(candles_h1) >= 20:
            self._compute_h1_levels(candles_h1)

        if candles_m5 is not None and len(candles_m5) >= 40:
            self._compute_asian_range(candles_m5)

    def _compute_d1_levels(self, df_d1: pd.DataFrame):
        try:
            prev_day = df_d1.iloc[-2]
            self.levels["pdh"] = float(prev_day["high"])
            self.levels["pdl"] = float(prev_day["low"])
            self.levels["pdc"] = float(prev_day["close"])

            # Weekly levels (last 5 completed D1 bars)
            if len(df_d1) >= 7:
                last_5_days = df_d1.iloc[-7:-2]
                self.levels["pwh"] = float(last_5_days["high"].max())
                self.levels["pwl"] = float(last_5_days["low"].min())

            # Monthly levels (last 22 completed D1 bars)
            if len(df_d1) >= 25:
                last_month_days = df_d1.iloc[-25:-2]
                self.levels["pmh"] = float(last_month_days["high"].max())
                self.levels["pml"] = float(last_month_days["low"].min())

            # S/R clusters from 60 days
            swings = IndicatorEngine.find_swing_points(df_d1, window=3)
            highs = swings[swings["swing_high"]]["swing_high_price"].dropna().tolist()
            lows = swings[swings["swing_low"]]["swing_low_price"].dropna().tolist()
            self.levels["major_resistance"] = sorted(highs)[-5:] if highs else []
            self.levels["major_support"] = sorted(lows)[:5] if lows else []
        except Exception as e:
            logger.warning(f"Error computing D1 macro levels: {e}")

    def _compute_h1_levels(self, df_h1: pd.DataFrame):
        try:
            swings = IndicatorEngine.find_swing_points(df_h1, window=2)
            highs = swings[swings["swing_high"]]["swing_high_price"].dropna().tolist()
            lows = swings[swings["swing_low"]]["swing_low_price"].dropna().tolist()
            self.levels["h1_highs"] = highs[-5:] if highs else []
            self.levels["h1_lows"] = lows[-5:] if lows else []
        except Exception as e:
            logger.warning(f"Error computing H1 levels: {e}")

    def _compute_asian_range(self, df_m5: pd.DataFrame):
        try:
            # Asian Session: 06:00 - 13:00 BKK
            today_bars = []
            for t, row in df_m5.iterrows():
                hour = t.hour if hasattr(t, "hour") else 0
                if 6 <= hour < 13:
                    today_bars.append(row)
            if today_bars:
                asian_df = pd.DataFrame(today_bars)
                self.levels["asian_high"] = float(asian_df["high"].max())
                self.levels["asian_low"] = float(asian_df["low"].min())
        except Exception as e:
            logger.warning(f"Error computing Asian range: {e}")

    def check_macro_confluence(self, current_price: float, pip_size: float = 0.10) -> dict:
        """
        Evaluates proximity to any Macro or Intraday S/R level within tolerance.
        """
        tol = self.tolerance_pips * pip_size
        matches = []

        # 1. Macro Daily / Weekly / Monthly
        checks = [
            ("Previous Day High (PDH)", self.levels.get("pdh", 0.0), "RESISTANCE", 3),
            ("Previous Day Low (PDL)", self.levels.get("pdl", 0.0), "SUPPORT", 3),
            ("Previous Week High (PWH)", self.levels.get("pwh", 0.0), "RESISTANCE", 4),
            ("Previous Week Low (PWL)", self.levels.get("pwl", 0.0), "SUPPORT", 4),
            ("Previous Month High (PMH)", self.levels.get("pmh", 0.0), "RESISTANCE", 5),
            ("Previous Month Low (PML)", self.levels.get("pml", 0.0), "SUPPORT", 5),
            ("Asian Session High", self.levels.get("asian_high", 0.0), "RESISTANCE", 3),
            ("Asian Session Low", self.levels.get("asian_low", 0.0), "SUPPORT", 3),
        ]

        for name, price_lvl, zone_type, weight in checks:
            if price_lvl > 0:
                dist = abs(current_price - price_lvl)
                dist_pips = dist / pip_size
                if dist_pips <= self.tolerance_pips:
                    matches.append({
                        "name": name,
                        "level": price_lvl,
                        "zone_type": zone_type,
                        "distance_pips": round(dist_pips, 1),
                        "weight": weight
                    })

        # 2. H1 Intraday Swings
        for h_lvl in self.levels.get("h1_highs", []):
            dist_pips = abs(current_price - h_lvl) / pip_size
            if dist_pips <= self.tolerance_pips:
                matches.append({
                    "name": "H1 Swing Resistance",
                    "level": h_lvl,
                    "zone_type": "RESISTANCE",
                    "distance_pips": round(dist_pips, 1),
                    "weight": 2
                })

        for l_lvl in self.levels.get("h1_lows", []):
            dist_pips = abs(current_price - l_lvl) / pip_size
            if dist_pips <= self.tolerance_pips:
                matches.append({
                    "name": "H1 Swing Support",
                    "level": l_lvl,
                    "zone_type": "SUPPORT",
                    "distance_pips": round(dist_pips, 1),
                    "weight": 2
                })

        if matches:
            matches.sort(key=lambda x: (x["distance_pips"], -x["weight"]))
            best = matches[0]
            return {
                "is_at_key_level": True,
                "description": f"🎯 At {best['name']} (${best['level']:.2f}, {best['distance_pips']} pips away)",
                "nearest_level": best['level'],
                "zone_type": best['zone_type'],
                "score_bonus": best['weight']
            }

        return {
            "is_at_key_level": False,
            "description": "Mid-range / No major level nearby",
            "nearest_level": 0.0,
            "zone_type": "NONE",
            "score_bonus": 0
        }
