# ==========================================================
# Risk Management & Precision Position Sizing for Gold
# ==========================================================
import logging

logger = logging.getLogger("RiskManager")

class RiskManager:

    def __init__(self, config: dict):
        self.config = config.get("risk", {})
        self.risk_pct = self.config.get("risk_per_trade_percent", 1.0)
        self.min_rr = self.config.get("min_risk_reward_ratio", 1.5)
        self.target_rr = self.config.get("target_risk_reward_ratio", 2.5)
        self.max_sl_pips = self.config.get("max_sl_pips", 45.0)
        self.min_sl_pips = self.config.get("min_sl_pips", 20.0)
        self.sl_buffer_pips = self.config.get("sl_buffer_pips", 3.5)

    def calculate_trade_levels(self, action: str, entry_price: float, 
                               structural_sl_price: float, pip_size: float, 
                               account_balance: float = 1000.0) -> dict:
        """
        Calculates Entry, Dynamic Institutional SL (min 20 pips), TP1, TP2, and Lot.
        """
        buffer_usd = self.sl_buffer_pips * pip_size

        if action == "BUY":
            # SL placed below structural support/wick minus buffer
            sl_price = round(structural_sl_price - buffer_usd, 2)
            sl_distance_pips = round((entry_price - sl_price) / pip_size, 1)

            # Check SL bounds (Ensure at least 20 pips breathing room)
            if sl_distance_pips < self.min_sl_pips:
                sl_price = round(entry_price - (self.min_sl_pips * pip_size), 2)
                sl_distance_pips = self.min_sl_pips
            elif sl_distance_pips > self.max_sl_pips:
                sl_price = round(entry_price - (self.max_sl_pips * pip_size), 2)
                sl_distance_pips = self.max_sl_pips

            risk_dist = entry_price - sl_price
            tp1_price = round(entry_price + (1.5 * risk_dist), 2)
            tp2_price = round(entry_price + (self.target_rr * risk_dist), 2)
            rr_ratio = round((tp2_price - entry_price) / risk_dist, 2)

        elif action == "SELL":
            # SL placed above structural resistance/wick plus buffer
            sl_price = round(structural_sl_price + buffer_usd, 2)
            sl_distance_pips = round((sl_price - entry_price) / pip_size, 1)

            # Check SL bounds (Ensure at least 20 pips breathing room)
            if sl_distance_pips < self.min_sl_pips:
                sl_price = round(entry_price + (self.min_sl_pips * pip_size), 2)
                sl_distance_pips = self.min_sl_pips
            elif sl_distance_pips > self.max_sl_pips:
                sl_price = round(entry_price + (self.max_sl_pips * pip_size), 2)
                sl_distance_pips = self.max_sl_pips

            risk_dist = sl_price - entry_price
            tp1_price = round(entry_price - (1.5 * risk_dist), 2)
            tp2_price = round(entry_price - (self.target_rr * risk_dist), 2)
            rr_ratio = round((entry_price - tp2_price) / risk_dist, 2)

        else:
            return {"is_valid": False, "reason": "Invalid action"}

        # Calculate exact lot size
        risk_usd = (account_balance * (self.risk_pct / 100.0))
        pip_val_1lot = 10.0
        calculated_lot = risk_usd / (sl_distance_pips * pip_val_1lot) if sl_distance_pips > 0 else 0.01
        recommended_lot = max(0.01, round(calculated_lot, 2))

        return {
            "is_valid": True,
            "action": action,
            "entry": round(entry_price, 2),
            "sl": sl_price,
            "sl_pips": sl_distance_pips,
            "tp1": tp1_price,
            "tp2": tp2_price,
            "risk_reward": f"1:{rr_ratio}",
            "risk_usd": round(risk_usd, 2),
            "recommended_lot": recommended_lot
        }
