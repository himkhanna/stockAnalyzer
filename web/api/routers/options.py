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
    seed_broker_code,
)
from portfolio_intel.markets import Market, parse_ticker
from portfolio_intel.options import (
    DEFAULT_DIVIDEND_YIELD,
    DEFAULT_RISK_FREE_IN,
    bs_greeks,
    bs_price,
    candidate_expiries,
    implied_vol,
    iv_rv_label,
    next_monthly_expiries,
    next_weekly_expiries,
    realized_volatility,
    years_to_expiry,
)
from portfolio_intel.options.pricing import OptionRight

from ..state import get_source, get_store

router = APIRouter()
_BROKER = "icici_breeze"

# Cache key: (broker_stock_code, today). Per-symbol, per-day. Cleared on
# process restart, which is the right TTL for an expiry calendar.
_PROBE_CACHE: dict[tuple[str, str], list[str]] = {}


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
    """Calendar-derived expiries. Cheap fallback; use /expiries/probe for
    per-symbol verified dates."""
    monthly = [d.isoformat() for d in next_monthly_expiries(6)]
    weekly = [d.isoformat() for d in next_weekly_expiries(8)]
    return ExpiriesOut(monthly=monthly, weekly=weekly)


class ProbeOut(BaseModel):
    underlying_symbol: str
    underlying_broker_code: str
    expiries: list[str]
    probed: list[str]
    cached: bool = False
    note: str = (
        "Verified by asking Breeze which last-week-of-month dates have "
        "contracts for this underlying."
    )


@router.get("/expiries/probe", response_model=ProbeOut)
def expiries_probe(
    symbol: str = Query(..., description="NSE bare ticker OR ICICI broker code"),
    broker_code: Optional[str] = Query(None),
    months: int = Query(3, ge=1, le=6, description="How many monthly cycles to probe"),
) -> ProbeOut:
    """Ask Breeze which expiry dates actually have contracts for the
    underlying. Probes every Mon-Fri of the last week of the next
    `months` monthly cycles. Per-symbol, per-day in-memory cache."""
    store = get_store()
    cfg = store.broker_get(_BROKER)
    if not cfg or not cfg.get("session_token"):
        raise HTTPException(
            status_code=400,
            detail="ICICI Breeze not connected. Connect via Portfolio → ICICI Direct sync.",
        )

    bare_symbol, _ = parse_ticker(symbol, default_market=Market.NSE)
    learned_code = store.broker_code_get(_BROKER, bare_symbol)
    seed_code = seed_broker_code(bare_symbol)
    underlying_code = (broker_code or learned_code or seed_code or bare_symbol).upper()

    cache_key = (underlying_code, date.today().isoformat())
    if cache_key in _PROBE_CACHE:
        return ProbeOut(
            underlying_symbol=bare_symbol,
            underlying_broker_code=underlying_code,
            expiries=_PROBE_CACHE[cache_key],
            probed=[],
            cached=True,
        )

    candidates = candidate_expiries(months=months)
    try:
        client = BreezeClient(cfg["api_key"])
        client.connect(cfg["api_secret"], cfg["session_token"])
        found = client.find_available_expiries(stock_code=underlying_code, candidates=candidates)
    except BreezeNotInstalled as e:
        raise HTTPException(status_code=503, detail=str(e))
    except BreezeSessionExpired as e:
        raise HTTPException(status_code=401, detail=str(e))
    except BreezeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    expiries_iso = [d.isoformat() for d in found]
    # Only cache non-empty results — empty might mean a wrong broker code,
    # which the user is still figuring out.
    if expiries_iso:
        _PROBE_CACHE[cache_key] = expiries_iso

    return ProbeOut(
        underlying_symbol=bare_symbol,
        underlying_broker_code=underlying_code,
        expiries=expiries_iso,
        probed=[d.isoformat() for d in candidates],
    )


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

    store = get_store()
    cfg = store.broker_get(_BROKER)
    if not cfg or not cfg.get("session_token"):
        raise HTTPException(
            status_code=400,
            detail="ICICI Breeze not connected. Connect via Portfolio → ICICI Direct sync.",
        )

    # Strip any yfinance suffix (.NS / .BO) before handing to Breeze — it
    # rejects qualified symbols with a generic "Error while calling service".
    bare_symbol, _ = parse_ticker(symbol, default_market=Market.NSE)

    # Resolution order:
    #   explicit override → learned DB dictionary → curated seed map → bare.
    learned_code = store.broker_code_get(_BROKER, bare_symbol)
    seed_code = seed_broker_code(bare_symbol)
    underlying_code = (broker_code or learned_code or seed_code or bare_symbol).upper()

    try:
        client = BreezeClient(cfg["api_key"])
        client.connect(cfg["api_secret"], cfg["session_token"])
        contracts = client.get_option_chain(stock_code=underlying_code, expiry=expiry_date)
    except BreezeNotInstalled as e:
        raise HTTPException(status_code=503, detail=str(e))
    except BreezeSessionExpired as e:
        raise HTTPException(status_code=401, detail=str(e))
    except BreezeError as e:
        msg = str(e)
        low = msg.lower()
        # Breeze's "T10:56 / contact admin" almost always means the stock_code
        # doesn't resolve to an F&O underlying on their side. Suggest the most
        # common fix instead of bouncing their raw message to the user.
        if "contact admin" in low or "t10:56" in low or "calling service" in low:
            hint = (
                f"Breeze couldn't resolve '{underlying_code}' as an F&O "
                "underlying. Try the ICICI broker code instead (e.g. RELIND "
                "for RELIANCE, EXIIND for EXIDEIND, STABAN for SBIN). For "
                "indices use NIFTY / BANKNIFTY / FINNIFTY."
            )
            raise HTTPException(status_code=502, detail=f"{hint} (Breeze: {msg})")
        raise HTTPException(status_code=502, detail=msg)

    # Chain came back. If the code we just used isn't the same as the bare
    # symbol, record it so next time the user doesn't need the override.
    # Only record on a non-empty result — an empty list often means Breeze
    # accepted the call but the symbol still isn't a real F&O underlying.
    if contracts and underlying_code != bare_symbol:
        source = "chain_ok" if broker_code else "chain_ok_auto"
        store.broker_code_upsert(_BROKER, bare_symbol, underlying_code, source)

    # Best-effort underlying spot price via yfinance — use the bare symbol;
    # the source re-adds the market suffix internally.
    spot: Optional[float] = None
    try:
        q = get_source().get_quote(bare_symbol, Market.NSE)
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
        underlying_symbol=bare_symbol,
        underlying_broker_code=underlying_code,
        spot=spot,
        expiry=expiry_date.isoformat(),
        days_to_expiry=days,
        risk_free_rate=rate,
        rows=rows,
    )


class IVSnapshotOut(BaseModel):
    underlying_symbol: str
    underlying_broker_code: str
    spot: Optional[float] = None
    expiry: str
    days_to_expiry: int
    atm_strike: Optional[float] = None
    atm_iv: Optional[float] = None           # decimal, 0.22 = 22%
    realized_vol_30d: Optional[float] = None # decimal, annualised
    iv_rv_ratio: Optional[float] = None
    label: str = "n/a"                       # cheap | fair | rich | n/a
    note: str = (
        "IV from ATM contract via Black-Scholes inversion. RV = stdev of "
        "log returns over the last 30 trading days, annualised by sqrt(252). "
        "Above ~1.2x = implied is rich; below ~0.9x = implied is cheap."
    )


@router.get("/iv-snapshot", response_model=IVSnapshotOut)
def iv_snapshot(
    symbol: str = Query(..., description="NSE bare ticker"),
    expiry: str = Query(..., description="YYYY-MM-DD"),
    broker_code: Optional[str] = Query(None),
    rate: float = Query(DEFAULT_RISK_FREE_IN),
) -> IVSnapshotOut:
    """ATM implied vol vs 30d realized vol for the underlying."""
    chain_out = chain(symbol=symbol, expiry=expiry, broker_code=broker_code, rate=rate)

    # Find the ATM strike (closest to spot) and its call IV.
    atm_strike: Optional[float] = None
    atm_iv: Optional[float] = None
    if chain_out.spot is not None and chain_out.rows:
        # Pick the call closest to spot whose IV solved.
        calls = [r for r in chain_out.rows if r.right == "call" and r.iv is not None]
        if calls:
            best = min(calls, key=lambda r: abs(r.strike - chain_out.spot))
            atm_strike = best.strike
            atm_iv = best.iv

    # 30d realized vol from yfinance closes.
    rv: Optional[float] = None
    try:
        bare_symbol, _ = parse_ticker(symbol, default_market=Market.NSE)
        hist = get_source().get_history(bare_symbol, Market.NSE, period="3mo", interval="1d")
        if hist is not None and not hist.empty and "close" in hist.columns:
            rv = realized_volatility(hist["close"], window=30)
    except Exception:
        rv = None

    ratio = (atm_iv / rv) if (atm_iv is not None and rv is not None and rv > 0) else None

    return IVSnapshotOut(
        underlying_symbol=chain_out.underlying_symbol,
        underlying_broker_code=chain_out.underlying_broker_code,
        spot=chain_out.spot,
        expiry=chain_out.expiry,
        days_to_expiry=chain_out.days_to_expiry,
        atm_strike=atm_strike,
        atm_iv=atm_iv,
        realized_vol_30d=rv,
        iv_rv_ratio=ratio,
        label=iv_rv_label(atm_iv, rv),
    )


class CoveredCallRow(BaseModel):
    strike: float
    premium: float                    # mid or LTP, whichever the chain has
    days_to_expiry: int
    yield_pct: float                  # premium / spot * 100, period yield
    annualized_pct: float             # yield_pct scaled to 365d
    moneyness_pct: float              # (strike - spot) / spot * 100
    delta: Optional[float] = None     # assignment-probability proxy
    open_interest: Optional[float] = None
    iv: Optional[float] = None


class CoveredCallsOut(BaseModel):
    underlying_symbol: str
    underlying_broker_code: str
    spot: Optional[float]
    expiry: str
    days_to_expiry: int
    rows: list[CoveredCallRow]
    note: str = (
        "Information only — not a recommendation to write calls. Yield = "
        "premium / spot for the period. Annualised assumes you keep rolling "
        "at the same yield (you won't). Δ is a rough proxy for the "
        "probability of being assigned at expiry."
    )


@router.get("/covered-calls", response_model=CoveredCallsOut)
def covered_calls(
    symbol: str = Query(..., description="NSE bare ticker you hold"),
    expiry: str = Query(..., description="YYYY-MM-DD"),
    broker_code: Optional[str] = Query(None),
    rate: float = Query(DEFAULT_RISK_FREE_IN),
    max_otm_pct: float = Query(15.0, description="Skip strikes more than this % above spot"),
) -> CoveredCallsOut:
    """For a stock you hold, list OTM monthly calls with their period
    yield, annualised yield, and assignment-probability proxy.

    Information only — no ranking by 'best trade', no buy/sell call. The
    user picks which trade-off (yield vs assignment risk) they want.
    """
    chain_out = chain(symbol=symbol, expiry=expiry, broker_code=broker_code, rate=rate)

    spot = chain_out.spot
    days = chain_out.days_to_expiry
    out_rows: list[CoveredCallRow] = []

    if spot is not None and spot > 0:
        for r in chain_out.rows:
            if r.right != "call":
                continue
            if r.strike <= spot:
                continue  # ITM/ATM — covered calls are usually OTM
            moneyness = (r.strike - spot) / spot * 100.0
            if moneyness > max_otm_pct:
                continue
            premium = r.ltp if r.ltp is not None else (
                0.5 * (r.bid + r.ask) if (r.bid and r.ask and r.bid > 0 and r.ask > 0) else None
            )
            if premium is None or premium <= 0:
                continue
            yield_pct = premium / spot * 100.0
            annualised = (yield_pct / max(days, 1)) * 365.0
            out_rows.append(CoveredCallRow(
                strike=r.strike,
                premium=round(premium, 2),
                days_to_expiry=days,
                yield_pct=round(yield_pct, 3),
                annualized_pct=round(annualised, 2),
                moneyness_pct=round(moneyness, 2),
                delta=r.delta,
                open_interest=r.open_interest,
                iv=r.iv,
            ))

    # Sort by yield_pct descending — highest income at top. User compares
    # against the Δ column to weigh assignment risk.
    out_rows.sort(key=lambda x: x.yield_pct, reverse=True)

    return CoveredCallsOut(
        underlying_symbol=chain_out.underlying_symbol,
        underlying_broker_code=chain_out.underlying_broker_code,
        spot=spot,
        expiry=chain_out.expiry,
        days_to_expiry=days,
        rows=out_rows,
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
