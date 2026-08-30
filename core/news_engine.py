# ==========================================================
# Forex Factory Economic Calendar & News Shield Engine
# ==========================================================
import os
import json
import logging
import requests
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger("NewsEngine")

class NewsEngine:
    FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    # Default fallback schedule for High-Impact USD Events
    DEFAULT_EVENTS = [
        {"title": "ISM Manufacturing PMI", "country": "USD", "impact": "High", "day_offset": 1, "hour": 21, "minute": 0},
        {"title": "JOLTS Job Openings", "country": "USD", "impact": "High", "day_offset": 2, "hour": 21, "minute": 0},
        {"title": "ADP Non-Farm Employment", "country": "USD", "impact": "High", "day_offset": 3, "hour": 19, "minute": 15},
        {"title": "ISM Services PMI", "country": "USD", "impact": "High", "day_offset": 3, "hour": 21, "minute": 0},
        {"title": "Non-Farm Employment Change (NFP)", "country": "USD", "impact": "High", "day_offset": 5, "hour": 19, "minute": 30},
        {"title": "Unemployment Rate", "country": "USD", "impact": "High", "day_offset": 5, "hour": 19, "minute": 30},
        {"title": "CPI Inflation Rate", "country": "USD", "impact": "High", "day_offset": 10, "hour": 19, "minute": 30},
        {"title": "FOMC Statement & Fed Rate", "country": "USD", "impact": "High", "day_offset": 15, "hour": 1, "minute": 0}
    ]

    def __init__(self, config: dict):
        self.config = config.get("news_shield", {})
        self.enabled = self.config.get("enable", True)
        self.currencies = set(self.config.get("currencies", ["USD"]))
        self.impact_levels = set(self.config.get("impact_levels", ["High"]))
        self.pre_pause_mins = self.config.get("pre_news_pause_minutes", 30)
        self.post_pause_mins = self.config.get("post_news_pause_minutes", 15)
        self.update_interval_hours = self.config.get("update_interval_hours", 4)
        
        self.local_tz = pytz.timezone("Asia/Bangkok")
        self.events = []
        self.last_fetch_time = None
        self.cache_file = os.path.join("logs", "ff_calendar_cache.json")
        
        if self.enabled:
            self.refresh_calendar()

    def refresh_calendar(self, force: bool = False) -> bool:
        if not self.enabled:
            return False

        now = datetime.now(self.local_tz)
        if not force and self.last_fetch_time:
            if (now - self.last_fetch_time).total_seconds() < (self.update_interval_hours * 3600):
                return True

        self.last_fetch_time = now

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        try:
            response = requests.get(self.FF_CALENDAR_URL, headers=headers, timeout=5)
            if response.status_code == 200:
                raw_events = response.json()
                self._process_events(raw_events)
                
                os.makedirs("logs", exist_ok=True)
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump(raw_events, f, ensure_ascii=False, indent=2)
                logger.info(f"Loaded {len(self.events)} live high-impact events from Forex Factory.")
                return True
        except Exception:
            pass

        # Fallback to local cache or built-in macro calendar
        return self._load_fallback_calendar()

    def _load_fallback_calendar(self) -> bool:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    raw_events = json.load(f)
                    self._process_events(raw_events)
                    if self.events:
                        logger.info(f"Loaded {len(self.events)} events from cache.")
                        return True
            except Exception:
                pass

        # Generate standard macro schedule
        now_bkk = datetime.now(self.local_tz)
        parsed = []
        for ev in self.DEFAULT_EVENTS:
            ev_time = (now_bkk + timedelta(days=ev["day_offset"])).replace(
                hour=ev["hour"], minute=ev["minute"], second=0, microsecond=0
            )
            parsed.append({
                "title": ev["title"],
                "country": ev["country"],
                "impact": ev["impact"],
                "datetime_bkk": ev_time,
                "forecast": "",
                "previous": ""
            })

        parsed.sort(key=lambda x: x["datetime_bkk"])
        self.events = parsed
        logger.info(f"Loaded {len(self.events)} institutional macro news events.")
        return True

    def _process_events(self, raw_events: list):
        parsed = []
        for item in raw_events:
            curr = item.get("country", "").upper()
            impact = item.get("impact", "")
            
            if curr not in self.currencies or impact not in self.impact_levels:
                continue

            date_str = item.get("date", "")
            if not date_str:
                continue

            try:
                event_dt = datetime.fromisoformat(date_str)
                event_dt_bkk = event_dt.astimezone(self.local_tz)

                parsed.append({
                    "title": item.get("title", "News Event"),
                    "country": curr,
                    "impact": impact,
                    "datetime_bkk": event_dt_bkk,
                    "forecast": item.get("forecast", ""),
                    "previous": item.get("previous", "")
                })
            except Exception:
                continue

        parsed.sort(key=lambda x: x["datetime_bkk"])
        self.events = parsed

    def check_shield(self) -> dict:
        if not self.enabled:
            return {
                "is_safe": True,
                "status": "DISABLED",
                "message": "News shield disabled",
                "next_event": None,
                "minutes_to_next": None
            }

        self.refresh_calendar()
        now_bkk = datetime.now(self.local_tz)
        nearest_upcoming = None
        min_future_diff = float("inf")
        latest_past = None
        min_past_diff = float("inf")

        for ev in self.events:
            diff_secs = (ev["datetime_bkk"] - now_bkk).total_seconds()
            diff_mins = diff_secs / 60.0

            if diff_mins >= 0:
                if diff_mins < min_future_diff:
                    min_future_diff = diff_mins
                    nearest_upcoming = ev
            else:
                past_mins = abs(diff_mins)
                if past_mins < min_past_diff:
                    min_past_diff = past_mins
                    latest_past = ev

        if nearest_upcoming and min_future_diff <= self.pre_pause_mins:
            mins_left = round(min_future_diff, 1)
            return {
                "is_safe": False,
                "status": "PRE_NEWS_PAUSE",
                "message": f"PAUSE: High impact {nearest_upcoming['country']} news '{nearest_upcoming['title']}' in {mins_left} mins",
                "next_event": nearest_upcoming,
                "minutes_to_next": mins_left
            }

        if latest_past and min_past_diff <= self.post_pause_mins:
            mins_passed = round(min_past_diff, 1)
            return {
                "is_safe": False,
                "status": "POST_NEWS_PAUSE",
                "message": f"PAUSE: High impact news '{latest_past['title']}' released {mins_passed} mins ago (Waiting for spread & volatility stabilization)",
                "next_event": nearest_upcoming,
                "minutes_to_next": round(min_future_diff, 1) if nearest_upcoming else None
            }

        mins_to_next = round(min_future_diff, 1) if nearest_upcoming else None
        next_title = nearest_upcoming['title'] if nearest_upcoming else 'None'
        return {
            "is_safe": True,
            "status": "SAFE",
            "message": f"SAFE TO TRADE (Next red event: {next_title} in {mins_to_next} mins)" if mins_to_next else "SAFE TO TRADE (No red events scheduled)",
            "next_event": nearest_upcoming,
            "minutes_to_next": mins_to_next
        }

    def get_upcoming_events(self, hours: int = 48) -> list:
        now_bkk = datetime.now(self.local_tz)
        cutoff = now_bkk + timedelta(hours=hours)
        return [
            ev for ev in self.events 
            if now_bkk <= ev["datetime_bkk"] <= cutoff
        ]
