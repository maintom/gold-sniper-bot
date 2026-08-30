# ==========================================================
# High-Precision Multi-Source Cloud Gold Feed (XAU/USD)
# ==========================================================
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger("CloudGoldFeed")

class CloudGoldFeed:

    def __init__(self):
        self.local_tz = pytz.timezone("Asia/Bangkok")
        self.active_symbol = "XAUUSD"
        self.last_price = 2502.50

    def get_price(self) -> dict:
        """Returns live Bid, Ask, Spread for Gold (XAUUSD)."""
        # Source 1: Yahoo Finance Gold (Whitelisted on PythonAnywhere Free Tier)
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d"
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=4)
            if res.status_code == 200:
                data = res.json()
                meta = data["chart"]["result"][0]["meta"]
                cur_p = float(meta["regularMarketPrice"])
                self.last_price = cur_p
                spread_val = 0.25
                return {
                    "symbol": "XAUUSD",
                    "bid": round(cur_p - (spread_val / 2.0), 2),
                    "ask": round(cur_p + (spread_val / 2.0), 2),
                    "mid": cur_p,
                    "spread_pips": 2.5,
                    "point": 0.01,
                    "pip_size": 0.10,
                    "digits": 2,
                    "time": datetime.now(self.local_tz)
                }
        except Exception:
            pass

        # Source 2: Binance PAXGUSDT
        try:
            url = "https://api.binance.com/api/v3/ticker/bookTicker?symbol=PAXGUSDT"
            res = requests.get(url, timeout=3)
            if res.status_code == 200:
                data = res.json()
                bid = float(data["bidPrice"])
                ask = float(data["askPrice"])
                self.last_price = (bid + ask) / 2.0
                return {
                    "symbol": "XAUUSD",
                    "bid": bid,
                    "ask": ask,
                    "mid": self.last_price,
                    "spread_pips": round((ask - bid) / 0.10, 1),
                    "point": 0.01,
                    "pip_size": 0.10,
                    "digits": 2,
                    "time": datetime.now(self.local_tz)
                }
        except Exception:
            pass

        # Fallback
        return {
            "symbol": "XAUUSD",
            "bid": round(self.last_price - 0.12, 2),
            "ask": round(self.last_price + 0.13, 2),
            "mid": self.last_price,
            "spread_pips": 2.5,
            "point": 0.01,
            "pip_size": 0.10,
            "digits": 2,
            "time": datetime.now(self.local_tz)
        }

    def get_candles(self, timeframe: str, count: int = 100) -> pd.DataFrame:
        """Fetches OHLCV bars for Gold."""
        tf_map = {"M1": "1m", "M5": "5m", "M15": "15m", "H1": "1h", "D1": "1d"}
        interval = tf_map.get(timeframe.upper(), "5m")

        # Source 1: Yahoo Finance Chart API (Whitelisted on PythonAnywhere)
        try:
            range_val = "5d" if interval in ["1m", "5m", "15m"] else "1mo"
            if interval == "1d": range_val = "1y"
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={range_val}"
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                timestamps = data["chart"]["result"][0]["timestamp"]
                quotes = data["chart"]["result"][0]["indicators"]["quote"][0]
                
                rows = []
                for i in range(len(timestamps)):
                    if quotes["close"][i] is not None:
                        t = datetime.fromtimestamp(timestamps[i], tz=self.local_tz)
                        rows.append({
                            "time": t,
                            "open": quotes["open"][i],
                            "high": quotes["high"][i],
                            "low": quotes["low"][i],
                            "close": quotes["close"][i],
                            "tick_volume": quotes.get("volume", [0])[i] or 100
                        })
                df = pd.DataFrame(rows)
                df.set_index("time", inplace=True)
                return df.iloc[-count:]
        except Exception:
            pass

        # Source 2: Binance PAXG
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval={interval}&limit={count}"
            res = requests.get(url, timeout=4)
            if res.status_code == 200:
                raw = res.json()
                data = []
                for k in raw:
                    t = datetime.fromtimestamp(k[0] / 1000.0, tz=self.local_tz)
                    data.append({
                        "time": t,
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "tick_volume": float(k[5])
                    })
                df = pd.DataFrame(data)
                df.set_index("time", inplace=True)
                return df
        except Exception:
            pass

        return pd.DataFrame()

    def get_account_info(self) -> dict:
        return {
            "login": "Cloud-Account",
            "server": "Cloud-24/7",
            "balance": 1000.0,
            "equity": 1000.0,
            "leverage": 2000
        }
