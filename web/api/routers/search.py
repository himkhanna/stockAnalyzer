"""GET /api/search?q=reliance → ticker suggestions from Yahoo.

Filters to the markets this app supports (US / NSE / BSE) so users don't pick
a ticker from an exchange we can't analyse.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter()


# Yahoo exchange codes → our Market codes. EQUITIES + ETFs only.
_US_EXCHANGES = {"NMS", "NYQ", "NCM", "NGM", "ASE", "PNK", "BTS", "NYE"}
_EXCHANGE_TO_MARKET = {ex: "US" for ex in _US_EXCHANGES}
_EXCHANGE_TO_MARKET["NSI"] = "NSE"
_EXCHANGE_TO_MARKET["BSE"] = "BSE"

_ALLOWED_QUOTE_TYPES = {"EQUITY", "ETF"}


class SearchHit(BaseModel):
    symbol: str
    name: str
    market: str
    exchange: str
    quote_type: str


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHit]


@router.get("", response_model=SearchOut)
def search(
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(10, ge=1, le=25),
) -> SearchOut:
    import yfinance as yf

    hits: list[SearchHit] = []
    seen: set[str] = set()

    try:
        # max_results is per request; ask for a few extra so we still hit `limit`
        # after filtering to US/NSE/BSE.
        results = yf.Search(q, max_results=limit * 2)
        quotes: list[dict] = list(getattr(results, "quotes", []) or [])
    except Exception:
        quotes = []

    for item in quotes:
        symbol: Optional[str] = item.get("symbol")
        exchange: Optional[str] = item.get("exchange")
        quote_type: Optional[str] = item.get("quoteType")
        if not symbol or not exchange:
            continue
        if quote_type and quote_type not in _ALLOWED_QUOTE_TYPES:
            continue
        market = _EXCHANGE_TO_MARKET.get(exchange)
        if market is None:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)

        name = (
            item.get("shortname")
            or item.get("longname")
            or item.get("name")
            or symbol
        )
        hits.append(SearchHit(
            symbol=symbol,
            name=name,
            market=market,
            exchange=exchange,
            quote_type=quote_type or "EQUITY",
        ))
        if len(hits) >= limit:
            break

    return SearchOut(query=q, hits=hits)
