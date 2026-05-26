"""Portfolio CSV import.

Default format (header required, columns can appear in any order):
    ticker, market, shares, cost_basis, date

- ticker: bare symbol (AAPL, RELIANCE) OR qualified (RELIANCE.NS). If qualified,
  the suffix wins and `market` is ignored.
- market: US | NSE | BSE. Required if ticker is bare.
- shares: number (float ok).
- cost_basis: per-share cost in the market's native currency.
- date: YYYY-MM-DD. Optional; defaults to today.

Returns a list of Holding objects. Bad rows are collected and returned as
errors rather than aborting the whole import — caller decides whether to
proceed.

Broker-export formats (Zerodha, Fidelity, etc.) can be added later by
detecting the header signature and mapping to this canonical shape.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..markets import Market, parse_ticker
from .models import Holding


REQUIRED_COLUMNS = {"ticker", "shares", "cost_basis"}


@dataclass
class RowError:
    row_number: int
    raw: dict
    reason: str


@dataclass
class ImportResult:
    holdings: list[Holding]
    errors: list[RowError]

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_portfolio_csv(rows: Iterable[dict], *, today: date | None = None) -> ImportResult:
    today = today or date.today()
    holdings: list[Holding] = []
    errors: list[RowError] = []

    for i, raw in enumerate(rows, start=2):  # row 1 = header
        try:
            holdings.append(_row_to_holding(raw, today=today))
        except (ValueError, KeyError) as e:
            errors.append(RowError(row_number=i, raw=dict(raw), reason=str(e)))

    return ImportResult(holdings=holdings, errors=errors)


def import_csv_file(
    path: str | Path,
    *,
    today: date | None = None,
    on_resolve: "Callable[[int, int, str, str | None], None] | None" = None,
) -> ImportResult:
    """Read a CSV and return an ImportResult.

    Auto-detects broker formats (ICICI Direct currently). For broker
    formats, every row's ticker is resolved via ISIN/name lookup before
    being handed to the canonical parser. `on_resolve(i, total, key,
    resolved)` lets the CLI / UI render a progress bar during that step.
    """
    from .brokers import detect_broker, translate
    from .ticker_resolver import TickerResolver

    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: CSV has no header row")
        raw_rows = list(reader)

    broker = detect_broker(list(reader.fieldnames))
    if broker is not None:
        translation = translate(
            broker, raw_rows, resolver=TickerResolver(), on_progress=on_resolve,
        )
        result = parse_portfolio_csv(translation.canonical_rows, today=today)
        # Append broker-side unresolved rows as ImportResult errors so the
        # caller surfaces them in the same UI/CLI path.
        for u in translation.unresolved:
            result.errors.append(
                RowError(row_number=-1, raw=u, reason=u.get("reason", "unresolved"))
            )
        return result

    normalized = [_normalize_keys(r) for r in raw_rows]
    missing = REQUIRED_COLUMNS - {_canon(c) for c in reader.fieldnames}
    if missing:
        raise ValueError(
            f"{path}: missing required columns: {sorted(missing)}; "
            f"got {reader.fieldnames}"
        )
    return parse_portfolio_csv(normalized, today=today)


def _canon(s: str) -> str:
    return s.strip().lower().replace(" ", "_")


def _normalize_keys(row: dict) -> dict:
    return {_canon(k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}


def _row_to_holding(raw: dict, *, today: date) -> Holding:
    ticker_raw = raw.get("ticker")
    if not ticker_raw:
        raise ValueError("missing ticker")

    market_flag = raw.get("market") or None
    explicit = Market.from_code(market_flag) if market_flag else None
    symbol, market = parse_ticker(ticker_raw, default_market=explicit)
    if explicit is not None and market is not explicit and market_flag:
        # qualified suffix and an explicit market disagree — let the suffix win silently
        pass

    shares = _required_float(raw, "shares")
    cost_basis = _required_float(raw, "cost_basis")
    if shares <= 0:
        raise ValueError(f"shares must be > 0 (got {shares})")
    if cost_basis < 0:
        raise ValueError(f"cost_basis must be >= 0 (got {cost_basis})")

    date_str = raw.get("date")
    d = date.fromisoformat(date_str) if date_str else today

    return Holding(
        ticker=symbol,
        market_code=market.code,
        shares=shares,
        cost_basis=cost_basis,
        currency=market.currency,
        date_added=d,
    )


def _required_float(raw: dict, key: str) -> float:
    v = raw.get(key)
    if v in (None, ""):
        raise ValueError(f"missing {key}")
    try:
        return float(str(v).replace(",", ""))
    except ValueError as e:
        raise ValueError(f"{key} is not a number: {v!r}") from e
