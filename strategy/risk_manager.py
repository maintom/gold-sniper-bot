# ==========================================================
# Institutional Dynamic ATR Risk & Money Management Engine
# ==========================================================
import logging

logger = logging.getLogger("RiskManager")

class RiskManager:
    """
    Computes exact institutional position sizing and Dynamic ATR-based Stop Loss
    to adapt to real-time market volatility across all account sizes ($50 to $100,000+).
    """

    def __init__(self, config: dict):
        self.config = config.get("money_management", config.get("risk", {}))
        self.risk_pct = self.config.get("risk_per_trade_percent", 1.0)
        self.min_rr = 1.5
        self.target_rr = 2.5
        self.max_sl_pips = self.config.get("max_sl_pips", 45.0)
        self.min_sl_pips = self.config.get("min_sl_pips", 20.0)
        self.sl_buffer_pips = self.config.get("sl_buffer_pips", 3.0)

    def calculate_lot(self, account_balance: float, sl_distance_pips: float, trade_mode: str = "QUICK_SCALP") -> float:
        """
        Smooth Money Management Lot Sizing for real accounts ($50 - $10,000+):
        - Micro Account ($50 - $150): 0.01 Lot (Max safety)
        - Small Account ($150 - $500): 0.02 Lot
        - Medium Account ($500 - $1,500): 0.03 - 0.04 Lot
        - Large Account ($1,500+): Strict 1% risk sizing
        """
        if account_balance < 150.0:
            return 0.01
        elif account_balance < 500.0:
            return 0.02 if trade_mode == "QUICK_SCALP" else 0.01
        elif account_balance < 1500.0:
            return 0.03 if trade_mode == "QUICK_SCALP" else 0.02

        # 1% Dynamic Risk Sizing for larger accounts
        risk_usd = account_balance * (self.risk_pct / 100.0)
        pip_val_1lot = 10.0
        calculated_lot = risk_usd / (sl_distance_pips * pip_val_1lot) if sl_distance_pips > 0 else 0.02
        
        max_allowed_lot = max(0.01, round(account_balance / 25000.0, 2))
        base_lot = max(0.01, min(max_allowed_lot, round(calculated_lot, 2)))

        if trade_mode == "TREND_RUNNER":
            return max(0.01, round(base_lot * 0.5, 2))
        return base_lot

    def calculate_trade_levels(self, action: str, entry_price: float, 
                               structural_sl_price: float, pip_size: float, 
                               account_balance: float = 1000.0,
                               atr_value: float = 2.0) -> dict:
        """
        Calculates Entry, Dynamic ATR SL, TP1, TP2, and Lot without altering entry precision.
        """
        atr_sl_pips = round((atr_value * 1.2) / pip_size, 1) if atr_value > 0 else 25.0
        buffer_usd = self.sl_buffer_pips * pip_size

        if action == "BUY":
            sl_price = round(structural_sl_price - buffer_usd, 2)
            sl_distance_pips = round((entry_price - sl_price) / pip_size, 1)

            if sl_distance_pips < self.min_sl_pips or sl_distance_pips < (atr_sl_pips * 0.8):
                sl_distance_pips = max(self.min_sl_pips, min(self.max_sl_pips, atr_sl_pips))
                sl_price = round(entry_price - (sl_distance_pips * pip_size), 2)
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

            if sl_distance_pips < self.min_sl_pips or sl_distance_pips < (atr_sl_pips * 0.8):
                sl_distance_pips = max(self.min_sl_pips, min(self.max_sl_pips, atr_sl_pips))
                sl_price = round(entry_price + (sl_distance_pips * pip_size), 2)
            elif sl_distance_pips > self.max_sl_pips:
                sl_price = round(entry_price - (self.max_sl_pips * pip_size), 2)
                sl_distance_pips = self.max_sl_pips

            risk_dist = sl_price - entry_price
            tp1_price = round(entry_price - (1.5 * risk_dist), 2)
            tp2_price = round(entry_price - (self.target_rr * risk_dist), 2)
            rr_ratio = round((entry_price - tp2_price) / risk_dist, 2)

        else:
            return {"is_valid": False, "reason": "Invalid action"}

        rec_lot = self.calculate_lot(account_balance, sl_distance_pips, "QUICK_SCALP")
        risk_usd = round(rec_lot * sl_distance_pips * 10.0, 2)

        return {
            "is_valid": True,
            "action": action,
            "entry": round(entry_price, 2),
            "sl": sl_price,
            "sl_pips": sl_distance_pips,
            "tp1": tp1_price,
            "tp2": tp2_price,
            "risk_reward": f"1:{rr_ratio}",
            "risk_usd": risk_usd,
            "recommended_lot": rec_lot
        }
