"""Curated per-market universes for the Discover panel.

Picked for liquidity and coverage, not exhaustiveness. Smaller lists keep
the cold-scan time bounded (the bottleneck is yfinance, ~1s per ticker).

Lists are bare symbols — the data source adds the .NS / .BO suffix.
"""
from __future__ import annotations

from ..markets import Market

# NIFTY 50 constituents (NSE) — as of early 2026.
NIFTY_50: list[str] = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BEL", "BHARTIARTL",
    "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB",
    "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK",
    "INDUSINDBK", "INFY", "ITC", "JSWSTEEL", "KOTAKBANK",
    "LT", "LTIM", "M&M", "MARUTI", "NESTLEIND",
    "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE",
    "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS",
    "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT",
    "ULTRACEMCO", "WIPRO",
]

# Dow Jones Industrial Average — 30 large-cap US names.
DOW_30: list[str] = [
    "AAPL", "AMGN", "AMZN", "AXP", "BA",
    "CAT", "CRM", "CSCO", "CVX", "DIS",
    "GS", "HD", "HON", "IBM", "JNJ",
    "JPM", "KO", "MCD", "MMM", "MRK",
    "MSFT", "NKE", "NVDA", "PG", "SHW",
    "TRV", "UNH", "V", "VZ", "WMT",
]

# DFM (Dubai) top-liquidity picks. Smaller market, fewer names.
DFM_TOP: list[str] = [
    "EMAAR", "DEWA", "EMIRATESNBD", "ALMAS", "EMAARDEV",
    "ARM", "DIB", "AJMANBANK", "DU", "TECOM",
]

# ADX (Abu Dhabi) — same logic.
ADX_TOP: list[str] = [
    "IHC", "FAB", "ADCB", "ETISALAT", "ALDAR",
    "TAQA", "ADNOCDIST", "ADNOCDRILL", "ADIB", "MULTIPLY",
]


UNIVERSES: dict[Market, list[str]] = {
    Market.NSE: NIFTY_50,
    Market.US: DOW_30,
    Market.DFM: DFM_TOP,
    Market.ADX: ADX_TOP,
}


def universe_for(market: Market) -> list[str]:
    """Return the curated discovery list for a market, or [] if none."""
    return UNIVERSES.get(market, [])
