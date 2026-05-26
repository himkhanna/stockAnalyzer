"""Explicit threshold rules.

Each rule is a named, transparent trigger. CLAUDE.md's example:
'RSI < 30 AND price near support -> buy signal'. We expose all triggered
rules to the user (and to the LLM as context) so the read isn't a black box.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..news.sentiment import SentimentSummary
from ..technical.signals import TechnicalSnapshot
from .weights import DEFAULT_WEIGHTS, Weights


@dataclass(frozen=True)
class RuleHit:
    name: str
    direction: str  # "bullish" | "bearish" | "caution"
    note: str


def _near(price: float, level: float | None, pct: float) -> bool:
    if level is None or level == 0:
        return False
    return abs(price - level) / level <= pct


def evaluate_rules(
    snap: TechnicalSnapshot,
    sentiment: SentimentSummary,
    *,
    weights: Weights = DEFAULT_WEIGHTS,
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    near_pct = weights.near_level_pct

    # --- Mean-reversion / overbought ---
    if snap.rsi is not None and snap.rsi <= weights.rsi_oversold and _near(snap.close, snap.nearest_support, near_pct):
        hits.append(RuleHit(
            "oversold_at_support", "bullish",
            f"RSI {snap.rsi:.0f} oversold while price is within {near_pct*100:.0f}% of support — classic mean-reversion setup.",
        ))
    if snap.rsi is not None and snap.rsi >= weights.rsi_overbought and _near(snap.close, snap.nearest_resistance, near_pct):
        hits.append(RuleHit(
            "overbought_at_resistance", "caution",
            f"RSI {snap.rsi:.0f} overbought while price is pressing resistance — poor risk/reward to add here.",
        ))

    # --- Trend structure ---
    if snap.recent_golden_cross:
        hits.append(RuleHit(
            "golden_cross", "bullish",
            "SMA50 crossed above SMA200 — bullish structural shift.",
        ))
    if snap.recent_death_cross:
        hits.append(RuleHit(
            "death_cross", "bearish",
            "SMA50 crossed below SMA200 — bearish structural shift; consider reducing exposure.",
        ))

    # --- Volatility extremes ---
    if snap.bb_label == "near lower" and snap.macd_label == "bullish":
        hits.append(RuleHit(
            "bb_lower_macd_turn", "bullish",
            "Price near lower Bollinger band with MACD turning up — possible bounce setup.",
        ))
    if snap.bb_label == "near upper" and snap.macd_label == "bearish":
        hits.append(RuleHit(
            "bb_upper_macd_turn", "bearish",
            "Price near upper Bollinger band with MACD rolling over — momentum fading at the top.",
        ))

    # --- News + technicals divergence ---
    if sentiment.label == "mostly negative" and snap.trend_label == "uptrend":
        hits.append(RuleHit(
            "news_trend_divergence", "caution",
            "Uptrend continues despite mostly negative news — watch for a catch-down.",
        ))
    if sentiment.label == "mostly positive" and snap.trend_label == "downtrend":
        hits.append(RuleHit(
            "news_trend_divergence", "caution",
            "Positive news against a downtrend — rallies into downtrends often fail.",
        ))

    # --- Candlestick + level ---
    if ("hammer" in snap.patterns or "bullish engulfing" in snap.patterns) and _near(
        snap.close, snap.nearest_support, near_pct
    ):
        hits.append(RuleHit(
            "reversal_at_support", "bullish",
            f"Bullish reversal pattern ({', '.join(snap.patterns)}) at support — classic entry signal.",
        ))
    if "bearish engulfing" in snap.patterns and _near(snap.close, snap.nearest_resistance, near_pct):
        hits.append(RuleHit(
            "rejection_at_resistance", "bearish",
            "Bearish engulfing at resistance — signals rejection.",
        ))

    return hits
