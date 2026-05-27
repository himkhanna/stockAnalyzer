"""Unit tests for the math layer.

These tests use synthetic OHLCV with known properties so we can assert exact
or near-exact values. A wrong indicator here would propagate through every
later layer (scoring, LLM prompt, backtest) — so this is the layer to nail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio_intel.technical import indicators as ind
from portfolio_intel.technical.signals import compute_snapshot


def _df_from_close(close_values: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame where O=H=L=C and volume=1000."""
    n = len(close_values)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": close_values,
            "high": close_values,
            "low": close_values,
            "close": close_values,
            "volume": [1000] * n,
        },
        index=idx,
    )


def test_sma_simple():
    df = _df_from_close([1, 2, 3, 4, 5])
    s = ind.sma(df["close"], 3)
    assert s.iloc[2] == pytest.approx(2.0)
    assert s.iloc[3] == pytest.approx(3.0)
    assert s.iloc[4] == pytest.approx(4.0)
    assert pd.isna(s.iloc[0])


def test_rsi_constant_series_is_undefined_then_100_when_only_gains():
    """RSI of a monotonic series should be 100 (all gains, no losses)."""
    df = _df_from_close(list(range(1, 30)))
    r = ind.rsi(df["close"], 14)
    assert r.iloc[-1] == pytest.approx(100.0)


def test_rsi_monotonic_down_is_zero():
    df = _df_from_close(list(range(30, 1, -1)))
    r = ind.rsi(df["close"], 14)
    assert r.iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_rsi_range_is_bounded():
    rng = np.random.default_rng(seed=42)
    closes = 100 + np.cumsum(rng.normal(0, 1, 200))
    r = ind.rsi(pd.Series(closes), 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_macd_signal_lags_macd():
    df = _df_from_close(list(np.linspace(100, 200, 100)))
    m = ind.macd(df["close"])
    # On a steadily rising series MACD line is positive and signal is below it.
    assert m["macd"].iloc[-1] > 0
    assert m["macd"].iloc[-1] > m["signal"].iloc[-1]
    assert m["hist"].iloc[-1] == pytest.approx(m["macd"].iloc[-1] - m["signal"].iloc[-1])


def test_bollinger_bands_contain_price_for_calm_series():
    """For a low-noise series the bands should be tight around price."""
    closes = [100 + 0.1 * np.sin(i / 5) for i in range(50)]
    bb = ind.bollinger(pd.Series(closes), length=20)
    last = bb.iloc[-1]
    assert last["lower"] < closes[-1] < last["upper"]
    assert 0.0 <= last["pct_b"] <= 1.0


def test_atr_increases_with_volatility():
    n = 50
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    calm = pd.DataFrame(
        {"open": [100] * n, "high": [101] * n, "low": [99] * n, "close": [100] * n, "volume": [1] * n},
        index=idx,
    )
    wild = pd.DataFrame(
        {"open": [100] * n, "high": [110] * n, "low": [90] * n, "close": [100] * n, "volume": [1] * n},
        index=idx,
    )
    assert ind.atr(wild).iloc[-1] > ind.atr(calm).iloc[-1] * 5


def test_golden_cross_fires_when_fast_crosses_above_slow():
    # Long downtrend then sustained recovery: SMA50 dips below SMA200, then
    # crosses back up. That cross is the golden-cross event.
    down = list(np.linspace(200, 100, 250))
    up = list(np.linspace(100, 250, 250))
    s = pd.Series(down + up)
    assert ind.golden_cross(s, fast=50, slow=200).sum() >= 1


def test_death_cross_fires_when_fast_crosses_below_slow():
    up = list(np.linspace(100, 250, 250))
    down = list(np.linspace(250, 80, 250))
    s = pd.Series(up + down)
    assert ind.death_cross(s, fast=50, slow=200).sum() >= 1


def test_snapshot_requires_minimum_bars():
    df = _df_from_close([100.0] * 10)
    with pytest.raises(ValueError, match="at least 20 bars"):
        compute_snapshot(df)


def test_snapshot_runs_on_rising_series_and_labels_overbought():
    rng = np.random.default_rng(seed=0)
    # Strong steady uptrend with small noise -> RSI should pin near overbought.
    base = np.linspace(100, 200, 250)
    noise = rng.normal(0, 0.5, 250)
    closes = list(base + noise)
    n = len(closes)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * n,
        },
        index=idx,
    )
    snap = compute_snapshot(df)
    assert snap.trend_label == "uptrend"
    assert snap.rsi is not None and snap.rsi > 60
    assert snap.macd_label in {"bullish", "neutral"}
    assert snap.bars_used == 250
