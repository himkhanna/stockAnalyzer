"""Convert internal CardRow + per-currency totals into wire schemas."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from portfolio_intel.markets import Market
from portfolio_intel.portfolio.models import Holding
from portfolio_intel.scoring.weights import DEFAULT_WEIGHTS

from .schemas import (
    CardRowOut,
    CurrencyBucketOut,
    DashboardOut,
    HoldingOut,
    TradeSetupOut,
)
from .state import CardRow


def _today_digest_path(symbol: str, market: str, out_dir: Path) -> Path:
    from datetime import date as date_
    return out_dir / date_.today().isoformat() / f"{symbol}.{market}.md"


def card_row_to_out(row: CardRow, *, digest_dir: Path) -> CardRowOut:
    c = row.card
    setup = TradeSetupOut(
        valid=bool(c.get("setup_valid", False)),
        entry=c.get("setup_entry"),
        stop=c.get("setup_stop"),
        target=c.get("setup_target"),
        risk_reward=c.get("setup_rr"),
    )
    h = row.holding
    return CardRowOut(
        symbol=c.get("symbol", ""),
        market=c.get("market_code", ""),
        currency=c.get("currency", ""),
        currency_symbol=c.get("currency_symbol", ""),
        price=c.get("price"),
        change_pct=c.get("change_pct"),
        stale=bool(c.get("stale", False)),
        score_value=c.get("score_value"),
        score_label=c.get("score_label"),
        rsi=c.get("rsi"),
        trend=c.get("trend"),
        sentiment_label=c.get("sentiment_label"),
        sentiment_total=int(c.get("sentiment_total", 0)),
        setup=setup,
        recent_closes=list(c.get("recent_closes") or []),
        shares=h.shares if h else None,
        cost_basis=h.cost_basis if h else None,
        market_value=row.market_value if h else None,
        pnl=row.pnl if h else None,
        pnl_pct=row.pnl_pct if h else None,
        weight_pct=row.weight_pct,
        overweight=row.overweight,
        has_digest=_today_digest_path(
            c.get("symbol", ""), c.get("market_code", ""), digest_dir
        ).exists(),
        error=c.get("error"),
    )


def rows_to_dashboard(rows: list[CardRow], *, loaded_at: str, digest_dir: Path) -> DashboardOut:
    out_rows = [card_row_to_out(r, digest_dir=digest_dir) for r in rows]

    by_ccy: dict[str, dict] = defaultdict(lambda: {"mv": 0.0, "cost": 0.0, "n": 0, "sym": ""})
    for r in rows:
        if not r.holding or r.card.get("error") or r.market_value <= 0:
            continue
        b = by_ccy[r.holding.currency]
        b["mv"] += r.market_value
        b["cost"] += r.cost_total
        b["n"] += 1
        b["sym"] = r.card["currency_symbol"]

    buckets = []
    for ccy, agg in by_ccy.items():
        pnl = agg["mv"] - agg["cost"]
        pnl_pct = (pnl / agg["cost"] * 100.0) if agg["cost"] else 0.0
        buckets.append(CurrencyBucketOut(
            currency=ccy, currency_symbol=agg["sym"],
            market_value=agg["mv"], cost_total=agg["cost"],
            pnl=pnl, pnl_pct=pnl_pct, n_positions=int(agg["n"]),
        ))

    signal_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        lbl = r.card.get("score_label")
        if lbl:
            signal_counts[lbl] += 1

    overweight_count = sum(1 for r in rows if r.overweight)
    winners_count = sum(1 for r in rows if r.holding and r.pnl > 0 and not r.card.get("error"))
    losers_count = sum(1 for r in rows if r.holding and r.pnl < 0 and not r.card.get("error"))

    return DashboardOut(
        rows=out_rows,
        buckets=buckets,
        signal_counts=dict(signal_counts),
        overweight_count=overweight_count,
        winners_count=winners_count,
        losers_count=losers_count,
        loaded_at=loaded_at,
    )


def holding_to_out(h: Holding) -> HoldingOut:
    return HoldingOut(
        ticker=h.ticker, market=h.market_code, shares=h.shares,
        cost_basis=h.cost_basis, currency=h.currency, date_added=h.date_added,
    )
