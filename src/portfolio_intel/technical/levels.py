"""Support / resistance from local highs and lows.

Algorithm: a bar is a swing high if its `high` is the maximum in a window
of `window` bars on each side (and likewise a swing low for the minimum).
We then cluster nearby swing prices into levels using a percentage band.

This is intentionally simple — better than nothing, far less risky than
letting the LLM invent a 'support level.' CLAUDE.md is explicit that
targets come from real levels, never from the model.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Levels:
    supports: list[float]   # sorted ascending
    resistances: list[float]  # sorted ascending
    nearest_support: float | None
    nearest_resistance: float | None


def find_levels(
    df: pd.DataFrame,
    *,
    window: int = 5,
    cluster_pct: float = 0.01,
    last_n: int = 250,
) -> Levels:
    """Find swing highs/lows in the last `last_n` bars and cluster them.

    `cluster_pct` is the fraction (e.g. 0.01 = 1%) within which two swing
    prices are considered the same level.
    """
    recent = df.tail(last_n)
    highs = _swing_points(recent["high"], window, mode="max")
    lows = _swing_points(recent["low"], window, mode="min")

    res_levels = _cluster(highs, cluster_pct)
    sup_levels = _cluster(lows, cluster_pct)

    last_close = float(df["close"].iloc[-1])
    nearest_sup = max((s for s in sup_levels if s < last_close), default=None)
    nearest_res = min((r for r in res_levels if r > last_close), default=None)

    return Levels(
        supports=sup_levels,
        resistances=res_levels,
        nearest_support=nearest_sup,
        nearest_resistance=nearest_res,
    )


def _swing_points(series: pd.Series, window: int, mode: str) -> list[float]:
    out: list[float] = []
    arr = series.values
    n = len(arr)
    for i in range(window, n - window):
        left = arr[i - window : i]
        right = arr[i + 1 : i + 1 + window]
        v = arr[i]
        if mode == "max" and v >= left.max() and v >= right.max():
            out.append(float(v))
        elif mode == "min" and v <= left.min() and v <= right.min():
            out.append(float(v))
    return out


def _cluster(prices: list[float], pct: float) -> list[float]:
    if not prices:
        return []
    sorted_prices = sorted(prices)
    clusters: list[list[float]] = [[sorted_prices[0]]]
    for p in sorted_prices[1:]:
        anchor = clusters[-1][0]
        if anchor == 0 or abs(p - anchor) / anchor <= pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [round(sum(c) / len(c), 4) for c in clusters]
