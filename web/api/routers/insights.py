"""GET /api/insights → conviction board, watchlist scan, market pulse, risk,
signal changes, upcoming earnings.

Every directional claim here comes from the existing deterministic scoring
engine + rules. The LLM is not consulted. Per CLAUDE.md: signals are decision
support, never advice.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

from portfolio_intel.markets import INDICES, Market

from ..schemas import (
    CardRowOut,
    ConvictionRow,
    CurrencyExposure,
    EarningsItem,
    IndexSnapshot,
    InsightsOut,
    RiskPanel,
    RiskTopWeight,
    SignalChange,
)
from ..serializers import card_row_to_out
from ..state import build_card_for, get_dashboard, get_source, get_store

router = APIRouter()
_DIGEST_DIR = Path(os.environ.get("DIGEST_DIR", "digests"))

# Conviction = strong score AND a confirming rule. The threshold matches
# the Strong Buy / Strong Sell cutoff in scoring/weights.py (±6.0).
_CONVICTION_ABS_SCORE = 6.0

# Rough FX to convert currency buckets to a common unit so we can show
# pct-of-total exposure. NOT used for any P&L calculation — purely for
# the "% of portfolio" chart on the risk panel. Honest fallback if FX
# isn't available.
_ROUGH_FX_TO_INR = {"INR": 1.0, "USD": 83.0, "AED": 22.6}


@router.get("", response_model=InsightsOut)
def get_insights() -> InsightsOut:
    payload = get_dashboard()
    rows = payload["rows"]

    return InsightsOut(
        conviction=_conviction_panel(rows),
        watchlist=_watchlist_panel(),
        indices=_indices_panel(),
        risk=_risk_panel(rows),
        signal_changes=_signal_changes_panel(rows, payload.get("loaded_at", "")),
        upcoming_earnings=_earnings_panel(rows),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


# --- Conviction board ---

def _conviction_panel(rows) -> list[ConvictionRow]:
    out: list[ConvictionRow] = []
    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        v = c.get("score_value")
        if v is None:
            continue
        if abs(float(v)) < _CONVICTION_ABS_SCORE:
            continue
        if int(c.get("rule_count", 0)) < 1:
            continue
        out.append(ConvictionRow(
            row=card_row_to_out(r, digest_dir=_DIGEST_DIR),
            direction="bullish" if v > 0 else "bearish",
            rule_count=int(c.get("rule_count", 0)),
            rule_notes=list(c.get("rule_notes") or [])[:4],
        ))
    out.sort(key=lambda x: abs(x.row.score_value or 0.0), reverse=True)
    return out


# --- Watchlist scan ---

def _watchlist_panel() -> list[CardRowOut]:
    store = get_store()
    items = store.watchlist_all()
    out: list[CardRowOut] = []
    for ticker, market_code, _note, _added in items:
        try:
            market = Market.from_code(market_code)
        except Exception:
            continue
        row = build_card_for(ticker, market)
        out.append(card_row_to_out(row, digest_dir=_DIGEST_DIR))
    # Sort by absolute score so the strongest signals float to the top.
    out.sort(key=lambda r: abs(r.score_value or 0.0), reverse=True)
    return out


# --- Market pulse (indices) ---

def _indices_panel() -> list[IndexSnapshot]:
    snaps: list[IndexSnapshot] = []
    src = get_source()
    for symbol, name, market_code in INDICES:
        try:
            mkt = Market.from_code(market_code)
        except Exception:
            continue
        try:
            row = build_card_for(symbol, mkt)
        except Exception as e:
            snaps.append(IndexSnapshot(
                symbol=symbol, name=name, market=market_code, error=str(e),
            ))
            continue
        c = row.card
        snaps.append(IndexSnapshot(
            symbol=symbol,
            name=name,
            market=market_code,
            price=c.get("price"),
            change_pct=c.get("change_pct"),
            rsi=c.get("rsi"),
            trend=c.get("trend"),
            score_label=c.get("score_label"),
            error=c.get("error"),
        ))
        # Quiet unused-source warning.
        _ = src
    return snaps


# --- Portfolio risk view ---

def _risk_panel(rows) -> RiskPanel:
    top_weights: list[RiskTopWeight] = []
    for r in rows:
        if r.weight_pct is None or r.holding is None:
            continue
        c = r.card
        top_weights.append(RiskTopWeight(
            symbol=c.get("symbol", ""),
            market=c.get("market_code", ""),
            weight_pct=float(r.weight_pct),
            market_value=float(r.market_value),
            currency_symbol=c.get("currency_symbol", ""),
        ))
    top_weights.sort(key=lambda x: x.weight_pct, reverse=True)
    top_weights = top_weights[:5]

    # Currency exposure normalised through approximate FX so the panel can
    # show a single % split. The note in the schema flags this is approximate.
    totals_in_inr: dict[str, float] = {}
    symbols: dict[str, str] = {}
    for r in rows:
        if r.holding is None or r.card.get("error"):
            continue
        ccy = r.holding.currency
        fx = _ROUGH_FX_TO_INR.get(ccy, 1.0)
        totals_in_inr[ccy] = totals_in_inr.get(ccy, 0.0) + r.market_value * fx
        symbols[ccy] = r.card.get("currency_symbol", "")
    grand = sum(totals_in_inr.values()) or 1.0
    currency_exposure = [
        CurrencyExposure(
            currency=ccy,
            currency_symbol=symbols.get(ccy, ""),
            market_value=v,
            pct_of_total_inr=v / grand * 100.0,
        )
        for ccy, v in sorted(totals_in_inr.items(), key=lambda kv: kv[1], reverse=True)
    ]

    held = [r for r in rows if r.holding and not r.card.get("error")]
    winners = sorted(
        (r for r in held if r.pnl > 0), key=lambda r: r.pnl_pct, reverse=True,
    )[:3]
    losers = sorted(
        (r for r in held if r.pnl < 0), key=lambda r: r.pnl_pct,
    )[:3]

    return RiskPanel(
        top_weights=top_weights,
        currency_exposure=currency_exposure,
        biggest_winners=[card_row_to_out(r, digest_dir=_DIGEST_DIR) for r in winners],
        biggest_losers=[card_row_to_out(r, digest_dir=_DIGEST_DIR) for r in losers],
    )


# --- Signal changes ---

def _signal_changes_panel(rows, current_captured_at: str) -> list[SignalChange]:
    if not current_captured_at:
        return []
    store = get_store()
    out: list[SignalChange] = []
    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        v = c.get("score_value")
        lbl = c.get("score_label")
        sym = c.get("symbol")
        mkt = c.get("market_code")
        if v is None or not lbl or not sym or not mkt:
            continue
        prev = store.signal_previous(sym, mkt, current_captured_at)
        if prev is None:
            continue
        prev_val, prev_lbl, prev_at = prev
        if prev_lbl == lbl:
            continue
        out.append(SignalChange(
            symbol=sym,
            market=mkt,
            previous_label=prev_lbl,
            current_label=lbl,
            previous_value=prev_val,
            current_value=float(v),
            captured_previous_at=prev_at,
        ))
    # Most dramatic moves first.
    out.sort(key=lambda s: abs(s.current_value - s.previous_value), reverse=True)
    return out


# --- Upcoming earnings ---

def _earnings_panel(rows) -> list[EarningsItem]:
    import yfinance as yf

    today = datetime.now().date()
    horizon = today + timedelta(days=30)
    out: list[EarningsItem] = []
    seen: set[tuple[str, str]] = set()

    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        sym = c.get("symbol")
        mkt_code = c.get("market_code")
        if not sym or not mkt_code:
            continue
        key = (sym, mkt_code)
        if key in seen:
            continue
        seen.add(key)

        try:
            market = Market.from_code(mkt_code)
            qualified = market.format_ticker(sym)
            ticker = yf.Ticker(qualified)
            date_value = _earnings_date_from_ticker(ticker)
        except Exception:
            continue

        if date_value is None:
            continue
        days = (date_value - today).days
        if days < 0 or days > 30:
            continue
        out.append(EarningsItem(
            symbol=sym,
            market=mkt_code,
            company=None,
            earnings_date=date_value.isoformat(),
            days_until=days,
        ))
        if date_value > horizon:
            break

    out.sort(key=lambda e: e.days_until)
    return out


def _earnings_date_from_ticker(ticker) -> Optional["date"]:
    """Pull the next earnings date from yfinance, tolerant of its shape changes."""
    from datetime import date as date_t

    cal = None
    try:
        cal = ticker.calendar
    except Exception:
        cal = None

    if isinstance(cal, dict):
        v = cal.get("Earnings Date") or cal.get("earnings_date") or cal.get("Earnings date")
        if isinstance(v, list) and v:
            v = v[0]
        if hasattr(v, "date"):
            return v.date()
        if isinstance(v, date_t):
            return v

    try:
        df = ticker.earnings_dates
    except Exception:
        df = None
    if df is not None and hasattr(df, "index") and len(df) > 0:
        future = [d for d in df.index if hasattr(d, "date") and d.date() >= datetime.now().date()]
        if future:
            return min(future).date()

    return None
