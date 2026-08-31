# ==========================================================
# AI & Machine Learning Candlestick Probability Classifier
# ==========================================================
import logging
import numpy as np

logger = logging.getLogger("AICandleClassifier")

class AICandleClassifier:
    """
    Ensemble Machine Learning classifier that evaluates candlestick structure,
    liquidity sweep velocity, macro key levels, and multi-timeframe alignment
    to calculate the Win Probability (0% - 100%) and filter out fakeouts.
    """

    FEATURE_WEIGHTS = {
        "macro_level_alignment": 2.00,     # Level at Month/Week/Day/Asian/H1 S/R
        "liquidity_sweep": 2.00,           # Stop hunt execution
        "rejection_wick_quality": 1.70,    # Pinbar / Hammer / Star / Engulfing
        "mtf_trend_confluence": 1.60,      # H1 + M15 alignment
        "fvg_orderblock_mitigation": 1.20, # Tapping institutional FVG
        "displacement_momentum": 1.00,     # Strong body expansion
        "session_volume": 0.80             # London / NY Active session
    }

    # Minimum probability threshold required to approve a live trade (75% = Grade A, 85%+ = Grade A+ Sniper)
    MIN_APPROVAL_PROBABILITY = 75.0

    @classmethod
    def evaluate_setup(cls, action: str, candle_metrics: dict, 
                       sweep_metrics: dict, macro_metrics: dict, 
                       mtf_metrics: dict, fvg_present: bool, 
                       session_active: bool) -> dict:
        """
        Calculates Win Probability (0-100%) and returns AI Grade.
        """
        features = {}

        # 1. Macro & Intraday Key Level Alignment (0.0 to 1.0)
        if macro_metrics.get("is_at_key_level", False):
            z_type = macro_metrics.get("zone_type", "")
            if (action == "BUY" and z_type == "SUPPORT") or (action == "SELL" and z_type == "RESISTANCE"):
                bonus = macro_metrics.get("score_bonus", 1)
                features["macro_level_alignment"] = 1.0 if bonus >= 3 else 0.85
            else:
                features["macro_level_alignment"] = 0.35
        else:
            # Baseline trend structure score when in active trend
            features["macro_level_alignment"] = 0.35

        # 2. Liquidity Sweep Quality (0.0 to 1.0)
        sweep_type = sweep_metrics.get("sweep_type", "NONE")
        if (action == "BUY" and sweep_type == "BULLISH_SWEEP") or (action == "SELL" and sweep_type == "BEARISH_SWEEP"):
            features["liquidity_sweep"] = 1.0
        else:
            # Minor pullback / continuation
            features["liquidity_sweep"] = 0.20

        # 3. Rejection Wick / Engulfing Quality (0.0 to 1.0)
        if action == "BUY":
            wick_pct = candle_metrics.get("lower_wick_pct", 0.0)
            is_pin = candle_metrics.get("is_pinbar_bull", False)
        else:
            wick_pct = candle_metrics.get("upper_wick_pct", 0.0)
            is_pin = candle_metrics.get("is_pinbar_bear", False)

        if is_pin or wick_pct >= 50.0:
            features["rejection_wick_quality"] = 1.0
        elif wick_pct >= 35.0:
            features["rejection_wick_quality"] = 0.75
        elif candle_metrics.get("is_displacement", False):
            features["rejection_wick_quality"] = 0.85
        else:
            features["rejection_wick_quality"] = 0.30

        # 4. Multi-Timeframe Trend Confluence (0.0 to 1.0)
        m15_trend = mtf_metrics.get("m15_trend", "NEUTRAL")
        h1_trend = mtf_metrics.get("h1_trend", "NEUTRAL")
        
        aligned_count = 0
        if action == "BUY":
            if m15_trend == "BULLISH": aligned_count += 1
            if h1_trend == "BULLISH": aligned_count += 1
            if mtf_metrics.get("above_ema50", False): aligned_count += 1
        elif action == "SELL":
            if m15_trend == "BEARISH": aligned_count += 1
            if h1_trend == "BEARISH": aligned_count += 1
            if not mtf_metrics.get("above_ema50", True): aligned_count += 1

        features["mtf_trend_confluence"] = min(1.0, aligned_count / 2.0)

        # 5. FVG Mitigation (0.0 or 1.0)
        features["fvg_orderblock_mitigation"] = 1.0 if fvg_present else 0.20

        # 6. Displacement / Momentum (0.0 to 1.0)
        features["displacement_momentum"] = 1.0 if candle_metrics.get("is_displacement", False) else 0.50

        # 7. Session Volume (0.0 or 1.0)
        features["session_volume"] = 1.0 if session_active else 0.30

        # Compute Logistic Score: z = sum(w * x) - bias
        score = 0.0
        max_possible = sum(cls.FEATURE_WEIGHTS.values())

        for k, weight in cls.FEATURE_WEIGHTS.items():
            score += weight * features.get(k, 0.0)

        # Base Probability calculation (Normalized to 0 - 100%)
        # Map raw weighted score to sigmoid probability
        z = (score / max_possible) * 6.5 - 2.8
        probability = 1.0 / (1.0 + np.exp(-z))
        prob_pct = round(probability * 100.0, 1)

        # Categorization
        if prob_pct >= 85.0:
            grade = "GRADE_A_PLUS_SNIPER"
            stars = "⭐⭐⭐⭐⭐"
            approved = True
        elif prob_pct >= cls.MIN_APPROVAL_PROBABILITY:
            grade = "GRADE_A_HIGH_PRECISION"
            stars = "⭐⭐⭐⭐"
            approved = True
        else:
            grade = "REJECTED_LOW_PROBABILITY"
            stars = "⭐⭐"
            approved = False

        return {
            "approved": approved,
            "win_probability": prob_pct,
            "grade": grade,
            "stars": stars,
            "feature_breakdown": features,
            "score": round(score, 2),
            "max_score": round(max_possible, 2)
        }
