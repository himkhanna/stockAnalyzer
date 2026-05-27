"""DataSource interface.

All market data access goes through this seam. Phase 1 has one implementation
(yfinance); later phases may add Finnhub for richer US news or broker APIs
(Zerodha Kite, Upstox) for India.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..markets import Market
from .models import NewsItem, Quote


class DataSourceError(RuntimeError):
    """Raised when a data source cannot fulfill a request."""


class DataSource(ABC):
    """Abstract market-data provider."""

    @abstractmethod
    def supports(self, market: Market) -> bool:
        """Whether this source can serve the given market."""

    @abstractmethod
    def get_quote(self, symbol: str, market: Market) -> Quote:
        """Fetch the latest quote. Returns a stale=True quote if market is closed."""

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        market: Market,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Historical OHLCV as a DataFrame indexed by date.

        Columns: open, high, low, close, volume (lowercase).
        """

    @abstractmethod
    def get_news(self, symbol: str, market: Market) -> list[NewsItem]:
        """Recent news. May return [] when no coverage is available — callers
        must handle this gracefully (do not raise on empty)."""
