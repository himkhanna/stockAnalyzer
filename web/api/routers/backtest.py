"""POST /api/backtest/{symbol}/{market} — lazy backtest for one ticker.

Surfaces the existing backtest engine through a JSON endpoint without
running it for every dashboard row (which would be expensive). Per
CLAUDE.md Phase 5, this is the honesty check that should accompany any
directional signal we display.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from portfolio_intel.backtest import run_backtest
from portfolio_intel.data.base import DataSourceError
from portfolio_intel.markets import Market

from ..schemas import BacktestOut
from ..state import DEFAULT_PERIOD, get_source

router = APIRouter()


@router.post("/{symbol}/{market}", response_model=BacktestOut)
def backtest_ticker(
    symbol: str,
    market: str,
    period: str = Query(DEFAULT_PERIOD),
    transaction_cost_pct: float = Query(0.1, ge=0.0, le=2.0),
) -> BacktestOut:
    sym = symbol.upper()
    mkt_code = market.upper()
    try:
        mkt = Market.from_code(mkt_code)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown market: {mkt_code}")

    try:
        df = get_source().get_history(sym, mkt, period=period)
    except DataSourceError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        result = run_backtest(df, transaction_cost_pct=transaction_cost_pct)
    except ValueError as e:
        # Most commonly "not enough history for indicators".
        raise HTTPException(status_code=422, detail=str(e))

    return BacktestOut(
        symbol=sym,
        market=mkt_code,
        start_date=result.start_date.isoformat(),
        end_date=result.end_date.isoformat(),
        bars=result.bars,
        strategy_return_pct=result.strategy_return_pct,
        buy_and_hold_return_pct=result.buy_and_hold_return_pct,
        edge_pct=result.edge_pct,
        beat_hold=result.beat_hold,
        max_drawdown_pct=result.max_drawdown_pct,
        n_trades=result.n_trades,
        win_rate_pct=result.win_rate_pct,
        avg_holding_days=result.avg_holding_days,
        in_market_pct=result.in_market_pct,
        transaction_cost_pct=result.transaction_cost_pct,
        score_threshold_enter=result.score_threshold_enter,
        score_threshold_exit=result.score_threshold_exit,
        sentiment_used=result.sentiment_used,
    )
