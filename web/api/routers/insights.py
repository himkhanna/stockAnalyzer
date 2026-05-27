"""GET /api/insights → conviction board, watchlist scan, market pulse, risk,
signal changes, upcoming earnings.

Every directional claim here comes from the existing deterministic scoring
engine + rules. The LLM is not consulted. Per CLAUDE.md: signals are decision
support, never advice.
"""
from __future__ import annotations

import os
import pickle
import threading
import time as _time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from portfolio_intel.discovery import (
    classify as classify_asset,
    scan_universe,
    summarise as summarise_diversification,
    universe_for,
)
from portfolio_intel.markets import INDICES, Market
from portfolio_intel.portfolio.performance import Period, attribute
from portfolio_intel.portfolio.tax import (
    current_fy,
    find_harvest_candidates,
    summarise_realized_gains,
)

from ..schemas import (
    AssetSliceOut,
    AttributionBucketOut,
    AttributionRowOut,
    CapitalGainsBucketOut,
    CapitalGainsOut,
    CardRowOut,
    ConvictionRow,
    CurrencyExposure,
    DiscoveryOut,
    DiscoveryRowOut,
    DiversificationInstrumentOut,
    DiversificationOut,
    EarningsItem,
    HarvestCandidateOut,
    IndexSnapshot,
    InsightsOut,
    PerformanceOut,
    RealizedGainIn,
    RealizedGainOut,
    RiskPanel,
    RiskTopWeight,
    SignalChange,
    TaxHarvestOut,
)
from ..serializers import card_row_to_out
from ..state import build_card_for, get_dashboard, get_source, get_store

router = APIRouter()
_DIGEST_DIR = Path(os.environ.get("DIGEST_DIR", "digests"))

# Conviction = strong score AND a confirming rule. The threshold matches
# the Strong Buy / Strong Sell cutoff in scoring/weights.py (±6.0).
_CONVICTION_ABS_SCORE = 6.0

# Discovery scan is expensive (~1s per ticker × ~100 tickers). Cache the
# result on disk for 6h so the page loads instantly after the first scan
# of the day. User can force-refresh.
_DISCOVERY_CACHE_FILE = Path(".discovery_cache.pkl")
_DISCOVERY_CACHE_TTL_S = 6 * 60 * 60
_DISCOVERY_LOCK = threading.Lock()

# Performance attribution needs daily closes per holding (potentially
# 1y back). Cache the closes series per (ticker, market) in memory for
# the day to dedupe repeated requests; the values don't change once
# the day's close is set.
_HISTORY_CACHE: dict[tuple[str, str, str], "object"] = {}
_HISTORY_LOCK = threading.Lock()

# Insights cache. We persist the full /api/insights payload to disk and
# only rebuild when (a) the holding set changes (fingerprint), or
# (b) the user explicitly hits Refresh (?force=true). Hitting the
# Insights tab repeatedly should NOT trigger N rebuilds — users like
# himkhanna get visibly annoyed by the latency, and most of the
# panels (conviction, risk, signal changes, earnings) don't change
# meaningfully between page loads anyway.
_INSIGHTS_CACHE_FILE = Path(".insights_cache.pkl")
_INSIGHTS_LOCK = threading.Lock()


def _portfolio_fingerprint() -> tuple:
    """Cheap fingerprint over the holdings set — when this changes, the
    insights cache should miss."""
    try:
        holdings = get_store().all()
        return tuple(sorted(
            (h.ticker.upper(), h.market_code.upper(), h.shares)
            for h in holdings
        ))
    except Exception:
        return ("",)


def _insights_load() -> Optional[dict]:
    if not _INSIGHTS_CACHE_FILE.exists():
        return None
    try:
        with _INSIGHTS_CACHE_FILE.open("rb") as f:
            return pickle.load(f)
    except (pickle.UnpicklingError, EOFError, AttributeError, ImportError):
        try:
            _INSIGHTS_CACHE_FILE.unlink()
        except OSError:
            pass
        return None


def _insights_save(payload: dict) -> None:
    try:
        with _INSIGHTS_CACHE_FILE.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError:
        pass


def _bulk_warm_history(items: list[tuple[str, str]]) -> None:
    """Pre-populate _HISTORY_CACHE for many holdings in one yfinance call.

    Falls back to per-ticker get_history for whatever the bulk missed.
    Errors are swallowed — anything still missing just gets None when
    _closes_for is called (which the attribute() helper handles by
    falling back to cost basis with a 'since added' label).
    """
    today_iso = date.today().isoformat()
    needed: list[tuple[str, str, "Market"]] = []
    for sym, mkt in items:
        key = (sym.upper(), mkt.upper(), today_iso)
        with _HISTORY_LOCK:
            if key in _HISTORY_CACHE:
                continue
        try:
            m = Market.from_code(mkt)
        except Exception:
            continue
        needed.append((sym, mkt, m))
    if not needed:
        return

    try:
        import yfinance as yf
    except ImportError:
        return

    qualified_to_key: dict[str, tuple[str, str]] = {}
    for sym, mkt_code, m in needed:
        qualified_to_key[m.format_ticker(sym)] = (sym.upper(), mkt_code.upper())

    try:
        df = yf.download(
            tickers=list(qualified_to_key.keys()),
            period="1y",
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception:
        df = None

    if df is not None and not df.empty:
        single = len(qualified_to_key) == 1
        for qualified, key in qualified_to_key.items():
            try:
                closes = df["Close"].dropna() if single else df[qualified]["Close"].dropna()
            except (KeyError, AttributeError):
                closes = None
            cache_key = (key[0], key[1], today_iso)
            with _HISTORY_LOCK:
                _HISTORY_CACHE[cache_key] = (
                    closes if (closes is not None and not closes.empty) else None
                )

# Rough FX to convert currency buckets to a common unit so we can show
# pct-of-total exposure. NOT used for any P&L calculation — purely for
# the "% of portfolio" chart on the risk panel. Honest fallback if FX
# isn't available.
_ROUGH_FX_TO_INR = {"INR": 1.0, "USD": 83.0, "AED": 22.6}


@router.get("", response_model=InsightsOut)
def get_insights(
    force: bool = Query(False, description="Skip the cache and rebuild now"),
) -> InsightsOut:
    """Return the Insights payload. Cached on disk between calls and
    only rebuilt when the user explicitly refreshes or the portfolio
    fingerprint changes (holdings added/removed/qty changed)."""
    fp = _portfolio_fingerprint()
    with _INSIGHTS_LOCK:
        if not force:
            cached = _insights_load()
            if cached and cached.get("fp") == fp:
                try:
                    return InsightsOut(**cached["payload"])
                except Exception:
                    # Schema drift since the cache was written; rebuild.
                    pass

        # Force the dashboard cache to rebuild too — the user pressed Refresh
        # because they want everything fresh, not just the post-aggregation
        # panels.
        payload = get_dashboard(force=force)
        rows = payload["rows"]
        out = InsightsOut(
            conviction=_conviction_panel(rows),
            watchlist=_watchlist_panel(),
            indices=_indices_panel(),
            risk=_risk_panel(rows),
            signal_changes=_signal_changes_panel(rows, payload.get("loaded_at", "")),
            upcoming_earnings=_earnings_panel(rows),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        _insights_save({"fp": fp, "payload": out.model_dump()})
        return out


# --- Conviction board ---

def _conviction_panel(rows) -> list[ConvictionRow]:
    out: list[ConvictionRow] = []
    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        v = c.get("score_value")
        if v is None:
            continue
        if abs(float(v)) < _CONVICTION_ABS_SCORE:
            continue
        if int(c.get("rule_count", 0)) < 1:
            continue
        out.append(ConvictionRow(
            row=card_row_to_out(r, digest_dir=_DIGEST_DIR),
            direction="bullish" if v > 0 else "bearish",
            rule_count=int(c.get("rule_count", 0)),
            rule_notes=list(c.get("rule_notes") or [])[:4],
        ))
    out.sort(key=lambda x: abs(x.row.score_value or 0.0), reverse=True)
    return out


# --- Watchlist scan ---

def _watchlist_panel() -> list[CardRowOut]:
    store = get_store()
    items = store.watchlist_all()
    out: list[CardRowOut] = []
    for ticker, market_code, _note, _added in items:
        try:
            market = Market.from_code(market_code)
        except Exception:
            continue
        row = build_card_for(ticker, market)
        out.append(card_row_to_out(row, digest_dir=_DIGEST_DIR))
    # Sort by absolute score so the strongest signals float to the top.
    out.sort(key=lambda r: abs(r.score_value or 0.0), reverse=True)
    return out


# --- Market pulse (indices) ---

def _indices_panel() -> list[IndexSnapshot]:
    """Bellwether indices. We silently skip indices yfinance can't price
    (e.g. UAE indices ^DFMGI / ^ADI have spotty coverage). Showing
    rows with 'no history available' adds noise the user can't act on."""
    snaps: list[IndexSnapshot] = []
    src = get_source()
    for symbol, name, market_code in INDICES:
        try:
            mkt = Market.from_code(market_code)
        except Exception:
            continue
        try:
            row = build_card_for(symbol, mkt)
        except Exception:
            continue   # silently drop — no usable data
        c = row.card
        # Card-level error or missing price → drop from market pulse rather
        # than showing a red error tile every load.
        if c.get("error") or c.get("price") is None:
            continue
        snaps.append(IndexSnapshot(
            symbol=symbol,
            name=name,
            market=market_code,
            price=c.get("price"),
            change_pct=c.get("change_pct"),
            rsi=c.get("rsi"),
            trend=c.get("trend"),
            score_label=c.get("score_label"),
            error=None,
        ))
        _ = src   # quiet unused-source warning
    return snaps


# --- Portfolio risk view ---

def _risk_panel(rows) -> RiskPanel:
    top_weights: list[RiskTopWeight] = []
    for r in rows:
        if r.weight_pct is None or r.holding is None:
            continue
        c = r.card
        top_weights.append(RiskTopWeight(
            symbol=c.get("symbol", ""),
            market=c.get("market_code", ""),
            weight_pct=float(r.weight_pct),
            market_value=float(r.market_value),
            currency_symbol=c.get("currency_symbol", ""),
        ))
    top_weights.sort(key=lambda x: x.weight_pct, reverse=True)
    top_weights = top_weights[:5]

    # Currency exposure normalised through approximate FX so the panel can
    # show a single % split. The note in the schema flags this is approximate.
    totals_in_inr: dict[str, float] = {}
    symbols: dict[str, str] = {}
    for r in rows:
        if r.holding is None or r.card.get("error"):
            continue
        ccy = r.holding.currency
        fx = _ROUGH_FX_TO_INR.get(ccy, 1.0)
        totals_in_inr[ccy] = totals_in_inr.get(ccy, 0.0) + r.market_value * fx
        symbols[ccy] = r.card.get("currency_symbol", "")
    grand = sum(totals_in_inr.values()) or 1.0
    currency_exposure = [
        CurrencyExposure(
            currency=ccy,
            currency_symbol=symbols.get(ccy, ""),
            market_value=v,
            pct_of_total_inr=v / grand * 100.0,
        )
        for ccy, v in sorted(totals_in_inr.items(), key=lambda kv: kv[1], reverse=True)
    ]

    held = [r for r in rows if r.holding and not r.card.get("error")]
    winners = sorted(
        (r for r in held if r.pnl > 0), key=lambda r: r.pnl_pct, reverse=True,
    )[:3]
    losers = sorted(
        (r for r in held if r.pnl < 0), key=lambda r: r.pnl_pct,
    )[:3]

    return RiskPanel(
        top_weights=top_weights,
        currency_exposure=currency_exposure,
        biggest_winners=[card_row_to_out(r, digest_dir=_DIGEST_DIR) for r in winners],
        biggest_losers=[card_row_to_out(r, digest_dir=_DIGEST_DIR) for r in losers],
    )


# --- Signal changes ---

def _signal_changes_panel(rows, current_captured_at: str) -> list[SignalChange]:
    if not current_captured_at:
        return []
    store = get_store()
    out: list[SignalChange] = []
    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        v = c.get("score_value")
        lbl = c.get("score_label")
        sym = c.get("symbol")
        mkt = c.get("market_code")
        if v is None or not lbl or not sym or not mkt:
            continue
        prev = store.signal_previous(sym, mkt, current_captured_at)
        if prev is None:
            continue
        prev_val, prev_lbl, prev_at = prev
        if prev_lbl == lbl:
            continue
        out.append(SignalChange(
            symbol=sym,
            market=mkt,
            previous_label=prev_lbl,
            current_label=lbl,
            previous_value=prev_val,
            current_value=float(v),
            captured_previous_at=prev_at,
        ))
    # Most dramatic moves first.
    out.sort(key=lambda s: abs(s.current_value - s.previous_value), reverse=True)
    return out


# --- Upcoming earnings ---

def _earnings_panel(rows) -> list[EarningsItem]:
    import yfinance as yf

    today = datetime.now().date()
    horizon = today + timedelta(days=30)
    out: list[EarningsItem] = []
    seen: set[tuple[str, str]] = set()

    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        sym = c.get("symbol")
        mkt_code = c.get("market_code")
        if not sym or not mkt_code:
            continue
        key = (sym, mkt_code)
        if key in seen:
            continue
        seen.add(key)

        try:
            market = Market.from_code(mkt_code)
            qualified = market.format_ticker(sym)
            ticker = yf.Ticker(qualified)
            date_value = _earnings_date_from_ticker(ticker)
        except Exception:
            continue

        if date_value is None:
            continue
        days = (date_value - today).days
        if days < 0 or days > 30:
            continue
        out.append(EarningsItem(
            symbol=sym,
            market=mkt_code,
            company=None,
            earnings_date=date_value.isoformat(),
            days_until=days,
        ))
        if date_value > horizon:
            break

    out.sort(key=lambda e: e.days_until)
    return out


def _earnings_date_from_ticker(ticker) -> Optional["date"]:
    """Pull the next earnings date from yfinance, tolerant of its shape changes."""
    from datetime import date as date_t

    cal = None
    try:
        cal = ticker.calendar
    except Exception:
        cal = None

    if isinstance(cal, dict):
        v = cal.get("Earnings Date") or cal.get("earnings_date") or cal.get("Earnings date")
        if isinstance(v, list) and v:
            v = v[0]
        if hasattr(v, "date"):
            return v.date()
        if isinstance(v, date_t):
            return v

    try:
        df = ticker.earnings_dates
    except Exception:
        df = None
    if df is not None and hasattr(df, "index") and len(df) > 0:
        future = [d for d in df.index if hasattr(d, "date") and d.date() >= datetime.now().date()]
        if future:
            return min(future).date()

    return None


# --- Discovery ---


@router.get("/discover", response_model=DiscoveryOut)
def discover(
    markets: Optional[str] = Query(
        None,
        description="Comma-separated market codes (NSE,US,DFM,ADX). Default: all four.",
    ),
    min_score: float = Query(2.0, description="Minimum score to surface (default 2.0 = Buy threshold)"),
    limit_per_market: int = Query(10, ge=1, le=50),
    refresh: bool = Query(False, description="Skip cache and re-scan now"),
) -> DiscoveryOut:
    """Scan curated per-market universes and return high-scoring names
    that aren't in the user's portfolio."""
    requested = _parse_markets(markets) or list(_DEFAULT_MARKETS)

    # Build the exclusion set once from current holdings.
    store = get_store()
    holdings = store.all()
    exclude = [(h.ticker, h.market_code) for h in holdings]

    # Cache key includes the request shape so different filter combos don't
    # collide. The dominant cost is the universe scan, so we cache the
    # per-market raw scan and slice/filter at request time.
    cached = _discovery_load() if not refresh else None
    by_market: dict[str, list[DiscoveryRowOut]] = {}
    universe_sizes: dict[str, int] = {}

    with _DISCOVERY_LOCK:
        cache: dict = cached or {"per_market": {}, "saved_ts": 0.0}
        per_market_cache: dict = cache.get("per_market", {})
        cache_age = _time.time() - cache.get("saved_ts", 0.0)
        fresh_cache = cache_age < _DISCOVERY_CACHE_TTL_S and not refresh

        for code in requested:
            try:
                market = Market.from_code(code)
            except Exception:
                continue
            universe_sizes[code] = len(universe_for(market))

            if fresh_cache and code in per_market_cache:
                rows = per_market_cache[code]
            else:
                discovered = scan_universe(
                    market,
                    exclude=exclude,
                    build_card=build_card_for,
                    min_score=0.0,            # store everything; filter below
                    limit=10_000,
                )
                rows = [DiscoveryRowOut(
                    symbol=d.symbol,
                    market=d.market_code,
                    currency_symbol=d.currency_symbol,
                    price=d.price,
                    change_pct=d.change_pct,
                    score_value=d.score_value,
                    score_label=d.score_label,
                    rsi=d.rsi,
                    trend=d.trend,
                    sentiment_label=d.sentiment_label,
                    sector=d.sector,
                    rule_count=d.rule_count,
                    rule_names=d.rule_names,
                    error=d.error,
                ) for d in discovered]
                per_market_cache[code] = rows

            # Apply request-time filters.
            filtered = [
                r for r in rows
                if r.score_value is not None and r.score_value >= min_score
            ]
            filtered.sort(key=lambda r: r.score_value or 0.0, reverse=True)
            by_market[code] = filtered[:limit_per_market]

        # Save back to disk (covers both refresh and first-time fills).
        if not fresh_cache or refresh:
            cache["per_market"] = per_market_cache
            cache["saved_ts"] = _time.time()
            _discovery_save(cache)

    return DiscoveryOut(
        by_market=by_market,
        universe_sizes=universe_sizes,
        excluded_count=len(exclude),
        scanned_at=datetime.fromtimestamp(cache.get("saved_ts", _time.time())).strftime("%Y-%m-%d %H:%M"),
        cached=bool(cached and not refresh),
    )


_DEFAULT_MARKETS = ("NSE", "US", "DFM", "ADX")


def _parse_markets(s: Optional[str]) -> list[str]:
    if not s:
        return []
    return [m.strip().upper() for m in s.split(",") if m.strip()]


def _discovery_load() -> Optional[dict]:
    if not _DISCOVERY_CACHE_FILE.exists():
        return None
    try:
        with _DISCOVERY_CACHE_FILE.open("rb") as f:
            return pickle.load(f)
    except (pickle.UnpicklingError, EOFError, AttributeError, ImportError):
        try:
            _DISCOVERY_CACHE_FILE.unlink()
        except OSError:
            pass
        return None


def _discovery_save(payload: dict) -> None:
    try:
        with _DISCOVERY_CACHE_FILE.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError:
        pass


# --- Diversification ---


@router.get("/diversification", response_model=DiversificationOut)
def diversification() -> DiversificationOut:
    """Classify the user's holdings into broad asset buckets and surface
    well-known instruments per gap. Information only — not advice."""
    payload = get_dashboard()
    rows = payload["rows"]

    # Build (symbol, market, market_value, 1) tuples for the summariser.
    items: list[tuple[str, str, float, int]] = []
    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        sym = c.get("symbol")
        mkt = c.get("market_code")
        if not sym or not mkt:
            continue
        items.append((sym, mkt, float(r.market_value or 0.0), 1))

    div = summarise_diversification(items)

    return DiversificationOut(
        by_asset=[
            AssetSliceOut(
                asset_class=s.asset_class,
                market_value=round(s.market_value, 2),
                pct=round(s.pct, 2),
                n_positions=s.n_positions,
            )
            for s in div.by_asset
        ],
        total_value=round(div.total_value, 2),
        gaps=list(div.gaps),
        suggestions={
            cls: [
                DiversificationInstrumentOut(
                    symbol=i.symbol,
                    market=i.market,
                    name=i.name,
                    asset_class=i.asset_class,
                    description=i.description,
                )
                for i in instruments
            ]
            for cls, instruments in div.suggestions.items()
        },
    )


# --- Tax-loss harvesting ---


@router.get("/tax-harvest", response_model=TaxHarvestOut)
def tax_harvest() -> TaxHarvestOut:
    """Surface holdings currently in the red where realising the loss
    would offset capital gains. Pure math; rates are configurable
    defaults — verify with your accountant before acting."""
    payload = get_dashboard()
    rows = payload["rows"]

    store = get_store()
    by_key = {(h.ticker.upper(), h.market_code.upper()): h for h in store.all()}
    currency_symbols: dict[str, str] = {}

    # Build (holding, market_value, price) tuples.
    items = []
    for r in rows:
        c = r.card
        if c.get("error"):
            continue
        sym = (c.get("symbol") or "").upper()
        mkt = (c.get("market_code") or "").upper()
        h = by_key.get((sym, mkt))
        if h is None:
            continue
        price = c.get("price")
        if price is None or r.market_value is None:
            continue
        items.append((h, float(r.market_value), float(price)))
        # collect currency symbols for display
        sym_char = c.get("currency_symbol") or h.currency
        currency_symbols[h.currency] = sym_char

    candidates = find_harvest_candidates(items, currency_symbols=currency_symbols)

    # Sum savings per currency (we don't FX-convert; same rule as the
    # rest of the app).
    totals: dict[str, float] = {}
    for c in candidates:
        totals[c.currency_symbol] = totals.get(c.currency_symbol, 0.0) + c.est_tax_saving

    return TaxHarvestOut(
        candidates=[
            HarvestCandidateOut(
                ticker=c.ticker,
                market=c.market,
                currency_symbol=c.currency_symbol,
                shares=c.shares,
                cost_basis=round(c.cost_basis, 2),
                price=round(c.price, 2),
                unrealised_loss=round(c.unrealised_loss, 2),
                loss_pct=round(c.loss_pct, 2),
                days_held=c.days_held,
                term=c.term,
                tax_rate=c.tax_rate,
                est_tax_saving=round(c.est_tax_saving, 2),
                notes=c.notes,
            )
            for c in candidates
        ],
        total_saving_by_currency={k: round(v, 2) for k, v in totals.items()},
    )


# --- Performance attribution ---


_VALID_PERIODS = ("1w", "1m", "3m", "6m", "ytd", "1y", "lifetime")


def _closes_for(symbol: str, market_code: str):
    """Daily closes Series cached per (ticker, market, today). One
    yfinance call per holding per day; subsequent requests within the
    same day reuse the cached series."""
    today = date.today().isoformat()
    key = (symbol.upper(), market_code.upper(), today)
    with _HISTORY_LOCK:
        if key in _HISTORY_CACHE:
            return _HISTORY_CACHE[key]
    try:
        market = Market.from_code(market_code)
    except Exception:
        return None
    try:
        df = get_source().get_history(symbol, market, period="1y", interval="1d")
    except Exception:
        return None
    closes = df["close"] if (df is not None and "close" in df.columns) else None
    with _HISTORY_LOCK:
        _HISTORY_CACHE[key] = closes
    return closes


@router.get("/performance", response_model=PerformanceOut)
def performance(
    period: str = Query("ytd", description="1w | 1m | 3m | 6m | ytd | 1y | lifetime"),
) -> PerformanceOut:
    """Decompose total portfolio return over a period into per-holding
    contributions, grouped by currency. Pure math — no opinion."""
    if period not in _VALID_PERIODS:
        period = "ytd"

    try:
        payload = get_dashboard()
    except Exception as e:
        # Surface as an empty result with the message rather than 500-ing.
        return PerformanceOut(
            period=period,
            buckets=[],
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            note=f"Could not load portfolio: {e}",
        )

    rows = payload.get("rows", [])
    store = get_store()
    try:
        by_key = {(h.ticker.upper(), h.market_code.upper()): h for h in store.all()}
    except Exception:
        by_key = {}

    # Pre-warm the closes cache in one bulk yfinance call. The lifetime
    # path doesn't need history; skip warmup in that case.
    if period != "lifetime":
        try:
            tickers_needed: list[tuple[str, str]] = []
            for r in rows:
                c = r.card if hasattr(r, "card") else {}
                if c.get("error"):
                    continue
                sym = (c.get("symbol") or "").upper()
                mkt = (c.get("market_code") or "").upper()
                if sym and mkt and (sym, mkt) in by_key:
                    tickers_needed.append((sym, mkt))
            if tickers_needed:
                _bulk_warm_history(tickers_needed)
        except Exception:
            pass  # bulk warm is best-effort; per-row fallback still works

    inputs = []
    for r in rows:
        try:
            c = r.card if hasattr(r, "card") else {}
            if c.get("error"):
                continue
            sym = (c.get("symbol") or "").upper()
            mkt = (c.get("market_code") or "").upper()
            h = by_key.get((sym, mkt))
            if h is None or h.shares <= 0 or h.cost_basis is None:
                continue
            price = c.get("price")
            mv = getattr(r, "market_value", None)
            if price is None or mv is None:
                continue

            closes = None if period == "lifetime" else _closes_for(sym, mkt)

            inputs.append((
                h.ticker,
                h.market_code,
                h.currency,
                c.get("currency_symbol") or h.currency,
                float(h.shares),
                float(h.cost_basis),
                float(price),
                float(mv),
                h.date_added,
                closes,
            ))
        except Exception:
            # One bad row shouldn't take down the whole endpoint.
            continue

    try:
        buckets = attribute(inputs, period=period)  # type: ignore[arg-type]
    except Exception as e:
        return PerformanceOut(
            period=period,
            buckets=[],
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            note=f"Computation failed: {e}",
        )

    return PerformanceOut(
        period=period,
        buckets=[
            AttributionBucketOut(
                currency=b.currency,
                currency_symbol=b.currency_symbol,
                total_return_pct=round(b.total_return_pct, 3),
                total_value=round(b.total_value, 2),
                rows=[
                    AttributionRowOut(
                        ticker=r.ticker,
                        market=r.market,
                        currency=r.currency,
                        currency_symbol=r.currency_symbol,
                        start_price=round(r.start_price, 2),
                        current_price=round(r.current_price, 2),
                        return_pct=round(r.return_pct, 3),
                        weight_pct=round(r.weight_pct, 3),
                        contribution_pct=round(r.contribution_pct, 3),
                        market_value=round(r.market_value, 2),
                        period_label=r.period_label,
                        shares=r.shares,
                    )
                    for r in b.rows
                ],
            )
            for b in buckets
        ],
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


# --- Capital gains running tally ---


def _resolve_fy_for_entry(market: str, realized_at_iso: str) -> str:
    """FY for a particular realized-at date, market-aware."""
    try:
        d = datetime.fromisoformat(realized_at_iso).date()
    except Exception:
        d = datetime.now().date()
    return current_fy(market.upper(), today=d)


@router.post("/capital-gains/entries", response_model=RealizedGainOut)
def capital_gains_add(entry: RealizedGainIn) -> RealizedGainOut:
    if entry.term not in ("short", "long"):
        raise HTTPException(status_code=400, detail="term must be 'short' or 'long'")
    try:
        datetime.fromisoformat(entry.realized_at)
    except Exception:
        raise HTTPException(status_code=400, detail="realized_at must be ISO date YYYY-MM-DD")
    fy = _resolve_fy_for_entry(entry.market, entry.realized_at)
    store = get_store()
    gid = store.realized_gain_add(
        ticker=entry.ticker, market=entry.market, qty=entry.qty,
        gain_amount=entry.gain_amount, currency=entry.currency,
        term=entry.term, realized_at=entry.realized_at, fy=fy,
        note=entry.note or "",
    )
    # Pull back to return the canonical row.
    for row in store.realized_gains_list(fy=fy):
        if int(row["id"]) == gid:
            return RealizedGainOut(**row)
    raise HTTPException(status_code=500, detail="insert succeeded but row not found")


@router.delete("/capital-gains/entries/{gain_id}")
def capital_gains_remove(gain_id: int) -> dict:
    ok = get_store().realized_gain_remove(gain_id)
    if not ok:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"ok": True}


@router.get("/capital-gains", response_model=CapitalGainsOut)
def capital_gains(
    fy: Optional[str] = Query(
        None,
        description="Financial year (e.g. '2025-26' for India, '2025' for US). Defaults to current FY per market.",
    ),
) -> CapitalGainsOut:
    """Aggregate realized gains for the current FY + projected tax,
    plus the offset available from currently-unrealised losses (the
    harvest panel). Defensive: every external call is wrapped so the
    panel never 500s — failures degrade to empty state with a note."""
    store = get_store()
    note: Optional[str] = None

    # Decide which FY string to use per market.
    today = date.today()
    fy_by_market: dict[str, str] = {
        "NSE": fy or current_fy("NSE", today),
        "BSE": fy or current_fy("BSE", today),
        "US": fy or current_fy("US", today),
    }

    # Pull entries for each unique FY string we care about. SQLite errors
    # (e.g. table missing after a schema migration hiccup) shouldn't crash
    # the endpoint.
    all_entries: list[dict] = []
    try:
        seen_fys = set(fy_by_market.values())
        for f in seen_fys:
            all_entries.extend(store.realized_gains_list(fy=f))
    except Exception as e:
        note = f"Could not load realized-gain entries: {e}"

    currency_symbols: dict[str, str] = {"INR": "₹", "USD": "$", "AED": "د.إ"}
    try:
        buckets = summarise_realized_gains(all_entries, currency_symbols=currency_symbols)
    except Exception as e:
        buckets = []
        note = note or f"Could not summarise: {e}"

    total_tax_by_cur: dict[str, float] = {}
    for b in buckets:
        sym = b.currency_symbol
        total_tax_by_cur[sym] = total_tax_by_cur.get(sym, 0.0) + b.est_tax_due_after_exempt

    # Harvest offset: re-use the harvest panel's logic. If the harvest
    # endpoint itself fails (yfinance throttling, missing holdings cache,
    # etc.) just skip the offset rather than failing the whole tally.
    harvest_offset_by_cur: dict[str, float] = {}
    try:
        harvest = tax_harvest()
        harvest_offset_by_cur = dict(harvest.total_saving_by_currency)
    except Exception as e:
        note = note or f"Harvest offset unavailable: {e}"

    net_tax_after: dict[str, float] = {}
    for sym, tax in total_tax_by_cur.items():
        offset = harvest_offset_by_cur.get(sym, 0.0)
        net_tax_after[sym] = max(0.0, round(tax - offset, 2))

    # Build entry rows defensively — a single malformed row in the DB
    # shouldn't take down the whole response.
    entry_outs: list[RealizedGainOut] = []
    for e in all_entries:
        try:
            entry_outs.append(RealizedGainOut(**e))
        except Exception:
            continue

    out = CapitalGainsOut(
        fy_by_market=fy_by_market,
        buckets=[
            CapitalGainsBucketOut(
                currency=b.currency,
                currency_symbol=b.currency_symbol,
                term=b.term,
                realized_gain=round(b.realized_gain, 2),
                realized_loss=round(b.realized_loss, 2),
                net=round(b.net, 2),
                n_entries=b.n_entries,
                tax_rate=b.tax_rate,
                est_tax_due=round(b.est_tax_due, 2),
                ltcg_exempt_applied=round(b.ltcg_exempt_applied, 2),
                est_tax_due_after_exempt=round(b.est_tax_due_after_exempt, 2),
            )
            for b in buckets
        ],
        entries=entry_outs,
        total_tax_due_by_currency={k: round(v, 2) for k, v in total_tax_by_cur.items()},
        harvest_offset_by_currency={k: round(v, 2) for k, v in harvest_offset_by_cur.items()},
        net_tax_after_harvest_by_currency=net_tax_after,
    )
    if note:
        out.note = f"{note}. " + out.note
    return out
