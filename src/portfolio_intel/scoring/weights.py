"""Scoring weights.

CLAUDE.md: "Weights must be config-driven and easily adjustable."

Default weights sum so the maximum theoretical score is +10 and minimum
-10. Adjust freely — these are an opinion, not a discovery. Resist the
temptation to tune them against historical returns (lookahead bias); the
backtest layer in Phase 5 is for measuring performance, not for
overfitting weights.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Weights:
    # Technical (max +/- 6)
    trend: float = 2.0           # uptrend +trend, downtrend -trend, else 0
    rsi: float = 1.0             # oversold +rsi, overbought -rsi
    macd: float = 1.0            # bullish +macd, bearish -macd
    bollinger: float = 1.0       # near lower +bb, near upper -bb
    cross: float = 1.0           # recent golden +cross, recent death -cross

    # Sentiment (max +/- 2)
    sentiment: float = 2.0       # mostly positive +s, mostly negative -s

    # Patterns (max +/- 1; doji contributes 0)
    pattern: float = 1.0

    # Used by rules.py / setup.py — not added into the score.
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    near_level_pct: float = 0.03         # within 3% counts as 'near'
    overweight_pct: float = 15.0         # holding > 15% of portfolio = overweight
    min_risk_reward: float = 1.5         # below this, a setup is 'not worth it'
    setup_eligible_score: float = 2.0    # need at least Buy-leaning to call it a setup

    # For score -> label mapping.
    label_thresholds: tuple[tuple[float, str], ...] = field(
        default_factory=lambda: (
            (6.0, "Strong Buy"),
            (2.0, "Buy"),
            (-1.99, "Hold"),
            (-5.99, "Sell"),
            (float("-inf"), "Strong Sell"),
        )
    )


DEFAULT_WEIGHTS = Weights()
