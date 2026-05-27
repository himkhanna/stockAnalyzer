"""Scan a per-market universe through the existing scoring engine and
return the top-rated non-portfolio names.

Honest framing: this is information about how the deterministic scoring
engine rates a curated list — it is NOT a 'buy these stocks' service.
The output ranks names by the same composite score used elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from ..markets import Market
from .universes import sector_for, universe_for


@dataclass
class DiscoveredRow:
    """A single discovery hit. Mirrors the dashboard CardRow shape but
    only the fields the UI surfaces — keeps the payload light when N
    universes get scanned at once."""
    symbol: str
    market_code: str
    currency_symbol: str
    price: Optional[float]
    change_pct: Optional[float]
    score_value: Optional[float]
    score_label: Optional[str]
    rsi: Optional[float]
    trend: Optional[str]
    sentiment_label: Optional[str]
    sector: str
    rule_count: int
    rule_names: list[str]
    error: Optional[str] = None


def scan_universe(
    market: Market,
    *,
    exclude: Iterable[tuple[str, str]],
    build_card: Callable[[str, Market], object],
    min_score: float = 2.0,
    limit: int = 10,
) -> list[DiscoveredRow]:
    """Scan a market's universe, drop excluded names, return rows with
    score >= min_score ordered by score desc.

    `exclude` is an iterable of (symbol, market_code) tuples — typically
    the user's existing portfolio. Matching is case-insensitive.

    `build_card` is dependency-injected so this stays testable; the API
    layer wires it to state.build_card_for which carries the same cache
    as the rest of the app.
    """
    exclude_set = {(s.upper(), m.upper()) for s, m in exclude}
    tickers = universe_for(market)
    out: list[DiscoveredRow] = []
    for sym in tickers:
        if (sym.upper(), market.code) in exclude_set:
            continue
        try:
            row = build_card(sym, market)  # CardRow
        except Exception as e:
            out.append(DiscoveredRow(
                symbol=sym, market_code=market.code,
                currency_symbol=market.currency_symbol,
                price=None, change_pct=None,
                score_value=None, score_label=None,
                rsi=None, trend=None, sentiment_label=None,
                sector=sector_for(sym, market.code),
                rule_count=0, rule_names=[],
                error=str(e)[:120],
            ))
            continue

        # CardRow is the dataclass from state.py — duck-type into its card dict.
        card = getattr(row, "card", {}) or {}
        if card.get("error"):
            continue
        v = card.get("score_value")
        if v is None or float(v) < min_score:
            continue

        out.append(DiscoveredRow(
            symbol=card.get("symbol", sym),
            market_code=card.get("market_code", market.code),
            currency_symbol=market.currency_symbol,
            price=card.get("price"),
            change_pct=card.get("change_pct"),
            score_value=float(v),
            score_label=card.get("score_label"),
            rsi=card.get("rsi"),
            trend=card.get("trend"),
            sentiment_label=card.get("sentiment_label"),
            sector=sector_for(card.get("symbol", sym), market.code),
            rule_count=int(card.get("rule_count", 0)),
            rule_names=list(card.get("rule_names") or [])[:3],
        ))

    out.sort(key=lambda r: r.score_value or 0.0, reverse=True)
    return out[:limit]
