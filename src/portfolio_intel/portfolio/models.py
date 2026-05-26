"""Portfolio value objects."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Holding:
    ticker: str
    market_code: str  # e.g. "US", "NSE", "BSE"
    shares: float
    cost_basis: float  # per-share cost, in the currency below
    currency: str  # currency the position was bought in; never silently converted
    date_added: date
