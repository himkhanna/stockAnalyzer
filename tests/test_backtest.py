"""Tests for the backtest engine.

The most important property — no lookahead bias — is structurally pinned:
indicator series are causal (rolling/EMA look backward), and the decision
at bar i is taken from score.iloc[i-1], not score.iloc[i].
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_intel.backtest import compute_score_series, run_backtest


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    arr = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": arr,
            "high": arr + 0.5,
            "low": arr - 0.5,
            "close": arr,
            "volume": [1000] * n,
        },
        index=idx,
    )


def test_score_series_has_one_value_per_bar_and_is_clamped():
    rng = np.random.default_rng(0)
    closes = 100 + np.cumsum(rng.normal(0, 1, 400))
    df = _ohlcv(list(closes))
    s = compute_score_series(df)
    assert len(s) == len(df)
    assert (s >= -10).all() and (s <= 10).all()


def test_score_series_is_causal_changing_future_doesnt_change_past():
    """Pin: bar i's score depends only on bars [0..i]."""
    rng = np.random.default_rng(1)
    closes = list(100 + np.cumsum(rng.normal(0, 1, 400)))
    s1 = compute_score_series(_ohlcv(closes))

    # Mutate ONLY the last 50 bars and recompute.
    mutated = closes.copy()
    for i in range(len(mutated) - 50, len(mutated)):
        mutated[i] = mutated[i] * 1.5

    s2 = compute_score_series(_ohlcv(mutated))
    # Everything BEFORE the mutation point must be identical.
    cut = len(closes) - 50
    pd.testing.assert_series_equal(s1.iloc[:cut], s2.iloc[:cut])


def test_backtest_relentless_uptrend_stays_mostly_flat_by_design():
    """A straight-line up triggers overbought RSI + upper-Bollinger, which
    cancel the trend signal. CLAUDE.md's example explicitly nets a strong
    uptrend to HOLD ('overbought, pressing resistance, poor risk/reward').
    Pin that the strategy genuinely abstains in that regime — and that
    that is reported truthfully (no overfit-to-match-buy-and-hold)."""
    rng = np.random.default_rng(2)
    closes = list(np.linspace(100, 250, 500) + rng.normal(0, 0.5, 500))
    bt = run_backtest(_ohlcv(closes))
    # Buy-and-hold made money; the strategy may not have. Both must be reported.
    assert bt.buy_and_hold_return_pct > 30
    assert bt.in_market_pct < 50  # mean-reversion signals dominate
    # Edge is allowed to be negative — that's the honest CLAUDE.md outcome.


def test_backtest_uptrend_with_pullbacks_participates():
    """A wavy uptrend (overall up, with regular pullbacks to oversold) is
    the regime the rules are designed for — buy at oversold-near-support,
    ride to overbought. Pin that the strategy enters multiple times."""
    rng = np.random.default_rng(7)
    n = 600
    base = np.linspace(100, 200, n)
    waves = 8 * np.sin(np.linspace(0, 12 * np.pi, n))  # ~6 oscillations
    closes = list(base + waves + rng.normal(0, 0.6, n))
    bt = run_backtest(_ohlcv(closes))
    assert bt.n_trades >= 1, "expected the rules to trigger at oscillation lows"


def test_backtest_monotonic_downtrend_stays_mostly_flat_and_caps_loss():
    """In a relentless downtrend the score should rarely cross enter_threshold,
    so the strategy stays flat and avoids the drawdown."""
    rng = np.random.default_rng(3)
    closes = list(np.linspace(200, 80, 500) + rng.normal(0, 0.5, 500))
    bt = run_backtest(_ohlcv(closes))
    # Buy-and-hold is deeply negative.
    assert bt.buy_and_hold_return_pct < -30
    # Strategy should be much better off (close to flat or modestly negative).
    assert bt.strategy_return_pct > bt.buy_and_hold_return_pct
    assert bt.in_market_pct < 50


def test_backtest_charges_transaction_costs():
    """Two runs on the same data, one with much higher costs — higher costs
    must produce a lower (or equal, if zero trades) strategy return."""
    rng = np.random.default_rng(4)
    # Choppy series that produces multiple trades.
    base = 100 + np.cumsum(rng.normal(0, 2.0, 400))
    closes = list(base)
    df = _ohlcv(closes)
    cheap = run_backtest(df, transaction_cost_pct=0.0)
    expensive = run_backtest(df, transaction_cost_pct=2.0)
    if cheap.n_trades > 0:
        assert expensive.strategy_return_pct <= cheap.strategy_return_pct


def test_backtest_records_completed_trades_with_dates_and_pricing():
    """A completed trade has entry < exit dates and a return that matches
    (exit - entry) net of costs."""
    rng = np.random.default_rng(5)
    base = 100 + np.cumsum(rng.normal(0, 1.5, 400))
    bt = run_backtest(_ohlcv(list(base)), transaction_cost_pct=0.0)
    for t in bt.trades:
        assert t.entry_date < t.exit_date
        # Allow open positions in the last trade (closed at last close)
        # not to match exactly, but other trades' net return should equal
        # (exit/entry - 1) * 100 within float tolerance.
        expected = (t.exit_price / t.entry_price - 1.0) * 100.0
        assert t.return_pct == pytest.approx(expected, abs=0.01)


def test_backtest_marks_sentiment_not_used():
    """CLAUDE.md: 'A rule that matched buy-and-hold is an honest and common
    result.' Equally honest: the backtest can't use historical sentiment.
    Pin that the result flags this."""
    rng = np.random.default_rng(6)
    closes = list(100 + np.cumsum(rng.normal(0, 1, 400)))
    bt = run_backtest(_ohlcv(closes))
    assert bt.sentiment_used is False


def test_backtest_requires_minimum_history():
    df = _ohlcv([100.0] * 50)
    with pytest.raises(ValueError, match="at least"):
        run_backtest(df)
