"""Candlestick pattern detection.

CLAUDE.md calls out engulfing, doji, and hammer. We implement those three
directly — they're simple OHLC arithmetic. If a fuller catalog is ever
needed, TA-Lib is the standard library to plug in.

Each function returns a boolean Series the same length as `df`. Bars where
the result is undefined (e.g. zero-range bars, or the first bar for
two-bar patterns) are False — never NA — so callers can `.iloc[-1]` into
them without `bool(NA)` raising.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _as_bool(s: pd.Series) -> pd.Series:
    return s.fillna(False).astype(bool)


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """A red candle followed by a green candle whose body engulfs the prior body."""
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_red = prev_c < prev_o
    curr_green = c > o
    engulfs = (o <= prev_c) & (c >= prev_o)
    return _as_bool(prev_red & curr_green & engulfs)


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_green = prev_c > prev_o
    curr_red = c < o
    engulfs = (o >= prev_c) & (c <= prev_o)
    return _as_bool(prev_green & curr_red & engulfs)


def doji(df: pd.DataFrame, body_pct: float = 0.1) -> pd.Series:
    """Body is <= `body_pct` of the high-low range. Zero-range bars are not doji."""
    body = (df["close"] - df["open"]).abs()
    span = (df["high"] - df["low"]).replace(0, np.nan)
    return _as_bool((body / span) <= body_pct)


def hammer(df: pd.DataFrame, lower_wick_mult: float = 2.0, upper_wick_pct: float = 0.2) -> pd.Series:
    """Long lower wick (>= `lower_wick_mult` x body), small upper wick
    (<= `upper_wick_pct` of range). Bullish reversal signal at a low."""
    o, c, h, l = df["open"], df["close"], df["high"], df["low"]
    body = (c - o).abs()
    upper_wick = h - c.combine(o, max)
    lower_wick = o.combine(c, min) - l
    span = (h - l).replace(0, np.nan)
    return _as_bool(
        (lower_wick >= lower_wick_mult * body)
        & (upper_wick <= upper_wick_pct * span)
        & (body > 0)
    )
