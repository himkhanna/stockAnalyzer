"""Position-aware logic.

CLAUDE.md: "flag overweight positions, suggest rebalancing. (This is sound
directional logic independent of prediction — prioritize it.)"

Portfolio weight = this holding's market value / total portfolio market
value, both measured in the holding's native currency. We do NOT convert
across currencies — CLAUDE.md is explicit on this. The 'total' passed in
must be denominated in the same currency as the holding.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..portfolio.models import Holding
from .weights import DEFAULT_WEIGHTS, Weights


@dataclass(frozen=True)
class PositionContext:
    shares: float
    cost_basis: float
    market_value: float
    pnl: float
    pnl_pct: float
    weight_pct: float | None      # share of currency-bucket total (None if not supplied)
    overweight: bool
    suggestion: str               # human-readable next-action hint


def build_position_context(
    holding: Holding,
    current_price: float,
    *,
    currency_bucket_total: float | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
) -> PositionContext:
    shares = holding.shares
    cost_basis = holding.cost_basis
    cost_total = cost_basis * shares
    mv = current_price * shares
    pnl = mv - cost_total
    pnl_pct = (pnl / cost_total * 100.0) if cost_total else 0.0

    weight: float | None = None
    overweight = False
    if currency_bucket_total and currency_bucket_total > 0:
        weight = mv / currency_bucket_total * 100.0
        overweight = weight > weights.overweight_pct

    if overweight and weight is not None:
        excess_pct = weight - weights.overweight_pct
        excess_value = excess_pct / 100.0 * currency_bucket_total
        excess_shares = max(0.0, excess_value / current_price)
        suggestion = (
            f"position is {weight:.1f}% of {holding.currency} portfolio "
            f"(target ≤ {weights.overweight_pct:.0f}%); "
            f"trimming ~{excess_shares:.0f} shares would rebalance."
        )
    elif weight is not None:
        suggestion = f"position is {weight:.1f}% of {holding.currency} portfolio — within target."
    else:
        suggestion = "portfolio weight unknown (only single holding analyzed)."

    return PositionContext(
        shares=shares,
        cost_basis=cost_basis,
        market_value=mv,
        pnl=pnl,
        pnl_pct=pnl_pct,
        weight_pct=weight,
        overweight=overweight,
        suggestion=suggestion,
    )
