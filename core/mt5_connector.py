# ==========================================================
# MetaTrader 5 (Exness) Connector & Data Provider
# ==========================================================
import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import pytz

logger = logging.getLogger("MT5Connector")

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

class MT5Connector:
    # Common Gold symbol names across Exness and various brokers
    GOLD_ALIASES = ["XAUUSD", "XAUUSDm", "XAUUSD_", "XAUUSDz", "XAUUSD.a", "GOLD", "GOLDm", "XAUUSDb"]

    def __init__(self, config: dict):
        self.config = config.get("mt5", {})
        self.requested_symbol = self.config.get("symbol", "").strip()
        self.path = self.config.get("path", "").strip()
        self.login = self.config.get("login", 0)
        self.password = self.config.get("password", "")
        self.server = self.config.get("server", "")
        self.timeout = self.config.get("timeout_ms", 60000)
        
        self.active_symbol = None
        self.symbol_info = None
        self.connected = False
        self.local_tz = pytz.timezone("Asia/Bangkok")

    def connect(self) -> bool:
        """Initialize connection to MT5 terminal."""
        init_params = {}
        if self.path:
            init_params["path"] = self.path
        if self.timeout:
            init_params["timeout"] = self.timeout
            
        if self.login and self.password and self.server:
            init_params["login"] = int(self.login)
            init_params["password"] = str(self.password)
            init_params["server"] = str(self.server)

        if not mt5.initialize(**init_params):
            logger.error(f"MT5 initialize failed. Error code: {mt5.last_error()}")
            self.connected = False
            return False

        self.connected = True
        logger.info("Successfully connected to MetaTrader 5 terminal.")

        # Resolve Gold Symbol
        if not self._resolve_symbol():
            logger.error("Could not resolve a valid Gold (XAUUSD) symbol in MT5.")
            return False

        account = mt5.account_info()
        if account is not None:
            logger.info(f"Account: #{account.login} ({account.server}) | Balance:  | Leverage: 1:{account.leverage}")

        return True

    def _resolve_symbol(self) -> bool:
        """Auto-detects and enables the correct Gold symbol in MarketWatch."""
        if self.requested_symbol:
            candidates = [self.requested_symbol]
        else:
            candidates = self.GOLD_ALIASES

        all_symbols = [s.name for s in mt5.symbols_get()] if mt5.symbols_get() else []

        for candidate in candidates:
            # Check exact or partial match
            match = None
            if candidate in all_symbols:
                match = candidate
            else:
                for s in all_symbols:
                    if candidate.upper() == s.upper():
                        match = s
                        break

            if match:
                # Ensure symbol is selected in Market Watch
                if not mt5.symbol_select(match, True):
                    logger.warning(f"Failed to select symbol {match} in Market Watch.")
                    continue
                
                info = mt5.symbol_info(match)
                if info is not None and info.visible:
                    self.active_symbol = match
                    self.symbol_info = info
                    logger.info(f"Active Gold Symbol resolved to: '{self.active_symbol}' (Digits: {info.digits}, Point: {info.point})")
                    return True

        logger.error(f"None of the candidate symbols {candidates} could be activated.")
        return False

    def get_price(self) -> dict:
        """Returns current real-time bid, ask, spread, and point size."""
        if not self.connected or not self.active_symbol:
            return None

        tick = mt5.symbol_info_tick(self.active_symbol)
        if tick is None:
            return None

        point = self.symbol_info.point if self.symbol_info else 0.01
        digits = self.symbol_info.digits if self.symbol_info else 2
        # In gold, 1 pip is typically 0.10 USD (or 10 points if 2 digits, 100 points if 3 digits)
        pip_size = point * 10 if digits == 2 else point * 100
        spread_pips = round((tick.ask - tick.bid) / pip_size, 2) if pip_size > 0 else 0.0

        return {
            "symbol": self.active_symbol,
            "bid": tick.bid,
            "ask": tick.ask,
            "mid": round((tick.bid + tick.ask) / 2.0, digits),
            "spread_points": round((tick.ask - tick.bid) / point, 1),
            "spread_pips": spread_pips,
            "point": point,
            "pip_size": pip_size,
            "digits": digits,
            "time": datetime.fromtimestamp(tick.time, tz=self.local_tz)
        }

    def get_candles(self, timeframe: str, count: int = 150) -> pd.DataFrame:
        """
        Fetches the latest OHLCV bars for the specified timeframe into a pandas DataFrame.
        """
        if not self.connected or not self.active_symbol:
            return pd.DataFrame()

        tf_const = TIMEFRAME_MAP.get(timeframe.upper())
        if tf_const is None:
            logger.error(f"Invalid timeframe: {timeframe}")
            return pd.DataFrame()

        rates = mt5.copy_rates_from_pos(self.active_symbol, tf_const, 0, count)
        if rates is None or len(rates) == 0:
            logger.warning(f"No rates returned for {self.active_symbol} on {timeframe}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert(self.local_tz)
        df.set_index("time", inplace=True)
        return df

    def get_account_info(self) -> dict:
        """Returns current account financial details."""
        if not self.connected:
            return {}

        acc = mt5.account_info()
        if acc is None:
            return {}

        term = mt5.terminal_info()
        trade_allowed = term.trade_allowed if term else True
        return {
            "login": acc.login,
            "server": acc.server,
            "currency": acc.currency,
            "balance": acc.balance,
            "equity": acc.equity,
            "margin": acc.margin,
            "free_margin": acc.margin_free,
            "margin_level": acc.margin_level,
            "leverage": acc.leverage,
            "profit": acc.profit,
            "terminal_trade_allowed": trade_allowed
        }

    def shutdown(self):
        """Cleanly closes MT5 connection."""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("MT5 connection closed.")
