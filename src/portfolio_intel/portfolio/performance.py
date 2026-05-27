"""Performance attribution.

Decomposes total portfolio return over a period into per-holding
contributions, so the user can see which picks actually drove the
number and which dragged on it.

Math (single-period attribution, simple Brinson-style for one bucket):
    contribution_pct = position_weight × position_return_pct
where weights sum to 1 (per currency bucket — we attribute within each
currency since we never silently FX-convert).

Period start price comes from the cached daily-close series. If the
series doesn't reach back far enough (e.g. a position newer than the
period), the row falls back to "since added".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Literal, Optional

import pandas as pd

Period = Literal["1w", "1m", "3m", "6m", "ytd", "1y", "lifetime"]


def period_start(period: Period, today: Optional[date] = None) -> Optional[date]:
    """Return the start date for a named period, or None for 'lifetime'.
    The actual price used will be the first available close >= this date."""
    today = today or date.today()
    if period == "1w":
        return today - timedelta(days=7)
    if period == "1m":
        return today - timedelta(days=30)
    if period == "3m":
        return today - timedelta(days=92)
    if period == "6m":
        return today - timedelta(days=183)
    if period == "ytd":
        return date(today.year, 1, 1)
    if period == "1y":
        return today - timedelta(days=365)
    return None  # lifetime — fall back to cost basis


@dataclass
class AttributionRow:
    ticker: str
    market: str
    currency: str
    currency_symbol: str
    start_price: float
    current_price: float
    return_pct: float          # (cur - start) / start * 100
    weight_pct: float          # position market_value as % of currency bucket
    contribution_pct: float    # return_pct * weight (in pct points of bucket return)
    market_value: float
    period_label: str          # "since added" if we fell back to cost basis
    shares: float


@dataclass
class AttributionBucket:
    currency: str
    currency_symbol: str
    total_return_pct: float    # bucket-level
    total_value: float
    rows: list[AttributionRow]


def attribute(
    inputs: Iterable[tuple],     # (ticker, market, currency, currency_symbol,
                                 #  shares, cost_basis, current_price,
                                 #  market_value, date_added, closes_series)
    *,
    period: Period,
    today: Optional[date] = None,
) -> list[AttributionBucket]:
    """Compute per-bucket attribution.

    `closes_series` is a pandas Series indexed by date (date or
    Timestamp) with daily closes for the position. Pass None if no
    history is available — the row will fall back to cost-basis return.
    """
    today = today or date.today()
    start = period_start(period, today)

    # First pass: compute per-row return + value, group by currency.
    by_currency: dict[str, dict] = {}
    rows_built: list[tuple[str, AttributionRow]] = []

    for (
        ticker, market, currency, currency_symbol,
        shares, cost_basis, current_price, market_value,
        date_added, closes,
    ) in inputs:
        if shares <= 0 or current_price is None or current_price <= 0:
            continue

        start_price, period_label = _resolve_start_price(
            period=period, closes=closes, start=start,
            cost_basis=cost_basis, date_added=date_added, today=today,
        )
        if start_price is None or start_price <= 0:
            continue

        ret_pct = (current_price - start_price) / start_price * 100.0
        row = AttributionRow(
            ticker=ticker,
            market=market,
            currency=currency,
            currency_symbol=currency_symbol,
            start_price=start_price,
            current_price=current_price,
            return_pct=ret_pct,
            weight_pct=0.0,            # filled in below
            contribution_pct=0.0,      # filled in below
            market_value=market_value,
            period_label=period_label,
            shares=shares,
        )
        rows_built.append((currency, row))

        slot = by_currency.setdefault(currency, {
            "currency_symbol": currency_symbol,
            "total_value": 0.0,
        })
        slot["total_value"] += market_value

    # Second pass: weights and contributions.
    bucketed: dict[str, list[AttributionRow]] = {}
    for currency, row in rows_built:
        total = by_currency[currency]["total_value"]
        if total > 0:
            row.weight_pct = row.market_value / total * 100.0
            row.contribution_pct = row.return_pct * (row.weight_pct / 100.0)
        bucketed.setdefault(currency, []).append(row)

    # Build per-bucket aggregates.
    out: list[AttributionBucket] = []
    for currency, rows in bucketed.items():
        rows.sort(key=lambda r: r.contribution_pct, reverse=True)
        out.append(AttributionBucket(
            currency=currency,
            currency_symbol=by_currency[currency]["currency_symbol"],
            total_return_pct=sum(r.contribution_pct for r in rows),
            total_value=by_currency[currency]["total_value"],
            rows=rows,
        ))
    out.sort(key=lambda b: b.currency)
    return out


def _resolve_start_price(
    *,
    period: Period,
    closes: Optional[pd.Series],
    start: Optional[date],
    cost_basis: float,
    date_added: date,
    today: date,
) -> tuple[Optional[float], str]:
    """Pick the price to anchor the period to.

    Priority:
      1. Closes series with a value at/after the requested start → use it
         (or the position's add date, whichever is later).
      2. Lifetime period → cost basis.
      3. Position newer than the period → cost basis with "since added" label.
    """
    if period == "lifetime":
        return float(cost_basis), "lifetime (since added)"

    # The position can't have a return before it was added — clamp.
    effective_start = max(start, date_added) if start else date_added
    fell_back = effective_start != start

    if closes is not None and len(closes) > 0:
        try:
            # Coerce the index to a tz-naive DatetimeIndex of dates, then
            # find the first close on/after effective_start. Wrapped in
            # one try/except so any pandas/numpy edge case (tz-aware
            # index, object-dtype, etc.) falls back cleanly to cost
            # basis instead of 500-ing the endpoint.
            di = pd.to_datetime(closes.index)
            try:
                di = di.tz_localize(None)  # noop if already naive
            except (TypeError, AttributeError):
                pass
            target_ts = pd.Timestamp(effective_start)
            sub = closes[di >= target_ts]
            if len(sub) > 0:
                price = float(sub.iloc[0])
                label = (
                    f"since added ({date_added.isoformat()})"
                    if fell_back else period
                )
                return price, label
        except Exception:
            pass

    # No usable history — fall back to cost basis.
    return float(cost_basis), f"since added ({date_added.isoformat()})"
