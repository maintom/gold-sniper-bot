# ==========================================================
# Institutional Risk & Money Management Engine
# ==========================================================
import logging

logger = logging.getLogger("RiskManager")

class RiskManager:
    """
    Computes exact institutional position sizing, dynamic stop loss (25-45 pips),
    and target risk-to-reward ratios to protect capital and prevent drawdowns.
    """

    def __init__(self, config: dict):
        self.config = config.get("money_management", config.get("risk", {}))
        self.risk_pct = self.config.get("risk_per_trade_percent", 1.0)
        self.min_rr = 1.5
        self.target_rr = 2.5
        self.max_sl_pips = self.config.get("max_sl_pips", 45.0)
        self.min_sl_pips = self.config.get("min_sl_pips", 25.0)
        self.sl_buffer_pips = self.config.get("sl_buffer_pips", 3.5)

    def calculate_trade_levels(self, action: str, entry_price: float, 
                               structural_sl_price: float, pip_size: float, 
                               account_balance: float = 1000.0) -> dict:
        """
        Calculates Entry, Dynamic Institutional SL (25-45 pips), TP1, TP2, and Lot.
        """
        buffer_usd = self.sl_buffer_pips * pip_size

        if action == "BUY":
            sl_price = round(structural_sl_price - buffer_usd, 2)
            sl_distance_pips = round((entry_price - sl_price) / pip_size, 1)

            # Ensure SL breathing room: min 25 pips ($2.50) to prevent spread whipsaws
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
            sl_price = round(structural_sl_price + buffer_usd, 2)
            sl_distance_pips = round((sl_price - entry_price) / pip_size, 1)

            # Ensure SL breathing room: min 25 pips ($2.50) to prevent spread whipsaws
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

        # Strict Money Management Lot Size:
        # Standard Gold 1.0 Lot = $10 per pip ($1.00 move = $100)
        risk_usd = account_balance * (self.risk_pct / 100.0)
        pip_val_1lot = 10.0
        calculated_lot = risk_usd / (sl_distance_pips * pip_val_1lot) if sl_distance_pips > 0 else 0.01
        
        # Sane Lot Limits based on balance
        max_allowed_lot = max(0.01, round(account_balance / 25000.0, 2))  # e.g. Max 0.12 lot for $3000
        recommended_lot = max(0.01, min(max_allowed_lot, round(calculated_lot, 2)))

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
