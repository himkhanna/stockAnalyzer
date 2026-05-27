"""Lightweight live-quote endpoint.

The dashboard payload (/api/holdings) computes indicators, scores and
sentiment — that's an expensive build cached for 1h. During market hours
the user expects the *price* to be live; the rest is fine to lag.

This router fetches only prices for the user's current holdings via a
single bulk Yahoo call, with a market-open flag per row so the frontend
can render a 'live' dot only when it's actually meaningful.
"""
from __future__ import annotations

import time
import threading
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from portfolio_intel.batch import items_from_portfolio
from portfolio_intel.data.yfinance_source import is_market_open
from portfolio_intel.markets import Market

from ..state import get_source, get_store


router = APIRouter()

# In-process cache so rapid polls (multiple browser tabs, focus blur, etc.)
# don't hammer Yahoo. 20s is short enough to feel live, long enough to
# absorb bursts.
_CACHE_TTL_S = 20.0
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, list[dict], bool]] = {}


class LiveQuote(BaseModel):
    symbol: str
    market: str
    currency_symbol: str
    price: float
    previous_close: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    market_open: bool
    as_of: str


class LiveQuotesOut(BaseModel):
    quotes: list[LiveQuote]
    any_market_open: bool
    cached: bool = False


@router.get("", response_model=LiveQuotesOut)
def live_quotes() -> LiveQuotesOut:
    """Bulk price-only fetch for every holding in the portfolio."""
    store = get_store()
    items = items_from_portfolio(store)
    if not items:
        return LiveQuotesOut(quotes=[], any_market_open=False)

    # Cache key = the sorted ticker set. If holdings change, the key changes,
    # the cache misses, fresh fetch.
    key = "|".join(sorted(f"{it.symbol}@{it.market.code}" for it in items))
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL_S:
            return LiveQuotesOut(quotes=[LiveQuote(**q) for q in cached[1]],
                                 any_market_open=cached[2], cached=True)

    src = get_source()
    quote_map = src.get_quotes_bulk([(it.symbol, it.market) for it in items])

    out_quotes: list[dict] = []
    any_open = False
    for it in items:
        mkt: Market = it.market
        open_now = is_market_open(mkt)
        any_open = any_open or open_now
        q = quote_map.get((it.symbol.upper(), mkt.code))
        if q is None:
            continue
        change = (q.price - q.previous_close) if q.previous_close else None
        change_pct = (
            (change / q.previous_close * 100.0)
            if change is not None and q.previous_close
            else None
        )
        out_quotes.append({
            "symbol": it.symbol.upper(),
            "market": mkt.code,
            "currency_symbol": mkt.currency_symbol,
            "price": q.price,
            "previous_close": q.previous_close,
            "change": change,
            "change_pct": change_pct,
            "market_open": open_now,
            "as_of": q.as_of.isoformat(),
        })

    with _CACHE_LOCK:
        _CACHE[key] = (now, out_quotes, any_open)

    return LiveQuotesOut(
        quotes=[LiveQuote(**q) for q in out_quotes],
        any_market_open=any_open,
    )
