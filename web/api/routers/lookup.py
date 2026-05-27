"""GET /api/lookup/{symbol}?market=NSE&run_llm=false → analysis for any ticker."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from portfolio_intel.data.base import DataSourceError
from portfolio_intel.digest import build_digest
from portfolio_intel.markets import Market, parse_ticker
from portfolio_intel.render import render_digest_md

from ..schemas import LookupOut, CardRowOut, TradeSetupOut
from ..state import DB_PATH, DEFAULT_PERIOD, get_finnhub, get_source, get_store

router = APIRouter()


@router.get("/{raw_ticker}", response_model=LookupOut)
def lookup(
    raw_ticker: str,
    market: Optional[str] = Query(None),
    run_llm: bool = Query(False),
    period: str = Query(DEFAULT_PERIOD),
) -> LookupOut:
    explicit = Market.from_code(market) if market else None
    symbol, mkt = parse_ticker(raw_ticker, default_market=explicit)
    holding = get_store().get(symbol, mkt.code)
    try:
        digest = build_digest(
            symbol, mkt,
            data_source=get_source(),
            finnhub=get_finnhub(),
            period=period,
            run_llm=run_llm,
            holding=holding,
            run_backtest_too=True,
        )
    except (DataSourceError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    row = CardRowOut(
        symbol=symbol,
        market=mkt.code,
        currency=mkt.currency,
        currency_symbol=mkt.currency_symbol,
        price=digest.quote.price if digest.quote else digest.snapshot.close,
        change_pct=digest.quote.change_pct if digest.quote else None,
        stale=digest.quote.stale if digest.quote else False,
        score_value=digest.score.value,
        score_label=digest.score.label,
        rsi=digest.snapshot.rsi,
        trend=digest.snapshot.trend_label,
        sentiment_label=digest.sentiment.label,
        sentiment_total=digest.sentiment.total,
        setup=TradeSetupOut(
            valid=bool(digest.setup and digest.setup.valid),
            entry=digest.setup.entry if digest.setup else None,
            stop=digest.setup.stop if digest.setup else None,
            target=digest.setup.target if digest.setup else None,
            risk_reward=digest.setup.risk_reward if digest.setup else None,
        ),
        recent_closes=list(digest.recent_closes),
        shares=holding.shares if holding else None,
        cost_basis=holding.cost_basis if holding else None,
        market_value=(digest.snapshot.close * holding.shares) if holding else None,
        pnl=((digest.snapshot.close - holding.cost_basis) * holding.shares) if holding else None,
        overweight=False,
    )

    md = render_digest_md(digest, holding=holding) if run_llm else None
    return LookupOut(row=row, markdown=md)
