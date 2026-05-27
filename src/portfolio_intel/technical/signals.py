"""Snapshot of all technical signals at the last bar.

This is the boundary the presentation layer (and later, the scoring engine
and LLM prompt) reads from. It contains computed numbers and qualitative
labels, never directional advice — those come from the scoring engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import indicators as ind
from .levels import Levels, find_levels
from .patterns import bearish_engulfing, bullish_engulfing, doji, hammer


@dataclass(frozen=True)
class TechnicalSnapshot:
    close: float
    rsi: float | None
    rsi_label: str  # "overbought" | "oversold" | "neutral" | "n/a"

    sma_50: float | None
    sma_200: float | None
    trend_label: str  # "uptrend" | "downtrend" | "mixed" | "n/a"
    recent_golden_cross: bool
    recent_death_cross: bool

    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    macd_label: str  # "bullish" | "bearish" | "neutral" | "n/a"

    bb_upper: float | None
    bb_lower: float | None
    bb_pct_b: float | None
    bb_label: str  # "near upper" | "near lower" | "mid range" | "n/a"

    atr: float | None
    atr_pct: float | None  # ATR as % of price — volatility proxy

    volume_ratio: float | None  # today's volume / 20-day avg
    volume_label: str  # "high" | "low" | "normal" | "n/a"

    levels: Levels
    nearest_support: float | None
    nearest_resistance: float | None

    patterns: list[str] = field(default_factory=list)  # names of patterns triggered on the last bar

    bars_used: int = 0


def compute_snapshot(df: pd.DataFrame, *, cross_lookback: int = 60) -> TechnicalSnapshot:
    """Compute every indicator and return a snapshot of the most recent values.

    `df` must have lowercase columns: open, high, low, close, volume.
    """
    _validate(df)
    close = df["close"]

    rsi_series = ind.rsi(close, 14)
    macd_df = ind.macd(close)
    bb = ind.bollinger(close)
    sma50 = ind.sma(close, 50)
    sma200 = ind.sma(close, 200)
    atr_series = ind.atr(df, 14)
    vol_ratio_series = ind.volume_signal(df, 20)
    gc = ind.golden_cross(close).tail(cross_lookback).any()
    dc = ind.death_cross(close).tail(cross_lookback).any()

    last = -1
    close_v = float(close.iloc[last])
    rsi_v = _last_float(rsi_series)
    sma50_v = _last_float(sma50)
    sma200_v = _last_float(sma200)
    macd_v = _last_float(macd_df["macd"])
    macd_sig_v = _last_float(macd_df["signal"])
    macd_hist_v = _last_float(macd_df["hist"])
    bb_upper = _last_float(bb["upper"])
    bb_lower = _last_float(bb["lower"])
    bb_pct = _last_float(bb["pct_b"])
    atr_v = _last_float(atr_series)
    atr_pct = (atr_v / close_v * 100.0) if (atr_v and close_v) else None
    vol_ratio = _last_float(vol_ratio_series)

    levels = find_levels(df)

    patterns: list[str] = []
    if bool(bullish_engulfing(df).iloc[last]):
        patterns.append("bullish engulfing")
    if bool(bearish_engulfing(df).iloc[last]):
        patterns.append("bearish engulfing")
    if bool(doji(df).iloc[last]):
        patterns.append("doji")
    if bool(hammer(df).iloc[last]):
        patterns.append("hammer")

    return TechnicalSnapshot(
        close=close_v,
        rsi=rsi_v,
        rsi_label=_rsi_label(rsi_v),
        sma_50=sma50_v,
        sma_200=sma200_v,
        trend_label=_trend_label(close_v, sma50_v, sma200_v),
        recent_golden_cross=bool(gc),
        recent_death_cross=bool(dc),
        macd=macd_v,
        macd_signal=macd_sig_v,
        macd_hist=macd_hist_v,
        macd_label=_macd_label(macd_v, macd_sig_v, macd_hist_v),
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        bb_pct_b=bb_pct,
        bb_label=_bb_label(bb_pct),
        atr=atr_v,
        atr_pct=atr_pct,
        volume_ratio=vol_ratio,
        volume_label=_volume_label(vol_ratio),
        levels=levels,
        nearest_support=levels.nearest_support,
        nearest_resistance=levels.nearest_resistance,
        patterns=patterns,
        bars_used=len(df),
    )


def _validate(df: pd.DataFrame) -> None:
    needed = {"open", "high", "low", "close", "volume"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"price DataFrame missing columns: {sorted(missing)}")
    if len(df) < 20:
        raise ValueError(f"need at least 20 bars to compute indicators; got {len(df)}")


def _last_float(s: pd.Series) -> float | None:
    if s is None or len(s) == 0:
        return None
    v = s.iloc[-1]
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _rsi_label(rsi: float | None) -> str:
    if rsi is None:
        return "n/a"
    if rsi >= 70:
        return "overbought"
    if rsi <= 30:
        return "oversold"
    return "neutral"


def _trend_label(close: float, sma50: float | None, sma200: float | None) -> str:
    if sma50 is None or sma200 is None:
        return "n/a"
    if close > sma50 > sma200:
        return "uptrend"
    if close < sma50 < sma200:
        return "downtrend"
    return "mixed"


def _macd_label(macd: float | None, signal: float | None, hist: float | None) -> str:
    if macd is None or signal is None or hist is None:
        return "n/a"
    if macd > signal and hist > 0:
        return "bullish"
    if macd < signal and hist < 0:
        return "bearish"
    return "neutral"


def _bb_label(pct_b: float | None) -> str:
    if pct_b is None:
        return "n/a"
    if pct_b >= 0.8:
        return "near upper"
    if pct_b <= 0.2:
        return "near lower"
    return "mid range"


def _volume_label(ratio: float | None) -> str:
    if ratio is None:
        return "n/a"
    if ratio >= 1.5:
        return "high"
    if ratio <= 0.6:
        return "low"
    return "normal"
