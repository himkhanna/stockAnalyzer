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
from portfolio_intel.scoring import RuleHit, Score, TradeSetup
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


def _score():
    return Score(value=2.5, label="Buy", breakdown={"trend": 2.0, "macd": 1.0, "sentiment": -0.5})


def _setup():
    return TradeSetup(valid=True, entry=200.0, stop=195.0, target=215.0,
                       risk_reward=3.0, note="entry at support, target at resistance.")


def test_user_prompt_contains_every_indicator_value():
    snap = _snap()
    sentiment = SentimentSummary(total=5, positive=3, neutral=1, negative=1,
                                 themes=["earnings"], sample_titles=["Beat", "Upgrade"])
    p = build_user_prompt("AAPL", "US", "$", snap, sentiment, news=[],
                          score=_score(), rules=[], setup=_setup())
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
    p = build_user_prompt("AAPL", "US", "$", snap, sentiment, news=[],
                          score=_score(), rules=[], setup=_setup())
    assert "3 items" in p
    assert "2 pos / 0 neu / 1 neg" in p
    assert "earnings" in p
    assert "Beats EPS" in p


def test_user_prompt_says_no_news_when_empty():
    """CLAUDE.md: when no news source covers a market/ticker, run on
    technicals alone and say so."""
    snap = _snap()
    empty = SentimentSummary(total=0, positive=0, neutral=0, negative=0)
    p = build_user_prompt("RELIANCE", "NSE", "₹", snap, empty, news=[],
                          score=_score(), rules=[], setup=_setup())
    assert "no items found" in p
    assert "RELIANCE.NSE" in p
    assert "₹211.40" in p  # native currency, not $


def test_user_prompt_includes_position_when_given():
    snap = _snap()
    empty = SentimentSummary(total=0, positive=0, neutral=0, negative=0)
    p = build_user_prompt(
        "AAPL", "US", "$", snap, empty, news=[],
        score=_score(), rules=[], setup=_setup(),
        position_note="holding 50 shares at cost basis $182.00",
    )
    assert "Position context" in p
    assert "50 shares" in p


def test_user_prompt_includes_score_and_rules_and_setup():
    """Phase 4: composite score, rule hits, and trade setup are facts
    handed to the model. The model must reason over them, not invent its
    own."""
    snap = _snap()
    empty = SentimentSummary(total=0, positive=0, neutral=0, negative=0)
    score = Score(value=4.0, label="Buy", breakdown={"trend": 2.0, "macd": 1.0, "sentiment": 1.0})
    rules = [
        RuleHit("oversold_at_support", "bullish", "RSI 25 oversold near support."),
        RuleHit("golden_cross", "bullish", "SMA50 crossed above SMA200."),
    ]
    setup = TradeSetup(valid=True, entry=200.0, stop=196.0, target=215.0,
                       risk_reward=3.75, note="entry on a dip to support.")
    p = build_user_prompt("AAPL", "US", "$", snap, empty, news=[],
                          score=score, rules=rules, setup=setup)
    assert "Buy" in p and "+4.0" in p
    assert "oversold_at_support" in p
    assert "golden_cross" in p
    assert "$200.00" in p  # entry
    assert "$215.00" in p  # target
    assert "RR 3.8:1" in p or "RR 3.7:1" in p  # tolerate rounding
    # Disclaimer is still pinned.
    assert "Not advice — your call." in p
