"""Composite directional score.

Reads a TechnicalSnapshot + SentimentSummary, returns a Score with:
- value in [-10, +10] (clamped)
- label (Strong Buy/Buy/Hold/Sell/Strong Sell)
- breakdown: which signals contributed what (transparency matters more
  than the number itself)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..news.sentiment import SentimentSummary
from ..technical.signals import TechnicalSnapshot
from .weights import DEFAULT_WEIGHTS, Weights


@dataclass(frozen=True)
class Score:
    value: float
    label: str
    breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def direction(self) -> str:
        """Coarse direction for downstream logic (rules / setup)."""
        if self.value >= 2.0:
            return "bullish"
        if self.value <= -2.0:
            return "bearish"
        return "neutral"


def compute_score(
    snap: TechnicalSnapshot,
    sentiment: SentimentSummary,
    *,
    weights: Weights = DEFAULT_WEIGHTS,
) -> Score:
    b: dict[str, float] = {}

    # Trend
    if snap.trend_label == "uptrend":
        b["trend"] = +weights.trend
    elif snap.trend_label == "downtrend":
        b["trend"] = -weights.trend

    # RSI: oversold is mean-reversion-positive, overbought is risk
    if snap.rsi is not None:
        if snap.rsi <= weights.rsi_oversold:
            b["rsi"] = +weights.rsi
        elif snap.rsi >= weights.rsi_overbought:
            b["rsi"] = -weights.rsi

    # MACD
    if snap.macd_label == "bullish":
        b["macd"] = +weights.macd
    elif snap.macd_label == "bearish":
        b["macd"] = -weights.macd

    # Bollinger position
    if snap.bb_label == "near lower":
        b["bollinger"] = +weights.bollinger
    elif snap.bb_label == "near upper":
        b["bollinger"] = -weights.bollinger

    # Recent SMA cross — structural
    if snap.recent_golden_cross:
        b["cross"] = +weights.cross
    elif snap.recent_death_cross:
        b["cross"] = -weights.cross

    # Sentiment
    if sentiment.label == "mostly positive":
        b["sentiment"] = +weights.sentiment
    elif sentiment.label == "mostly negative":
        b["sentiment"] = -weights.sentiment

    # Candlestick patterns on the last bar
    pat_score = 0.0
    for p in snap.patterns:
        if p in ("bullish engulfing", "hammer"):
            pat_score += weights.pattern
        elif p == "bearish engulfing":
            pat_score -= weights.pattern
        # doji is intentionally neutral
    if pat_score:
        # Cap so multiple patterns don't dominate
        b["pattern"] = max(-weights.pattern, min(weights.pattern, pat_score))

    raw = sum(b.values())
    value = max(-10.0, min(10.0, raw))
    label = _label_for(value, weights)
    return Score(value=round(value, 2), label=label, breakdown=b)


def _label_for(value: float, weights: Weights) -> str:
    for threshold, name in weights.label_thresholds:
        if value >= threshold:
            return name
    return weights.label_thresholds[-1][1]
