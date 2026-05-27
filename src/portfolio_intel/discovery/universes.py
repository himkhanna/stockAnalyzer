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


# Hardcoded sector classification for the curated universes. Looking up
# sector via yfinance .info works but doubles scan latency — and the
# sector of a Nifty 50 / Dow 30 name doesn't change month-to-month, so
# baking it in is a fine trade-off. Anything not in the map shows as
# 'Other' on the UI.
_SECTORS: dict[tuple[str, str], str] = {
    # --- NSE / Nifty 50 ---
    ("ADANIENT", "NSE"): "Conglomerate",
    ("ADANIPORTS", "NSE"): "Infrastructure",
    ("APOLLOHOSP", "NSE"): "Healthcare",
    ("ASIANPAINT", "NSE"): "Consumer",
    ("AXISBANK", "NSE"): "Banking",
    ("BAJAJ-AUTO", "NSE"): "Auto",
    ("BAJAJFINSV", "NSE"): "Financials",
    ("BAJFINANCE", "NSE"): "Financials",
    ("BEL", "NSE"): "Defence",
    ("BHARTIARTL", "NSE"): "Telecom",
    ("BPCL", "NSE"): "Energy",
    ("BRITANNIA", "NSE"): "Consumer",
    ("CIPLA", "NSE"): "Healthcare",
    ("COALINDIA", "NSE"): "Energy",
    ("DIVISLAB", "NSE"): "Healthcare",
    ("DRREDDY", "NSE"): "Healthcare",
    ("EICHERMOT", "NSE"): "Auto",
    ("GRASIM", "NSE"): "Materials",
    ("HCLTECH", "NSE"): "IT",
    ("HDFCBANK", "NSE"): "Banking",
    ("HDFCLIFE", "NSE"): "Financials",
    ("HEROMOTOCO", "NSE"): "Auto",
    ("HINDALCO", "NSE"): "Materials",
    ("HINDUNILVR", "NSE"): "Consumer",
    ("ICICIBANK", "NSE"): "Banking",
    ("INDUSINDBK", "NSE"): "Banking",
    ("INFY", "NSE"): "IT",
    ("ITC", "NSE"): "Consumer",
    ("JSWSTEEL", "NSE"): "Materials",
    ("KOTAKBANK", "NSE"): "Banking",
    ("LT", "NSE"): "Infrastructure",
    ("LTIM", "NSE"): "IT",
    ("M&M", "NSE"): "Auto",
    ("MARUTI", "NSE"): "Auto",
    ("NESTLEIND", "NSE"): "Consumer",
    ("NTPC", "NSE"): "Energy",
    ("ONGC", "NSE"): "Energy",
    ("POWERGRID", "NSE"): "Utilities",
    ("RELIANCE", "NSE"): "Conglomerate",
    ("SBILIFE", "NSE"): "Financials",
    ("SBIN", "NSE"): "Banking",
    ("SHRIRAMFIN", "NSE"): "Financials",
    ("SUNPHARMA", "NSE"): "Healthcare",
    ("TATACONSUM", "NSE"): "Consumer",
    ("TATAMOTORS", "NSE"): "Auto",
    ("TATASTEEL", "NSE"): "Materials",
    ("TCS", "NSE"): "IT",
    ("TECHM", "NSE"): "IT",
    ("TITAN", "NSE"): "Consumer",
    ("TRENT", "NSE"): "Consumer",
    ("ULTRACEMCO", "NSE"): "Materials",
    ("WIPRO", "NSE"): "IT",
    # --- US / Dow 30 ---
    ("AAPL", "US"): "Tech",
    ("AMGN", "US"): "Healthcare",
    ("AMZN", "US"): "Consumer",
    ("AXP", "US"): "Financials",
    ("BA", "US"): "Industrials",
    ("CAT", "US"): "Industrials",
    ("CRM", "US"): "Tech",
    ("CSCO", "US"): "Tech",
    ("CVX", "US"): "Energy",
    ("DIS", "US"): "Consumer",
    ("GS", "US"): "Financials",
    ("HD", "US"): "Consumer",
    ("HON", "US"): "Industrials",
    ("IBM", "US"): "Tech",
    ("JNJ", "US"): "Healthcare",
    ("JPM", "US"): "Financials",
    ("KO", "US"): "Consumer",
    ("MCD", "US"): "Consumer",
    ("MMM", "US"): "Industrials",
    ("MRK", "US"): "Healthcare",
    ("MSFT", "US"): "Tech",
    ("NKE", "US"): "Consumer",
    ("NVDA", "US"): "Tech",
    ("PG", "US"): "Consumer",
    ("SHW", "US"): "Materials",
    ("TRV", "US"): "Financials",
    ("UNH", "US"): "Healthcare",
    ("V", "US"): "Financials",
    ("VZ", "US"): "Telecom",
    ("WMT", "US"): "Consumer",
    # --- DFM / ADX ---
    ("EMAAR", "DFM"): "Real Estate",
    ("DEWA", "DFM"): "Utilities",
    ("EMIRATESNBD", "DFM"): "Banking",
    ("ALMAS", "DFM"): "Real Estate",
    ("EMAARDEV", "DFM"): "Real Estate",
    ("ARM", "DFM"): "Consumer",
    ("DIB", "DFM"): "Banking",
    ("AJMANBANK", "DFM"): "Banking",
    ("DU", "DFM"): "Telecom",
    ("TECOM", "DFM"): "Real Estate",
    ("IHC", "ADX"): "Conglomerate",
    ("FAB", "ADX"): "Banking",
    ("ADCB", "ADX"): "Banking",
    ("ETISALAT", "ADX"): "Telecom",
    ("ALDAR", "ADX"): "Real Estate",
    ("TAQA", "ADX"): "Utilities",
    ("ADNOCDIST", "ADX"): "Energy",
    ("ADNOCDRILL", "ADX"): "Energy",
    ("ADIB", "ADX"): "Banking",
    ("MULTIPLY", "ADX"): "Conglomerate",
}


def sector_for(symbol: str, market_code: str) -> str:
    """Return the hardcoded sector for a (symbol, market), or 'Other'."""
    return _SECTORS.get((symbol.upper(), market_code.upper()), "Other")
