"""Options-related statistics.

Pure math. Used by the IV-vs-RV panel and the covered-call yield
calculator. Kept separate from pricing.py so the Black-Scholes math
stays focused on per-contract pricing.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd


def realized_volatility(closes: pd.Series, window: int = 30) -> Optional[float]:
    """Annualised realised volatility from a series of daily closes.

    Computed as the standard deviation of log returns over the last
    `window` days, scaled by sqrt(252). Returns None if there isn't
    enough data.

    Output is in decimal form (0.22 = 22%), to match implied_vol().
    """
    if closes is None or len(closes) < 2:
        return None
    rets = (closes / closes.shift(1)).apply(lambda x: math.log(x) if x and x > 0 else None).dropna()
    rets = rets.tail(window)
    if len(rets) < max(5, window // 6):
        return None
    sigma = float(rets.std())
    if sigma <= 0 or not math.isfinite(sigma):
        return None
    return sigma * math.sqrt(252.0)


def iv_rv_label(iv: Optional[float], rv: Optional[float]) -> str:
    """Three-bucket label for the IV/RV spread.

    Below ~0.9: implied is cheap vs what the stock actually does.
    Above ~1.2: implied is rich.
    In between: fair.
    """
    if iv is None or rv is None or rv <= 0:
        return "n/a"
    ratio = iv / rv
    if ratio < 0.9:
        return "cheap"
    if ratio > 1.2:
        return "rich"
    return "fair"
