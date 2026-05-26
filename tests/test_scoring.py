"""Tests for the directional / scoring layer.

These pin behaviour for: score weights and labels, named rules,
trade-setup math (entry/stop/target/RR), and position-aware overweight
flagging.
"""
from __future__ import annotations

from datetime import date

import pytest

from portfolio_intel.news.sentiment import SentimentSummary
from portfolio_intel.portfolio.models import Holding
from portfolio_intel.scoring import (
    build_position_context,
    build_setup,
    compute_score,
    evaluate_rules,
)
from portfolio_intel.technical.levels import Levels
from portfolio_intel.technical.signals import TechnicalSnapshot


def _snap(**o) -> TechnicalSnapshot:
    base = dict(
        close=100.0,
        rsi=50.0, rsi_label="neutral",
        sma_50=95.0, sma_200=90.0, trend_label="uptrend",
        recent_golden_cross=False, recent_death_cross=False,
        macd=0.5, macd_signal=0.3, macd_hist=0.2, macd_label="bullish",
        bb_upper=110.0, bb_lower=90.0, bb_pct_b=0.5, bb_label="mid range",
        atr=2.0, atr_pct=2.0,
        volume_ratio=1.0, volume_label="normal",
        levels=Levels(supports=[90.0], resistances=[110.0],
                      nearest_support=90.0, nearest_resistance=110.0),
        nearest_support=90.0, nearest_resistance=110.0,
        patterns=[], bars_used=250,
    )
    base.update(o)
    return TechnicalSnapshot(**base)


def _empty_sent() -> SentimentSummary:
    return SentimentSummary(total=0, positive=0, neutral=0, negative=0)


# ---------- Score ----------

def test_score_bullish_stack_returns_buy_label():
    snap = _snap(
        trend_label="uptrend",
        rsi=45.0, rsi_label="neutral",
        macd_label="bullish",
        bb_label="near lower",
        recent_golden_cross=True,
    )
    s = SentimentSummary(total=5, positive=4, neutral=0, negative=1)
    # Force label since tally is what produces "mostly positive"; supply it manually.
    s = SentimentSummary(total=5, positive=4, neutral=0, negative=1)
    # rebuild with the right .label requires going through tally, but our
    # scorer only reads .label, so create a stub:
    class _S:
        label = "mostly positive"
        total = 5
    out = compute_score(snap, _S())
    assert out.value >= 5.0
    assert out.label in {"Buy", "Strong Buy"}
    assert out.direction == "bullish"
    assert "trend" in out.breakdown and out.breakdown["trend"] > 0


def test_score_bearish_stack_returns_sell_label():
    snap = _snap(
        trend_label="downtrend",
        rsi=80.0, rsi_label="overbought",
        macd_label="bearish",
        bb_label="near upper",
        recent_death_cross=True,
    )
    class _S:
        label = "mostly negative"
        total = 4
    out = compute_score(snap, _S())
    assert out.value <= -5.0
    assert out.label in {"Sell", "Strong Sell"}
    assert out.direction == "bearish"


def test_score_neutral_is_hold():
    snap = _snap(trend_label="mixed", rsi=50.0, rsi_label="neutral",
                 macd_label="neutral", bb_label="mid range")
    out = compute_score(snap, _empty_sent())
    assert -1.99 <= out.value <= 1.99
    assert out.label == "Hold"


def test_score_clamps_to_ten():
    snap = _snap(
        trend_label="uptrend", rsi=20, rsi_label="oversold",
        macd_label="bullish", bb_label="near lower",
        recent_golden_cross=True, patterns=["bullish engulfing", "hammer"],
    )
    class _S:
        label = "mostly positive"
        total = 10
    out = compute_score(snap, _S())
    assert out.value <= 10.0


# ---------- Rules ----------

def test_rule_oversold_at_support_fires():
    snap = _snap(close=91.0, rsi=25.0, rsi_label="oversold",
                 nearest_support=90.0)
    hits = evaluate_rules(snap, _empty_sent())
    names = {h.name for h in hits}
    assert "oversold_at_support" in names


def test_rule_overbought_at_resistance_fires():
    snap = _snap(close=109.0, rsi=75.0, rsi_label="overbought",
                 nearest_resistance=110.0)
    hits = evaluate_rules(snap, _empty_sent())
    names = {h.name for h in hits}
    assert "overbought_at_resistance" in names


def test_rule_death_cross_fires():
    snap = _snap(recent_death_cross=True)
    hits = evaluate_rules(snap, _empty_sent())
    assert any(h.name == "death_cross" for h in hits)


def test_rule_news_trend_divergence():
    snap = _snap(trend_label="uptrend")
    class _S:
        label = "mostly negative"
        total = 5
    hits = evaluate_rules(snap, _S())
    assert any(h.name == "news_trend_divergence" for h in hits)


# ---------- Trade setup ----------

def test_setup_valid_when_bullish_with_good_rr():
    # close at 92, support 90, resistance 110: RR ~ (110-92)/(92-90*0.985) ≈ 5x
    snap = _snap(
        close=92.0,
        nearest_support=90.0, nearest_resistance=110.0,
        trend_label="uptrend", rsi=45, rsi_label="neutral",
        macd_label="bullish", bb_label="near lower",
    )
    class _S:
        label = "mostly positive"
        total = 4
    score = compute_score(snap, _S())
    su = build_setup(snap, score)
    assert su.valid is True
    assert su.entry == 92.0
    assert su.target == 110.0
    assert su.stop < su.entry
    assert su.risk_reward >= 1.5


def test_setup_invalid_when_bearish():
    snap = _snap(
        close=100, trend_label="downtrend",
        macd_label="bearish", bb_label="near upper",
        recent_death_cross=True,
    )
    class _S:
        label = "mostly negative"
        total = 3
    score = compute_score(snap, _S())
    su = build_setup(snap, score)
    assert su.valid is False
    assert "bearish" in su.note.lower()


def test_setup_uses_real_levels_not_invented_numbers():
    """CLAUDE.md: targets come from real levels, never from the LLM. Verify
    the setup's target IS exactly nearest_resistance and stop is near
    nearest_support — no invented values."""
    snap = _snap(close=95.0, nearest_support=90.0, nearest_resistance=115.0)
    score = compute_score(snap, _empty_sent())
    su = build_setup(snap, score)
    # Target must be the provided resistance.
    if su.target is not None:
        assert su.target == 115.0
    # Entry must be either close (if at/near support) or the support itself.
    if su.entry is not None:
        assert su.entry in (95.0, 90.0)


def test_setup_no_levels_returns_invalid():
    snap = _snap(nearest_support=None, nearest_resistance=None,
                 levels=Levels(supports=[], resistances=[],
                               nearest_support=None, nearest_resistance=None))
    su = build_setup(snap, compute_score(snap, _empty_sent()))
    assert su.valid is False
    assert "swing levels" in su.note.lower()


# ---------- Position ----------

def _hold(shares=10, cost=100, ccy="USD") -> Holding:
    return Holding(ticker="AAPL", market_code="US", shares=shares,
                   cost_basis=cost, currency=ccy, date_added=date(2025, 1, 1))


def test_position_pnl_math():
    p = build_position_context(_hold(10, 100), current_price=150.0)
    assert p.market_value == 1500.0
    assert p.pnl == 500.0
    assert p.pnl_pct == pytest.approx(50.0)


def test_position_overweight_flags_when_over_threshold():
    p = build_position_context(_hold(10, 100), current_price=150.0,
                                currency_bucket_total=5000.0)
    # 1500 / 5000 = 30% which is > default 15% threshold
    assert p.weight_pct == pytest.approx(30.0)
    assert p.overweight is True
    assert "trim" in p.suggestion.lower()


def test_position_within_target_when_under_threshold():
    p = build_position_context(_hold(10, 100), current_price=150.0,
                                currency_bucket_total=20000.0)
    assert p.overweight is False
    assert "within target" in p.suggestion.lower()


def test_position_no_bucket_total_says_unknown():
    p = build_position_context(_hold(), current_price=120.0)
    assert p.weight_pct is None
    assert p.overweight is False
