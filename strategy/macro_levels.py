# ==========================================================
# Macro Historical Key Levels Engine (D1, W1, MN1)
# ==========================================================
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger("MacroLevels")

class MacroLevelsEngine:

    def __init__(self, tolerance_pips: float = 25.0):
        self.tolerance_pips = tolerance_pips
        self.levels = {
            "pdh": 0.0, "pdl": 0.0, "pdc": 0.0,
            "pwh": 0.0, "pwl": 0.0,
            "pmh": 0.0, "pml": 0.0,
            "major_support": [],
            "major_resistance": []
        }

    def update_from_candles(self, df_daily: pd.DataFrame, df_h4: pd.DataFrame = None):
        """
        Extracts Monthly, Weekly, Daily, and major 30-90 day S/R clusters from historical data.
        """
        if df_daily is None or len(df_daily) < 5:
            return

        # 1. Previous Day High / Low / Close
        if len(df_daily) >= 2:
            prev_day = df_daily.iloc[-2]
            self.levels["pdh"] = float(prev_day["high"])
            self.levels["pdl"] = float(prev_day["low"])
            self.levels["pdc"] = float(prev_day["close"])

        # 2. Previous Week High / Low (approx last 5 daily bars)
        if len(df_daily) >= 10:
            last_week_bars = df_daily.iloc[-10:-5]
            self.levels["pwh"] = float(last_week_bars["high"].max())
            self.levels["pwl"] = float(last_week_bars["low"].min())

        # 3. Previous Month High / Low (approx last 22 daily bars)
        if len(df_daily) >= 44:
            last_month_bars = df_daily.iloc[-44:-22]
            self.levels["pmh"] = float(last_month_bars["high"].max())
            self.levels["pml"] = float(last_month_bars["low"].min())
        elif len(df_daily) >= 25:
            last_month_bars = df_daily.iloc[-25:-5]
            self.levels["pmh"] = float(last_month_bars["high"].max())
            self.levels["pml"] = float(last_month_bars["low"].min())

        # 4. Major Institutional Support & Resistance Clusters (Past 30-90 bars)
        highs = df_daily["high"].values
        lows = df_daily["low"].values
        
        # Identify pivot bounce zones
        res_candidates = []
        sup_candidates = []
        for i in range(2, len(df_daily) - 2):
            # Swing High pivot
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                res_candidates.append(highs[i])
            # Swing Low pivot
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                sup_candidates.append(lows[i])

        self.levels["major_resistance"] = sorted(res_candidates)[-5:] if res_candidates else []
        self.levels["major_support"] = sorted(sup_candidates)[:5] if sup_candidates else []

    def check_macro_confluence(self, current_price: float, pip_size: float = 0.10) -> dict:
        """
        Checks if current price is tapping or reacting at a Major Historical Macro Level.
        Returns:
            is_at_key_level (bool)
            zone_type ("SUPPORT" | "RESISTANCE" | "NEUTRAL")
            level_name (str)
            level_price (float)
            distance_pips (float)
            score_bonus (int): Confluence bonus points (1 to 3)
        """
        tolerance_usd = self.tolerance_pips * pip_size
        best_match = {
            "is_at_key_level": False,
            "zone_type": "NEUTRAL",
            "level_name": "None",
            "level_price": 0.0,
            "distance_pips": 999.0,
            "score_bonus": 0,
            "description": "Mid-range / No major macro level nearby"
        }

        checks = []

        # Check Monthly
        if self.levels["pmh"] > 0:
            checks.append(("Previous Monthly High (PMH)", self.levels["pmh"], "RESISTANCE", 3))
        if self.levels["pml"] > 0:
            checks.append(("Previous Monthly Low (PML)", self.levels["pml"], "SUPPORT", 3))

        # Check Weekly
        if self.levels["pwh"] > 0:
            checks.append(("Previous Weekly High (PWH)", self.levels["pwh"], "RESISTANCE", 2))
        if self.levels["pwl"] > 0:
            checks.append(("Previous Weekly Low (PWL)", self.levels["pwl"], "SUPPORT", 2))

        # Check Daily
        if self.levels["pdh"] > 0:
            checks.append(("Previous Daily High (PDH)", self.levels["pdh"], "RESISTANCE", 2))
        if self.levels["pdl"] > 0:
            checks.append(("Previous Daily Low (PDL)", self.levels["pdl"], "SUPPORT", 2))

        # Check Major Historical S/R
        for r_lvl in self.levels["major_resistance"]:
            checks.append(("Major 30-90D Resistance", r_lvl, "RESISTANCE", 2))
        for s_lvl in self.levels["major_support"]:
            checks.append(("Major 30-90D Support", s_lvl, "SUPPORT", 2))

        min_dist = float("inf")

        for name, lvl_price, z_type, bonus in checks:
            dist_usd = abs(current_price - lvl_price)
            dist_pips = round(dist_usd / pip_size, 1)

            if dist_usd <= tolerance_usd and dist_pips < min_dist:
                min_dist = dist_pips
                best_match = {
                    "is_at_key_level": True,
                    "zone_type": z_type,
                    "level_name": name,
                    "level_price": round(lvl_price, 2),
                    "distance_pips": dist_pips,
                    "score_bonus": bonus,
                    "description": f"🎯 At {name} (${lvl_price:.2f}) [±{dist_pips} pips]"
                }

        return best_match
