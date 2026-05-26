"""Market abstraction.

A Market encapsulates everything that varies by exchange: currency, ticker
suffix conventions, timezone. Adding a new market should mean adding one
entry here — not editing logic elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class MarketSpec:
    code: str
    name: str
    currency: str
    currency_symbol: str
    yfinance_suffix: str
    timezone: str


class Market(Enum):
    US = MarketSpec("US", "United States", "USD", "$", "", "America/New_York")
    NSE = MarketSpec("NSE", "National Stock Exchange of India", "INR", "₹", ".NS", "Asia/Kolkata")
    BSE = MarketSpec("BSE", "Bombay Stock Exchange", "INR", "₹", ".BO", "Asia/Kolkata")

    @property
    def code(self) -> str:
        return self.value.code

    @property
    def currency(self) -> str:
        return self.value.currency

    @property
    def currency_symbol(self) -> str:
        return self.value.currency_symbol

    @property
    def yfinance_suffix(self) -> str:
        return self.value.yfinance_suffix

    @property
    def timezone(self) -> str:
        return self.value.timezone

    def format_ticker(self, symbol: str) -> str:
        """Return the yfinance-qualified symbol for this market."""
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol is empty")
        # Yahoo indices use a ^ prefix and are global (no exchange suffix).
        if symbol.startswith("^"):
            return symbol
        if self.yfinance_suffix and symbol.endswith(self.yfinance_suffix):
            return symbol
        return f"{symbol}{self.yfinance_suffix}"

    @classmethod
    def from_code(cls, code: str) -> "Market":
        code = code.strip().upper()
        for m in cls:
            if m.code == code:
                return m
        raise ValueError(f"unknown market: {code!r}")


# Suffix -> market, longest first so multi-char suffixes match before the empty US default.
_SUFFIX_MAP = sorted(
    [(m.yfinance_suffix, m) for m in Market if m.yfinance_suffix],
    key=lambda x: -len(x[0]),
)


def parse_ticker(raw: str, default_market: Optional[Market] = None) -> tuple[str, Market]:
    """Normalize a user-entered ticker.

    Accepts either a qualified symbol (RELIANCE.NS, AAPL) or a bare symbol
    when default_market is supplied. Returns (bare_symbol, Market).
    """
    if raw is None:
        raise ValueError("ticker is empty")
    s = raw.strip().upper()
    if not s:
        raise ValueError("ticker is empty")

    for suffix, market in _SUFFIX_MAP:
        if s.endswith(suffix):
            return s[: -len(suffix)], market

    # No recognized suffix.
    if default_market is not None:
        return s, default_market
    return s, Market.US


# Yahoo-formatted index symbols for the market-pulse panel. Kept here so adding
# a new market means adding its bellwether index alongside the Market enum.
INDICES: list[tuple[str, str, str]] = [
    # (yahoo_symbol, display_name, market_code)
    ("^GSPC",   "S&P 500",        "US"),
    ("^IXIC",   "NASDAQ",         "US"),
    ("^DJI",    "Dow Jones",      "US"),
    ("^NSEI",   "NIFTY 50",       "NSE"),
    ("^NSEBANK","NIFTY BANK",     "NSE"),
    ("^BSESN",  "SENSEX",         "BSE"),
]
