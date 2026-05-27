"""Finnhub news client (US only).

Finnhub's free tier covers US news well but does NOT reliably cover Indian
markets (CLAUDE.md flags this). This client is therefore scoped to US.
Anything else falls back to yfinance via YFinanceSource.get_news.

Requires FINNHUB_API_KEY in the environment. If unset, `fetch_news` returns
[] — callers should treat absence of key as 'no Finnhub' and degrade.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .models import NewsItem


FINNHUB_BASE = "https://finnhub.io/api/v1"


class FinnhubNewsSource:
    def __init__(self, api_key: Optional[str] = None, *, timeout: float = 5.0) -> None:
        self.api_key = api_key or os.environ.get("FINNHUB_API_KEY", "")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def get_news(self, symbol: str, *, days: int = 7) -> list[NewsItem]:
        if not self.enabled:
            return []
        today = date.today()
        params = {
            "symbol": symbol.upper(),
            "from": (today - timedelta(days=days)).isoformat(),
            "to": today.isoformat(),
            "token": self.api_key,
        }
        url = f"{FINNHUB_BASE}/company-news?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                payload = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return []
        if not isinstance(payload, list):
            return []
        out: list[NewsItem] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            title = item.get("headline") or ""
            if not title:
                continue
            ts = item.get("datetime")
            published = (
                datetime.fromtimestamp(ts, tz=timezone.utc)
                if isinstance(ts, (int, float))
                else None
            )
            out.append(
                NewsItem(
                    title=title,
                    publisher=item.get("source") or "Finnhub",
                    url=item.get("url") or "",
                    published_at=published,
                    summary=item.get("summary") or None,
                )
            )
        return out
