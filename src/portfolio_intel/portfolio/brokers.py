"""Broker-specific CSV format detection and translation.

Each broker has its own column names and ticker conventions. This module
detects the format from the header signature and converts rows to our
canonical shape ({ticker, market, shares, cost_basis, date}) that the
existing import pipeline already understands.

Currently supported:
- ICICI Direct ("PortFolioEqtSummary" export): broker uses internal short
  codes (EXIIND, GABIND, ...); we resolve via the ISIN column to NSE.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from .ticker_resolver import TickerResolver


ICICI_DIRECT_HEADERS = {
    "stock symbol",
    "company name",
    "isin code",
    "qty",
    "average cost price",
}


@dataclass
class BrokerTranslation:
    name: str                           # human-readable broker name
    canonical_rows: list[dict]          # rows in canonical {ticker,market,shares,cost_basis,date} shape
    unresolved: list[dict]              # rows we couldn't resolve a ticker for; for the UI to surface


def detect_broker(headers: list[str]) -> Optional[str]:
    """Return the broker key (e.g. 'icici_direct') or None if no broker
    format is recognized. Canonical format is the fallback."""
    if not headers:
        return None
    h = {(c or "").strip().lower() for c in headers}
    if ICICI_DIRECT_HEADERS.issubset(h):
        return "icici_direct"
    return None


def translate(
    broker_key: str,
    rows: list[dict],
    *,
    resolver: Optional[TickerResolver] = None,
    on_progress: Optional[Callable[[int, int, str, Optional[str]], None]] = None,
) -> BrokerTranslation:
    """Convert broker-native rows to canonical rows. Raises ValueError for
    an unknown broker key.

    `on_progress(i, total, key, resolved_or_none)` fires per row so a CLI
    progress bar or UI spinner can render the ISIN-resolution loop.
    """
    if broker_key == "icici_direct":
        return _translate_icici_direct(rows, resolver=resolver, on_progress=on_progress)
    raise ValueError(f"unknown broker format: {broker_key}")


def _translate_icici_direct(
    rows: list[dict],
    *,
    resolver: Optional[TickerResolver],
    on_progress: Optional[Callable[[int, int, str, Optional[str]], None]],
) -> BrokerTranslation:
    resolver = resolver or TickerResolver()
    canonical: list[dict] = []
    unresolved: list[dict] = []

    # Normalize keys to lowercase so the lookup is forgiving.
    normalized = [{(k or "").strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()} for r in rows]

    total = len(normalized)
    for i, raw in enumerate(normalized, start=1):
        # Skip blank/trailing rows.
        if not any(raw.values()):
            continue
        isin = (raw.get("isin code") or "").upper()
        name = raw.get("company name") or ""
        broker_sym = raw.get("stock symbol") or ""
        qty = raw.get("qty") or ""
        avg = raw.get("average cost price") or ""

        if not (isin or name):
            unresolved.append({"reason": "missing ISIN and name", "raw": raw})
            if on_progress:
                on_progress(i, total, broker_sym or name, None)
            continue

        resolution = resolver.resolve(isin=isin, name=name, fallback=broker_sym)
        if on_progress:
            on_progress(i, total, broker_sym or name, resolution.qualified if resolution else None)

        if resolution is None:
            unresolved.append({
                "reason": "could not resolve ISIN/name to an NSE ticker",
                "isin": isin,
                "name": name,
                "broker_symbol": broker_sym,
                "raw": raw,
            })
            continue

        canonical.append({
            "ticker": resolution.qualified,        # qualified form so parse_ticker honours .NS
            "market": "NSE",
            "shares": qty,
            "cost_basis": avg,
            # No date in this export; canonical parser defaults to today.
        })

    return BrokerTranslation(
        name="ICICI Direct",
        canonical_rows=canonical,
        unresolved=unresolved,
    )
