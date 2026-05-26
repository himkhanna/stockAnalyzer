"""Options endpoints — NSE F&O via Breeze.

This module fetches chain data and computes Greeks/IV. It is strictly
information + math. There is NO recommendation engine for options. Per
CLAUDE.md, the stock scoring engine doesn't translate to derivatives,
and we will not pretend otherwise.

Endpoints:
- GET  /api/options/expiries          → next monthly + weekly expiry dates
- GET  /api/options/chain             → chain rows with computed Greeks + IV
- POST /api/options/payoff            → multi-leg payoff curve (pure math)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from portfolio_intel.brokers import (
    BreezeClient,
    BreezeError,
    BreezeNotInstalled,
    BreezeSessionExpired,
)
from portfolio_intel.markets import Market
from portfolio_intel.options import (
    DEFAULT_DIVIDEND_YIELD,
    DEFAULT_RISK_FREE_IN,
    bs_greeks,
    bs_price,
    implied_vol,
    next_monthly_expiries,
    next_weekly_expiries,
    years_to_expiry,
)
from portfolio_intel.options.pricing import OptionRight

from ..state import get_source, get_store

router = APIRouter()
_BROKER = "icici_breeze"


# --- Schemas ---

class ExpiriesOut(BaseModel):
    monthly: list[str]
    weekly: list[str]


class OptionRow(BaseModel):
    strike: float
    right: str   # "call" | "put"
    bid: Optional[float] = None
    ask: Optional[float] = None
    ltp: Optional[float] = None
    open_interest: Optional[float] = None
    volume: Optional[float] = None
    iv: Optional[float] = None        # implied vol (decimal, 0.20 = 20%)
    theo_price: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None     # per day
    vega: Optional[float] = None      # per vol point


class ChainOut(BaseModel):
    underlying_symbol: str
    underlying_broker_code: str
    spot: Optional[float] = None
    expiry: str
    days_to_expiry: int
    risk_free_rate: float
    rows: list[OptionRow]
    note: str = (
        "Read-only chain data. Greeks computed via Black-Scholes. "
        "No directional recommendations are made for options."
    )


class PayoffLeg(BaseModel):
    qty: int                                 # negative = short
    right: OptionRight                       # "call" | "put"
    strike: float
    premium: float = Field(..., description="Per-share premium paid (positive) or received (negative ignored — use negative qty for short).")


class PayoffIn(BaseModel):
    spot: float
    legs: list[PayoffLeg]
    lot_size: int = 1
    s_min: Optional[float] = None
    s_max: Optional[float] = None
    steps: int = 121


class PayoffPoint(BaseModel):
    s: float
    pnl: float


class PayoffOut(BaseModel):
    curve: list[PayoffPoint]
    max_loss: float
    max_gain: float
    break_evens: list[float]
    cost_basis: float                # net premium paid (positive = debit, negative = credit)


# --- Endpoints ---


@router.get("/expiries", response_model=ExpiriesOut)
def expiries() -> ExpiriesOut:
    monthly = [d.isoformat() for d in next_monthly_expiries(6)]
    weekly = [d.isoformat() for d in next_weekly_expiries(8)]
    return ExpiriesOut(monthly=monthly, weekly=weekly)


@router.get("/chain", response_model=ChainOut)
def chain(
    symbol: str = Query(..., description="NSE bare ticker (e.g. RELIANCE) OR an ICICI broker code OR NIFTY/BANKNIFTY"),
    expiry: str = Query(..., description="YYYY-MM-DD"),
    broker_code: Optional[str] = Query(None, description="ICICI broker stock_code if different from symbol (e.g. EXIIND for EXIDEIND)"),
    rate: float = Query(DEFAULT_RISK_FREE_IN, description="Risk-free rate, decimal (0.07 = 7%)"),
) -> ChainOut:
    try:
        expiry_date = date.fromisoformat(expiry)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"bad expiry: {expiry}")

    cfg = get_store().broker_get(_BROKER)
    if not cfg or not cfg.get("session_token"):
        raise HTTPException(
            status_code=400,
            detail="ICICI Breeze not connected. Connect via Portfolio → ICICI Direct sync.",
        )

    underlying_code = (broker_code or symbol).upper()

    try:
        client = BreezeClient(cfg["api_key"])
        client.connect(cfg["api_secret"], cfg["session_token"])
        contracts = client.get_option_chain(stock_code=underlying_code, expiry=expiry_date)
    except BreezeNotInstalled as e:
        raise HTTPException(status_code=503, detail=str(e))
    except BreezeSessionExpired as e:
        raise HTTPException(status_code=401, detail=str(e))
    except BreezeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Best-effort underlying spot price via yfinance.
    spot: Optional[float] = None
    try:
        q = get_source().get_quote(symbol.upper(), Market.NSE)
        spot = float(q.price)
    except Exception:
        spot = None

    T = years_to_expiry(expiry_date)
    days = max((expiry_date - date.today()).days, 0)

    rows: list[OptionRow] = []
    for c in contracts:
        # Choose a sensible market price to derive IV from: prefer mid of
        # bid/ask, fall back to LTP.
        mid: Optional[float] = None
        if c.bid is not None and c.ask is not None and c.ask > 0 and c.bid > 0:
            mid = 0.5 * (c.bid + c.ask)
        elif c.ltp is not None and c.ltp > 0:
            mid = c.ltp

        iv = None
        theo = None
        d = g = t = v = None
        if spot is not None and mid is not None and c.strike_price > 0:
            iv = implied_vol(
                market_price=mid, S=spot, K=c.strike_price, T=T, r=rate,
                right=c.right, q=DEFAULT_DIVIDEND_YIELD,
            )
            if iv is not None:
                theo = bs_price(S=spot, K=c.strike_price, T=T, r=rate, sigma=iv, right=c.right)
                gk = bs_greeks(S=spot, K=c.strike_price, T=T, r=rate, sigma=iv, right=c.right)
                d, g, t, v = gk.delta, gk.gamma, gk.theta, gk.vega

        rows.append(OptionRow(
            strike=c.strike_price,
            right=c.right,
            bid=c.bid, ask=c.ask, ltp=c.ltp,
            open_interest=c.open_interest, volume=c.volume,
            iv=iv, theo_price=theo,
            delta=d, gamma=g, theta=t, vega=v,
        ))

    return ChainOut(
        underlying_symbol=symbol.upper(),
        underlying_broker_code=underlying_code,
        spot=spot,
        expiry=expiry_date.isoformat(),
        days_to_expiry=days,
        risk_free_rate=rate,
        rows=rows,
    )


@router.post("/payoff", response_model=PayoffOut)
def payoff(body: PayoffIn) -> PayoffOut:
    """Pure expiration-payoff math. No prediction, no Black-Scholes
    extrapolation; just the piecewise-linear value of the position at expiry."""
    if not body.legs:
        raise HTTPException(status_code=400, detail="at least one leg required")

    cost_basis = sum(leg.qty * leg.premium for leg in body.legs) * body.lot_size

    strikes = sorted({leg.strike for leg in body.legs})
    s_min = body.s_min if body.s_min is not None else max(min(strikes) * 0.7, 1e-6)
    s_max = body.s_max if body.s_max is not None else max(strikes) * 1.3 + 1.0
    if s_max <= s_min:
        raise HTTPException(status_code=400, detail="s_max must be > s_min")
    steps = max(11, min(body.steps, 1001))

    def leg_intrinsic(leg: PayoffLeg, s: float) -> float:
        if leg.right == "call":
            return max(s - leg.strike, 0.0)
        return max(leg.strike - s, 0.0)

    curve: list[PayoffPoint] = []
    for i in range(steps):
        s = s_min + (s_max - s_min) * i / (steps - 1)
        gross = sum(leg.qty * leg_intrinsic(leg, s) for leg in body.legs) * body.lot_size
        pnl = gross - cost_basis
        curve.append(PayoffPoint(s=round(s, 4), pnl=round(pnl, 4)))

    pnl_vals = [p.pnl for p in curve]
    max_loss = min(pnl_vals)
    max_gain = max(pnl_vals)

    # Break-evens: linear interpolation between sign changes.
    breaks: list[float] = []
    for i in range(1, len(curve)):
        a, b = curve[i - 1], curve[i]
        if a.pnl == 0:
            breaks.append(a.s)
        if (a.pnl > 0 and b.pnl < 0) or (a.pnl < 0 and b.pnl > 0):
            t = a.pnl / (a.pnl - b.pnl)
            breaks.append(round(a.s + t * (b.s - a.s), 4))
    # Dedupe near-equal break-evens.
    deduped: list[float] = []
    for b in sorted(breaks):
        if not deduped or abs(b - deduped[-1]) > 1e-3:
            deduped.append(b)

    return PayoffOut(
        curve=curve,
        max_loss=round(max_loss, 4),
        max_gain=round(max_gain, 4),
        break_evens=deduped,
        cost_basis=round(cost_basis, 4),
    )
