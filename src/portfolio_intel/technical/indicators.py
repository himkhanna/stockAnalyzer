"""Technical indicators, implemented directly in pandas.

Formulas are standard:
  RSI(n)  — Wilder's smoothed RS.
  MACD    — EMA(fast) - EMA(slow); signal = EMA(signal) of MACD.
  SMA(n)  — simple moving average.
  EMA(n)  — exponential, span=n.
  Bollinger(n, k) — SMA(n) ± k * rolling std(n).
  ATR(n)  — Wilder's smoothed true range.

Input: a DataFrame with lowercase columns: open, high, low, close, volume.
All functions return a Series indexed identically to `close`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(close: pd.Series, length: int) -> pd.Series:
    return close.rolling(window=length, min_periods=length).mean()


def ema(close: pd.Series, length: int) -> pd.Series:
    # adjust=False matches the recursive definition used everywhere in TA literature.
    return close.ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing == EMA with alpha = 1/length.
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss is 0 the RS is inf -> RSI = 100. When both are 0, RSI is undefined.
    out = out.where(~(avg_loss == 0) | (avg_gain == 0), 100.0)
    return out


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """Returns a DataFrame with columns: macd, signal, hist."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(
    close: pd.Series, length: int = 20, k: float = 2.0
) -> pd.DataFrame:
    """Returns columns: mid, upper, lower, pct_b, bandwidth."""
    mid = sma(close, length)
    sd = close.rolling(window=length, min_periods=length).std(ddof=0)
    upper = mid + k * sd
    lower = mid - k * sd
    pct_b = (close - lower) / (upper - lower)
    bandwidth = (upper - lower) / mid
    return pd.DataFrame(
        {"mid": mid, "upper": upper, "lower": lower, "pct_b": pct_b, "bandwidth": bandwidth}
    )


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Wilder's ATR. Requires high, low, close columns."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def volume_signal(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Ratio of current volume to its `length`-period average. >1 means above
    average, <1 below. Useful as a 'is this move backed by volume' check."""
    avg = df["volume"].rolling(window=length, min_periods=length).mean()
    return df["volume"] / avg


def golden_cross(close: pd.Series, fast: int = 50, slow: int = 200) -> pd.Series:
    """True at bars where SMA(fast) crossed up through SMA(slow)."""
    f = sma(close, fast)
    s = sma(close, slow)
    prev = (f.shift(1) <= s.shift(1))
    now = f > s
    return prev & now


def death_cross(close: pd.Series, fast: int = 50, slow: int = 200) -> pd.Series:
    f = sma(close, fast)
    s = sma(close, slow)
    prev = (f.shift(1) >= s.shift(1))
    now = f < s
    return prev & now
