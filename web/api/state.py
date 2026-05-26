"""Shared singletons + the disk-backed row cache.

Mirrors what the Streamlit app did with session_state, but here we keep
state in-process and persist to .rows_cache_api.pkl so reloads / restarts
don't trigger a refetch.
"""
from __future__ import annotations

import os
import pickle
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from portfolio_intel.batch import BatchItem, items_from_portfolio
from portfolio_intel.data.base import DataSourceError
from portfolio_intel.data.finnhub_news import FinnhubNewsSource
from portfolio_intel.data.yfinance_source import YFinanceSource
from portfolio_intel.digest import build_digest
from portfolio_intel.markets import Market
from portfolio_intel.portfolio.models import Holding
from portfolio_intel.portfolio.store import PortfolioStore
from portfolio_intel.scoring.weights import DEFAULT_WEIGHTS


DB_PATH = os.environ.get("PORTFOLIO_DB", "portfolio.db")
DEFAULT_PERIOD = os.environ.get("HISTORY_WINDOW", "1y")
ROWS_CACHE_FILE = Path(".rows_cache_api.pkl")
ROWS_CACHE_TTL_S = 60 * 60  # 1h


_store_lock = threading.Lock()
_source_singleton: Optional[YFinanceSource] = None
_finnhub_singleton: Optional[FinnhubNewsSource] = None


def get_store(db_path: str = DB_PATH) -> PortfolioStore:
    return PortfolioStore(db_path)


def get_source() -> YFinanceSource:
    global _source_singleton
    if _source_singleton is None:
        _source_singleton = YFinanceSource()
    return _source_singleton


def get_finnhub() -> FinnhubNewsSource:
    global _finnhub_singleton
    if _finnhub_singleton is None:
        _finnhub_singleton = FinnhubNewsSource()
    return _finnhub_singleton


@dataclass
class CardRow:
    card: dict
    holding: Optional[Holding]
    market_value: float = 0.0
    cost_total: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    weight_pct: Optional[float] = None
    overweight: bool = False


def _card_from_digest(symbol: str, market: Market, period: str) -> dict:
    try:
        digest = build_digest(
            symbol,
            market,
            data_source=get_source(),
            finnhub=get_finnhub(),
            period=period,
            run_llm=False,
        )
    except (DataSourceError, ValueError) as e:
        return {"error": str(e), "symbol": symbol, "market_code": market.code}

    return {
        "symbol": symbol,
        "market_code": market.code,
        "currency": market.currency,
        "currency_symbol": market.currency_symbol,
        "price": digest.quote.price if digest.quote else digest.snapshot.close,
        "change_pct": digest.quote.change_pct if digest.quote else None,
        "stale": digest.quote.stale if digest.quote else False,
        "score_value": digest.score.value,
        "score_label": digest.score.label,
        "rsi": digest.snapshot.rsi,
        "trend": digest.snapshot.trend_label,
        "sentiment_label": digest.sentiment.label,
        "sentiment_total": digest.sentiment.total,
        "setup_valid": digest.setup.valid if digest.setup else False,
        "setup_entry": digest.setup.entry if digest.setup else None,
        "setup_stop": digest.setup.stop if digest.setup else None,
        "setup_target": digest.setup.target if digest.setup else None,
        "setup_rr": digest.setup.risk_reward if digest.setup else None,
        "recent_closes": digest.recent_closes,
    }


def _build_rows(items: list[BatchItem], period: str) -> list[CardRow]:
    rows: list[CardRow] = []
    bucket_totals: dict[str, float] = defaultdict(float)

    for it in items:
        c = _card_from_digest(it.symbol, it.market, period)
        row = CardRow(card=c, holding=it.holding)
        if it.holding and not c.get("error") and c.get("price") is not None:
            row.market_value = float(c["price"]) * it.holding.shares
            row.cost_total = it.holding.cost_basis * it.holding.shares
            row.pnl = row.market_value - row.cost_total
            row.pnl_pct = (row.pnl / row.cost_total * 100.0) if row.cost_total else 0.0
            bucket_totals[it.holding.currency] += row.market_value
        rows.append(row)

    for row in rows:
        if row.holding and row.market_value > 0:
            total = bucket_totals.get(row.holding.currency, 0.0)
            if total > 0:
                row.weight_pct = row.market_value / total * 100.0
                row.overweight = row.weight_pct > DEFAULT_WEIGHTS.overweight_pct

    return rows


def _fingerprint(items: list[BatchItem], db_path: str, period: str) -> tuple:
    return (
        db_path, period,
        tuple(sorted((it.symbol, it.market.code) for it in items)),
    )


def _load_disk() -> Optional[dict]:
    if not ROWS_CACHE_FILE.exists():
        return None
    try:
        with ROWS_CACHE_FILE.open("rb") as f:
            return pickle.load(f)
    except (pickle.UnpicklingError, EOFError, AttributeError, ImportError):
        try:
            ROWS_CACHE_FILE.unlink()
        except OSError:
            pass
        return None


def _save_disk(payload: dict) -> None:
    try:
        with ROWS_CACHE_FILE.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError:
        pass


def get_dashboard(*, db_path: str = DB_PATH, period: str = DEFAULT_PERIOD,
                  force: bool = False) -> dict:
    """Return cached rows when available, otherwise build them. Thread-safe."""
    with _store_lock:
        store = get_store(db_path)
        items = items_from_portfolio(store)
        fp = _fingerprint(items, db_path, period)

        if not force:
            cached = _load_disk()
            if cached and cached.get("fp") == fp:
                age = time.time() - cached.get("saved_ts", 0)
                return {
                    "rows": cached["rows"],
                    "loaded_at": cached.get("loaded_at", ""),
                    "stale": age > ROWS_CACHE_TTL_S,
                }

        rows = _build_rows(items, period)
        payload = {
            "fp": fp,
            "rows": rows,
            "loaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "saved_ts": time.time(),
        }
        _save_disk(payload)
        return {
            "rows": rows,
            "loaded_at": payload["loaded_at"],
            "stale": False,
        }


def invalidate_dashboard() -> None:
    try:
        ROWS_CACHE_FILE.unlink(missing_ok=True)
    except OSError:
        pass
