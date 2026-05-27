"""Tests for candlestick patterns and support/resistance clustering."""
from __future__ import annotations

import pandas as pd

from portfolio_intel.technical.levels import find_levels
from portfolio_intel.technical.patterns import (
    bearish_engulfing,
    bullish_engulfing,
    doji,
    hammer,
)


def _bar(o, h, l, c, v=1000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _df(bars):
    idx = pd.date_range("2024-01-01", periods=len(bars), freq="B")
    return pd.DataFrame(bars, index=idx)


def test_bullish_engulfing_fires():
    # Red day, then a green day whose body engulfs it.
    bars = [
        _bar(102, 103, 100, 101),  # red
        _bar(100, 106, 99, 105),   # green, engulfs prior body
    ]
    df = _df(bars)
    assert bool(bullish_engulfing(df).iloc[-1]) is True
    assert bool(bearish_engulfing(df).iloc[-1]) is False


def test_bearish_engulfing_fires():
    bars = [
        _bar(100, 103, 99, 102),   # green
        _bar(103, 104, 98, 99),    # red, engulfs prior body
    ]
    df = _df(bars)
    assert bool(bearish_engulfing(df).iloc[-1]) is True


def test_doji_when_open_equals_close():
    bars = [_bar(100, 105, 95, 100)]
    df = _df(bars)
    assert bool(doji(df).iloc[-1]) is True


def test_doji_false_for_strong_body():
    bars = [_bar(100, 102, 99, 101.5)]  # body 1.5, span 3 -> 50%, well above 10%
    df = _df(bars)
    assert bool(doji(df).iloc[-1]) is False


def test_hammer_long_lower_wick():
    # Body 100->101 (1.0), lower wick 100 - 92 = 8, upper wick 101 -> 101.2 ~ tiny.
    bars = [_bar(100, 101.2, 92, 101)]
    df = _df(bars)
    assert bool(hammer(df).iloc[-1]) is True


def test_patterns_handle_zero_range_bars_without_raising():
    """Halted / no-trade bars can have high == low, producing a 0 span. The
    pattern functions must return a regular boolean Series with False there,
    not propagate pd.NA (which would make bool(...) raise downstream)."""
    bars = [
        _bar(100, 100, 100, 100),     # zero range
        _bar(100, 102, 99, 101),
        _bar(100, 100, 100, 100),     # zero range again
    ]
    df = _df(bars)
    for fn in (bullish_engulfing, bearish_engulfing, doji, hammer):
        out = fn(df)
        assert out.dtype == bool
        for v in out:
            assert isinstance(bool(v), bool)  # must not raise


def test_levels_cluster_nearby_highs_and_pick_nearest():
    # Build a series with two clear resistance shelves around 110 and 120,
    # and supports around 90 and 100, with current close = 105.
    seq = [
        100, 95, 100, 110, 105, 100, 110.5, 105, 100,  # res ~110, sup ~95-100
        90, 95, 110, 120, 115, 110, 120.2, 115, 110,   # res ~120, sup ~90
        105,  # current
    ]
    # Need enough bars for the window=5 swing detector to find points.
    closes = seq + seq + [105]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1] * len(closes),
        }
    )
    levels = find_levels(df, window=2, cluster_pct=0.02)
    assert levels.nearest_support is not None
    assert levels.nearest_resistance is not None
    assert levels.nearest_support < 105 < levels.nearest_resistance
