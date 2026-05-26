"""News provider routing.

For US tickers: Finnhub if a key is configured, fall back to yfinance.
For NSE/BSE: yfinance only — CLAUDE.md flags that Finnhub's free tier
does not reliably cover India. If yfinance returns nothing, we return []
and the digest runs on technicals alone (graceful degradation).
"""
from __future__ import annotations

from typing import Optional

from ..data.base import DataSource
from ..data.finnhub_news import FinnhubNewsSource
from ..data.models import NewsItem
from ..markets import Market


def fetch_news(
    symbol: str,
    market: Market,
    *,
    data_source: DataSource,
    finnhub: Optional[FinnhubNewsSource] = None,
) -> list[NewsItem]:
    """Return news for (symbol, market), choosing the best available source."""
    finnhub = finnhub or FinnhubNewsSource()

    if market is Market.US and finnhub.enabled:
        items = finnhub.get_news(symbol)
        if items:
            return items
        # Finnhub returned empty -> fall through to yfinance.

    try:
        return data_source.get_news(symbol, market)
    except Exception:
        return []
