"""Tests for the synthesis prompt.

The prompt is the strongest lever on output quality and on whether the model
respects CLAUDE.md's hard constraints. These tests pin the structural
invariants — what facts are present, what guardrails appear in the system
message — so we notice if a future edit weakens them.
"""
from __future__ import annotations

from portfolio_intel.data.models import NewsItem
from portfolio_intel.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from portfolio_intel.news.sentiment import SentimentSummary
from portfolio_intel.technical.levels import Levels
from portfolio_intel.technical.signals import TechnicalSnapshot


def _snap(**overrides) -> TechnicalSnapshot:
    base = dict(
        close=211.40,
        rsi=68.0, rsi_label="neutral",
        sma_50=200.0, sma_200=185.0, trend_label="uptrend",
        recent_golden_cross=False, recent_death_cross=False,
        macd=1.5, macd_signal=1.2, macd_hist=0.3, macd_label="bullish",
        bb_upper=215.0, bb_lower=195.0, bb_pct_b=0.82, bb_label="near upper",
        atr=3.2, atr_pct=1.5,
        volume_ratio=1.1, volume_label="normal",
        levels=Levels(supports=[195.0, 200.0], resistances=[215.0, 225.0],
                      nearest_support=200.0, nearest_resistance=215.0),
        nearest_support=200.0, nearest_resistance=215.0,
        patterns=[],
        bars_used=250,
    )
    base.update(overrides)
    return TechnicalSnapshot(**base)


def test_system_prompt_enforces_hard_constraints():
    sp = SYSTEM_PROMPT.lower()
    # Each item below is a CLAUDE.md hard constraint encoded in the prompt.
    assert "do not invent" in sp
    assert "Not advice — your call." in SYSTEM_PROMPT  # exact phrase, with em-dash
    assert "hedged" in sp
    assert "no hype" in sp or "hype" in sp
    assert "no confidence percentages" in sp


def test_user_prompt_contains_every_indicator_value():
    snap = _snap()
    sentiment = SentimentSummary(total=5, positive=3, neutral=1, negative=1,
                                 themes=["earnings"], sample_titles=["Beat", "Upgrade"])
    p = build_user_prompt("AAPL", "US", "$", snap, sentiment, news=[])
    assert "AAPL.US" in p
    assert "$211.40" in p
    assert "RSI(14): 68.00" in p
    assert "SMA50" in p and "SMA200" in p
    assert "uptrend" in p
    assert "MACD" in p and "1.500" in p
    assert "Bollinger" in p
    assert "ATR" in p
    assert "$200.00" in p  # nearest support
    assert "$215.00" in p  # nearest resistance
    # The closing instruction reminds the model of the disclaimer.
    assert "Not advice — your call." in p


def test_user_prompt_renders_news_when_present():
    snap = _snap()
    sentiment = SentimentSummary(total=3, positive=2, neutral=0, negative=1,
                                 themes=["earnings", "analyst"],
                                 sample_titles=["Beats EPS", "Analyst upgrade", "Probe"])
    p = build_user_prompt("AAPL", "US", "$", snap, sentiment, news=[])
    assert "3 items" in p
    assert "2 pos / 0 neu / 1 neg" in p
    assert "earnings" in p
    assert "Beats EPS" in p


def test_user_prompt_says_no_news_when_empty():
    """CLAUDE.md: when no news source covers a market/ticker, run on
    technicals alone and say so."""
    snap = _snap()
    empty = SentimentSummary(total=0, positive=0, neutral=0, negative=0)
    p = build_user_prompt("RELIANCE", "NSE", "₹", snap, empty, news=[])
    assert "no items found" in p
    assert "RELIANCE.NSE" in p
    assert "₹211.40" in p  # native currency, not $


def test_user_prompt_includes_position_when_given():
    snap = _snap()
    empty = SentimentSummary(total=0, positive=0, neutral=0, negative=0)
    p = build_user_prompt(
        "AAPL", "US", "$", snap, empty, news=[],
        position_note="holding 50 shares at cost basis $182.00",
    )
    assert "Position context" in p
    assert "50 shares" in p
