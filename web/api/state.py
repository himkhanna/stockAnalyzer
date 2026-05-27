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

    rule_hits = list(getattr(digest, "rules", []) or [])
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
        "rule_count": len(rule_hits),
        "rule_names": [h.name for h in rule_hits],
        "rule_notes": [h.note for h in rule_hits],
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
        loaded_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        _persist_signals(store, rows, captured_at=loaded_at)
        _evaluate_alerts(store, rows, captured_at=loaded_at)
        payload = {
            "fp": fp,
            "rows": rows,
            "loaded_at": loaded_at,
            "saved_ts": time.time(),
        }
        _save_disk(payload)
        return {
            "rows": rows,
            "loaded_at": payload["loaded_at"],
            "stale": False,
        }


def _persist_signals(store: PortfolioStore, rows: list[CardRow], *, captured_at: str) -> None:
    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        val = c.get("score_value")
        lbl = c.get("score_label")
        sym = c.get("symbol")
        mkt = c.get("market_code")
        if val is None or not lbl or not sym or not mkt:
            continue
        try:
            store.signal_record(sym, mkt, float(val), lbl, captured_at)
        except Exception:
            continue  # signal history is best-effort; never break the dashboard


def build_card_for(symbol: str, market: Market, period: str = DEFAULT_PERIOD) -> CardRow:
    """Build a single CardRow for any (symbol, market) — used by lookup & insights."""
    c = _card_from_digest(symbol, market, period)
    return CardRow(card=c, holding=None)


# --- Alerts evaluator -------------------------------------------------------

_ALERT_KINDS = {
    "price_above", "price_below",
    "rsi_above", "rsi_below",
    "score_at_or_above", "score_at_or_below",
    "score_flip_buy", "score_flip_sell",
    "pct_drop_day", "pct_rise_day",
}


def _evaluate_alerts(store: PortfolioStore, rows: list[CardRow], *, captured_at: str) -> None:
    """Walk every active alert rule against the freshly-built rows. Fire an
    alert_event when the condition holds. Non-fatal on errors — alerts must
    never break the dashboard refresh."""
    try:
        alerts = store.alerts_list(active_only=True)
    except Exception:
        return
    if not alerts:
        return

    # Index rows by (ticker, market) for O(1) lookup.
    by_key: dict[tuple[str, str], dict] = {}
    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        sym = (c.get("symbol") or "").upper()
        mkt = (c.get("market_code") or "").upper()
        if sym and mkt:
            by_key[(sym, mkt)] = c

    for a in alerts:
        try:
            card = by_key.get((a["ticker"].upper(), a["market"].upper()))
            if card is None:
                continue
            kind = a["kind"]
            if kind not in _ALERT_KINDS:
                continue
            threshold = float(a["threshold"])
            triggered, value, msg = _check_alert(kind, threshold, card, store, captured_at)
            if not triggered:
                continue
            store.alert_event_add(
                alert_id=int(a["id"]),
                ticker=a["ticker"],
                market_code=a["market"],
                kind=kind,
                threshold=threshold,
                fired_at=captured_at,
                triggered_value=value,
                message=msg,
            )
            store.alert_mark_fired(int(a["id"]), captured_at)
        except Exception:
            # One bad rule must not poison the rest.
            continue


def _check_alert(kind: str, threshold: float, card: dict,
                 store: PortfolioStore, current_captured_at: str
                 ) -> tuple[bool, Optional[float], str]:
    sym = card.get("symbol", "")
    mkt = card.get("market_code", "")

    price = card.get("price")
    rsi = card.get("rsi")
    score_value = card.get("score_value")
    score_label = card.get("score_label") or ""
    change_pct = card.get("change_pct")

    if kind == "price_above" and price is not None and price >= threshold:
        return True, float(price), f"{sym} price {price:.2f} crossed ≥ {threshold:g}"
    if kind == "price_below" and price is not None and price <= threshold:
        return True, float(price), f"{sym} price {price:.2f} crossed ≤ {threshold:g}"
    if kind == "rsi_above" and rsi is not None and rsi >= threshold:
        return True, float(rsi), f"{sym} RSI {rsi:.0f} ≥ {threshold:g}"
    if kind == "rsi_below" and rsi is not None and rsi <= threshold:
        return True, float(rsi), f"{sym} RSI {rsi:.0f} ≤ {threshold:g}"
    if kind == "score_at_or_above" and score_value is not None and score_value >= threshold:
        return True, float(score_value), f"{sym} score {score_value:+.1f} ≥ {threshold:+g} ({score_label})"
    if kind == "score_at_or_below" and score_value is not None and score_value <= threshold:
        return True, float(score_value), f"{sym} score {score_value:+.1f} ≤ {threshold:+g} ({score_label})"
    if kind == "pct_drop_day" and change_pct is not None and change_pct <= -abs(threshold):
        return True, float(change_pct), f"{sym} dropped {change_pct:.2f}% today (≤ -{abs(threshold):g}%)"
    if kind == "pct_rise_day" and change_pct is not None and change_pct >= abs(threshold):
        return True, float(change_pct), f"{sym} rose {change_pct:.2f}% today (≥ +{abs(threshold):g}%)"

    # Flip detection compares against the most recent prior captured signal.
    if kind in ("score_flip_buy", "score_flip_sell") and score_value is not None:
        prev = store.signal_previous(sym, mkt, current_captured_at)
        if prev is None:
            return False, None, ""
        prev_value, prev_label, _ = prev
        if kind == "score_flip_buy":
            # bullish flip into Buy/Strong Buy territory (score >= 2.0)
            if prev_value < 2.0 and score_value >= 2.0:
                return True, float(score_value), (
                    f"{sym} flipped to {score_label} ({prev_label} → {score_label})"
                )
        else:
            if prev_value > -2.0 and score_value <= -2.0:
                return True, float(score_value), (
                    f"{sym} flipped to {score_label} ({prev_label} → {score_label})"
                )

    return False, None, ""


def invalidate_dashboard() -> None:
    try:
        ROWS_CACHE_FILE.unlink(missing_ok=True)
    except OSError:
        pass
