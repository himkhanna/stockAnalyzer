"""Watchlist CRUD — separate from portfolio holdings (no shares / cost)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from portfolio_intel.markets import Market

from ..schemas import WatchlistItemIn, WatchlistItemOut
from ..state import get_store

router = APIRouter()


@router.get("", response_model=list[WatchlistItemOut])
def list_watchlist() -> list[WatchlistItemOut]:
    return [
        WatchlistItemOut(ticker=t, market=m, note=n, date_added=d)
        for (t, m, n, d) in get_store().watchlist_all()
    ]


@router.post("", response_model=WatchlistItemOut)
def add_watchlist(item: WatchlistItemIn) -> WatchlistItemOut:
    try:
        Market.from_code(item.market)
    except Exception:
        raise HTTPException(status_code=400, detail=f"unknown market {item.market}")
    if not item.ticker.strip():
        raise HTTPException(status_code=400, detail="ticker required")
    store = get_store()
    store.watchlist_add(item.ticker.strip().upper(), item.market.upper(), item.note or "")
    for t, m, n, d in store.watchlist_all():
        if t == item.ticker.strip().upper() and m == item.market.upper():
            return WatchlistItemOut(ticker=t, market=m, note=n, date_added=d)
    raise HTTPException(status_code=500, detail="failed to read back inserted row")


@router.delete("/{symbol}/{market}", status_code=204)
def remove_watchlist(symbol: str, market: str) -> None:
    ok = get_store().watchlist_remove(symbol, market)
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
