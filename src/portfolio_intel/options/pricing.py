"""Options pricing and Greeks.

All math, no I/O. Pure functions — easy to test, no dependencies on the
broker layer. Used by the API to enrich a chain with Greeks and to solve
implied volatility from a quoted market price.

Black-Scholes assumptions are explicit and well-known; we don't pretend
to predict prices. For Indian markets we default to a 7% risk-free rate
(roughly the 10-year G-Sec). Use whatever fits your context.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Optional

OptionRight = Literal["call", "put"]

DEFAULT_RISK_FREE_IN = 0.07   # India ~10y G-Sec
DEFAULT_DIVIDEND_YIELD = 0.0

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _phi(x: float) -> float:
    """Standard-normal PDF."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _Phi(x: float) -> float:
    """Standard-normal CDF via erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def years_to_expiry(expiry: date, ref: Optional[datetime] = None) -> float:
    """Calendar-time to expiry in years (365-day basis)."""
    ref = ref or datetime.now()
    if isinstance(expiry, datetime):
        target = expiry
    else:
        target = datetime.combine(expiry, datetime.min.time().replace(hour=15, minute=30))
    delta = target - ref
    return max(delta.total_seconds() / (365.0 * 24 * 3600), 1e-9)


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    theta: float   # per calendar day
    vega: float    # per 1 vol point (i.e. multiply by 0.01 for "per 1%")
    rho: float     # per 1 rate point


def _d1_d2(S: float, K: float, T: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return float("nan"), float("nan")
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_price(
    *,
    S: float, K: float, T: float, r: float, sigma: float,
    right: OptionRight, q: float = DEFAULT_DIVIDEND_YIELD,
) -> float:
    """Black-Scholes price for a European call/put."""
    if T <= 0 or sigma <= 0:
        # Intrinsic value if we're at/past expiry or zero vol.
        if right == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    if right == "call":
        return S * disc_q * _Phi(d1) - K * disc_r * _Phi(d2)
    return K * disc_r * _Phi(-d2) - S * disc_q * _Phi(-d1)


def bs_greeks(
    *,
    S: float, K: float, T: float, r: float, sigma: float,
    right: OptionRight, q: float = DEFAULT_DIVIDEND_YIELD,
) -> Greeks:
    if T <= 0 or sigma <= 0:
        return Greeks(delta=float("nan"), gamma=float("nan"), theta=float("nan"),
                      vega=float("nan"), rho=float("nan"))
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    pdf_d1 = _phi(d1)
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    sqrtT = math.sqrt(T)

    if right == "call":
        delta = disc_q * _Phi(d1)
        theta_yr = (
            -S * disc_q * pdf_d1 * sigma / (2.0 * sqrtT)
            - r * K * disc_r * _Phi(d2)
            + q * S * disc_q * _Phi(d1)
        )
        rho = K * T * disc_r * _Phi(d2) / 100.0
    else:
        delta = -disc_q * _Phi(-d1)
        theta_yr = (
            -S * disc_q * pdf_d1 * sigma / (2.0 * sqrtT)
            + r * K * disc_r * _Phi(-d2)
            - q * S * disc_q * _Phi(-d1)
        )
        rho = -K * T * disc_r * _Phi(-d2) / 100.0

    gamma = disc_q * pdf_d1 / (S * sigma * sqrtT)
    vega = S * disc_q * pdf_d1 * sqrtT / 100.0  # per 1 vol point (0.01)
    theta_day = theta_yr / 365.0
    return Greeks(delta=delta, gamma=gamma, theta=theta_day, vega=vega, rho=rho)


def implied_vol(
    *,
    market_price: float,
    S: float, K: float, T: float, r: float,
    right: OptionRight, q: float = DEFAULT_DIVIDEND_YIELD,
    tol: float = 1e-5, max_iter: int = 60,
) -> Optional[float]:
    """Solve for σ from market price via Newton-Raphson with a bisection
    safety net. Returns None if the price is impossible (below intrinsic
    or above the no-arbitrage upper bound) or the solver fails to converge."""
    if market_price <= 0 or T <= 0:
        return None
    intrinsic = max((S - K) if right == "call" else (K - S), 0.0)
    if market_price < intrinsic - 1e-8:
        return None
    if right == "call":
        upper = S * math.exp(-q * T)
    else:
        upper = K * math.exp(-r * T)
    if market_price >= upper - 1e-8:
        return None

    # Bracket: σ between 1e-4 and 5.
    lo, hi = 1e-4, 5.0
    sigma = 0.3
    for _ in range(max_iter):
        price = bs_price(S=S, K=K, T=T, r=r, sigma=sigma, right=right, q=q)
        diff = price - market_price
        if abs(diff) < tol:
            return sigma
        v = bs_greeks(S=S, K=K, T=T, r=r, sigma=sigma, right=right, q=q).vega * 100.0
        if v < 1e-8:
            # Vega too small to step reliably — fall back to bisection.
            if diff > 0:
                hi = sigma
            else:
                lo = sigma
            sigma = 0.5 * (lo + hi)
            continue
        step = diff / v
        new_sigma = sigma - step
        if new_sigma <= lo or new_sigma >= hi:
            # Out of bracket — bisect instead.
            if diff > 0:
                hi = sigma
            else:
                lo = sigma
            new_sigma = 0.5 * (lo + hi)
        sigma = new_sigma
    return None
