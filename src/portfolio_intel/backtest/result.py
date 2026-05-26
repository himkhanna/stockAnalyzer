"""Backtest result data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Trade:
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    return_pct: float  # net of transaction costs


@dataclass(frozen=True)
class BacktestResult:
    # Period
    start_date: date
    end_date: date
    bars: int

    # Returns (percent, e.g. 12.3 means +12.3%)
    strategy_return_pct: float
    buy_and_hold_return_pct: float

    # Risk
    max_drawdown_pct: float          # worst peak-to-trough on the strategy equity curve

    # Trade stats
    n_trades: int                    # completed round-trips
    win_rate_pct: float | None       # None when n_trades == 0
    avg_holding_days: float | None
    in_market_pct: float             # fraction of bars the strategy was long

    # Inputs (so the user can interpret correctly)
    transaction_cost_pct: float
    score_threshold_enter: float
    score_threshold_exit: float

    # Honesty caveat — printed on every render.
    sentiment_used: bool = False     # we don't have historical news for this

    trades: list[Trade] = field(default_factory=list)

    @property
    def edge_pct(self) -> float:
        """Strategy minus buy-and-hold, both net. Negative means hold won."""
        return self.strategy_return_pct - self.buy_and_hold_return_pct

    @property
    def beat_hold(self) -> bool:
        return self.strategy_return_pct > self.buy_and_hold_return_pct
