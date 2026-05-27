"""Value objects returned by DataSource implementations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Quote:
    symbol: str
    market_code: str
    price: float
    currency: str
    as_of: datetime
    previous_close: Optional[float]
    stale: bool  # True when market is closed and price is the last close, not live.

    @property
    def change(self) -> Optional[float]:
        if self.previous_close is None:
            return None
        return self.price - self.previous_close

    @property
    def change_pct(self) -> Optional[float]:
        if not self.previous_close:
            return None
        return (self.price - self.previous_close) / self.previous_close * 100.0


@dataclass(frozen=True)
class NewsItem:
    title: str
    publisher: str
    url: str
    published_at: Optional[datetime]
    summary: Optional[str] = None
