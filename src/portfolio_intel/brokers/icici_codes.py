"""Seed map: NSE F&O underlying ticker -> ICICI Breeze broker stock_code.

Breeze's F&O endpoints reject the bare NSE ticker for stocks where the
ICICI internal code differs (SBIN -> STABAN, RELIANCE -> RELIND, ...).
The learned dictionary in `broker_code_map` is the source of truth, but
for a first-time user with no holdings synced yet, hitting a 502 on the
most-traded names is a bad first impression.

This module ships a small, conservative seed list covering the most
liquid NSE F&O underlyings. Entries here are checked *after* the
user-learned DB dictionary, so they never override a confirmed-working
mapping. If a seed entry is wrong, the user can supply the correct
broker_code via the override field once and the DB will take precedence
forever after.

Sourced from publicly-circulated breeze-connect examples; treat as a
best-effort hint, not gospel.
"""
from __future__ import annotations

# Indices: ICICI accepts the bare names for F&O lookups.
_INDICES: dict[str, str] = {
    "NIFTY":      "NIFTY",
    "BANKNIFTY":  "CNXBAN",
    "FINNIFTY":   "CNXFIN",
    "MIDCPNIFTY": "NIFMID",
    "SENSEX":     "SENSEX",
}

# High-liquidity stock F&O underlyings where the ICICI code differs.
# Identity mappings (ticker == broker_code) are omitted on purpose —
# the resolver already falls through to the bare symbol.
_STOCKS: dict[str, str] = {
    "SBIN":       "STABAN",
    "RELIANCE":   "RELIND",
    "INFY":       "INFTEC",
    "HDFCBANK":   "HDFBAN",
    "ICICIBANK":  "ICIBAN",
    "AXISBANK":   "AXIBAN",
    "KOTAKBANK":  "KOTMAH",
    "HCLTECH":    "HCLTEC",
    "LT":         "LARTOU",
    "TATAMOTORS": "TATMOT",
    "TATASTEEL": "TATSTE",
    "BHARTIARTL": "BHAART",
    "ASIANPAINT": "ASIPAI",
    "MARUTI":     "MARUDY",
    "BAJFINANCE": "BAJFIN",
    "BAJAJFINSV": "BAJFIV",
    "ULTRACEMCO": "ULTCEM",
    "TITAN":      "TITIND",
    "M&M":        "MAHMAH",
    "MM":         "MAHMAH",
    "HINDUNILVR": "HINLEV",
    "ONGC":       "OILNAT",
    "POWERGRID":  "POWGRI",
    "SUNPHARMA":  "SUNPHA",
    "DIVISLAB":   "DIVLAB",
    "EXIDEIND":   "EXIIND",
    "ADANIENT":   "ADAENT",
    "ADANIPORTS": "ADAPOR",
    "GRASIM":     "GRAIND",
    "JSWSTEEL":   "JSWSTE",
    "BAJAJ-AUTO": "BAJAUT",
    "BAJAJAUTO":  "BAJAUT",
}

_SEED: dict[str, str] = {**_INDICES, **_STOCKS}


def seed_broker_code(exchange_ticker: str) -> str | None:
    """Return the seed ICICI broker code for an NSE ticker, or None.

    Lookup is case-insensitive. The DB dictionary takes precedence over
    this map; this is the next fallback before the bare-symbol guess.
    """
    if not exchange_ticker:
        return None
    return _SEED.get(exchange_ticker.strip().upper())
