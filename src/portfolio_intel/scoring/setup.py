"""Trade setup generator.

CLAUDE.md, verbatim:
  "Trade setup generator: entry / stop (nearest support) / target (nearest
   resistance) / risk-reward ratio. Targets come from real levels, NEVER
   from the LLM."

We only produce long setups — this is an investment tool, not a shorting
platform. For bearish reads we mark the setup invalid with a note ("trend
is down; no long setup"); the user can decide if they want to exit.

Entry logic:
- If price is already at/near support: entry = current close (taking the
  setup as it presents).
- Otherwise: entry = nearest support (the better-priced wait-for-dip
  entry, matching CLAUDE.md's "only on a dip" example).

Stop: a small buffer below the support being used as the floor.
Target: the next resistance above the entry.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..technical.signals import TechnicalSnapshot
from .score import Score
from .weights import DEFAULT_WEIGHTS, Weights


@dataclass(frozen=True)
class TradeSetup:
    valid: bool
    entry: float | None
    stop: float | None
    target: float | None
    risk_reward: float | None
    note: str
    direction: str = "long"


def build_setup(
    snap: TechnicalSnapshot,
    score: Score,
    *,
    weights: Weights = DEFAULT_WEIGHTS,
) -> TradeSetup:
    nearest_sup = snap.nearest_support
    nearest_res = snap.nearest_resistance
    close = snap.close

    # No trade if we have nothing to anchor stops or targets to.
    if nearest_sup is None or nearest_res is None:
        return TradeSetup(
            valid=False, entry=None, stop=None, target=None, risk_reward=None,
            note="not enough swing levels to anchor a setup; need more history.",
        )

    # Decide entry. If price is already near support, take it; otherwise wait.
    near_pct = weights.near_level_pct
    if close <= nearest_sup * (1 + near_pct):
        entry = close
        entry_note = f"current price ({_money(close, snap)}) is already at/near support"
    else:
        entry = nearest_sup
        entry_note = f"better entry on a pullback to {_money(entry, snap)}"

    stop = entry * (1 - 0.5 * near_pct) if entry == close else nearest_sup * (1 - near_pct)
    target = nearest_res
    risk = entry - stop
    reward = target - entry

    if risk <= 0 or reward <= 0:
        return TradeSetup(
            valid=False, entry=entry, stop=stop, target=target, risk_reward=None,
            note="entry/stop/target collapse — likely price is above the nearest resistance.",
        )

    rr = reward / risk

    bearish_block = (
        score.direction == "bearish"
        or (snap.recent_death_cross and not snap.recent_golden_cross)
    )
    poor_rr = rr < weights.min_risk_reward
    weak_score = score.value < weights.setup_eligible_score

    if bearish_block:
        note = (
            f"trend is bearish (score {score.value:+.1f}); a long setup is unfavorable. "
            f"Reference levels: entry {_money(entry, snap)} / stop {_money(stop, snap)} "
            f"/ target {_money(target, snap)} (RR {rr:.1f}:1). Wait for stabilization."
        )
        return TradeSetup(
            valid=False, entry=entry, stop=stop, target=target,
            risk_reward=round(rr, 2), note=note,
        )

    if weak_score and poor_rr:
        note = (
            f"score is neutral ({score.value:+.1f}) and RR is thin ({rr:.1f}:1 below "
            f"{weights.min_risk_reward}:1). {entry_note}; only act on a clearer trigger."
        )
        return TradeSetup(
            valid=False, entry=entry, stop=stop, target=target,
            risk_reward=round(rr, 2), note=note,
        )

    if poor_rr:
        note = (
            f"RR is thin ({rr:.1f}:1 vs minimum {weights.min_risk_reward}:1). "
            f"{entry_note}; setup is technically there but the math is weak."
        )
        return TradeSetup(
            valid=False, entry=entry, stop=stop, target=target,
            risk_reward=round(rr, 2), note=note,
        )

    note = (
        f"{entry_note}. Stop {_money(stop, snap)} (just below support), "
        f"target {_money(target, snap)} (nearest resistance). RR {rr:.1f}:1."
    )
    return TradeSetup(
        valid=True, entry=entry, stop=stop, target=target,
        risk_reward=round(rr, 2), note=note,
    )


def _money(v: float, snap: TechnicalSnapshot) -> str:
    # We don't have the currency symbol here without threading it; use bare
    # number. Callers that render this build their own currency-prefixed
    # version.
    return f"{v:,.2f}"
