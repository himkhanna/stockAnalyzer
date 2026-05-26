"""Pydantic schemas for the API.

Schemas mirror the existing dataclasses in `portfolio_intel` but stay decoupled
so changes to internal representations don't accidentally leak into the wire
format. Keep them flat and JSON-friendly — the React app consumes these directly.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class HoldingIn(BaseModel):
    ticker: str
    market: str  # "US" | "NSE" | "BSE"
    shares: float
    cost_basis: float
    date_added: Optional[date] = None


class HoldingOut(BaseModel):
    ticker: str
    market: str
    shares: float
    cost_basis: float
    currency: str
    date_added: date


class TradeSetupOut(BaseModel):
    valid: bool
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    risk_reward: Optional[float] = None


class CardRowOut(BaseModel):
    symbol: str
    market: str
    currency: str
    currency_symbol: str

    price: Optional[float] = None
    change_pct: Optional[float] = None
    stale: bool = False

    score_value: Optional[float] = None
    score_label: Optional[str] = None

    rsi: Optional[float] = None
    trend: Optional[str] = None
    sentiment_label: Optional[str] = None
    sentiment_total: int = 0

    setup: TradeSetupOut = Field(default_factory=lambda: TradeSetupOut(valid=False))
    recent_closes: list[float] = []

    # Position-aware fields (None when not held)
    shares: Optional[float] = None
    cost_basis: Optional[float] = None
    market_value: Optional[float] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    weight_pct: Optional[float] = None
    overweight: bool = False

    has_digest: bool = False
    error: Optional[str] = None


class CurrencyBucketOut(BaseModel):
    currency: str
    currency_symbol: str
    market_value: float
    cost_total: float
    pnl: float
    pnl_pct: float
    n_positions: int


class DashboardOut(BaseModel):
    rows: list[CardRowOut]
    buckets: list[CurrencyBucketOut]
    signal_counts: dict[str, int]
    overweight_count: int
    winners_count: int
    losers_count: int
    loaded_at: str


class ImportErrorRow(BaseModel):
    reason: str
    isin: Optional[str] = None
    name: Optional[str] = None
    broker_symbol: Optional[str] = None


class ImportResultOut(BaseModel):
    imported: int
    errors: list[ImportErrorRow]


class DigestOut(BaseModel):
    symbol: str
    market: str
    markdown: str
    has_synthesis: bool
    generated_at: Optional[str] = None


class LookupOut(BaseModel):
    row: CardRowOut
    markdown: Optional[str] = None  # populated when run_llm=true


class BacktestOut(BaseModel):
    symbol: str
    market: str

    start_date: str
    end_date: str
    bars: int

    strategy_return_pct: float
    buy_and_hold_return_pct: float
    edge_pct: float
    beat_hold: bool

    max_drawdown_pct: float
    n_trades: int
    win_rate_pct: Optional[float] = None
    avg_holding_days: Optional[float] = None
    in_market_pct: float

    transaction_cost_pct: float
    score_threshold_enter: float
    score_threshold_exit: float

    sentiment_used: bool = False  # honest caveat — see backtest/__init__.py


# --- Insights page ---

class WatchlistItemIn(BaseModel):
    ticker: str
    market: str  # "US" | "NSE" | "BSE"
    note: Optional[str] = ""


class WatchlistItemOut(BaseModel):
    ticker: str
    market: str
    note: str
    date_added: str


class IndexSnapshot(BaseModel):
    symbol: str
    name: str
    market: str
    price: Optional[float] = None
    change_pct: Optional[float] = None
    rsi: Optional[float] = None
    trend: Optional[str] = None
    score_label: Optional[str] = None
    error: Optional[str] = None


class ConvictionRow(BaseModel):
    row: CardRowOut
    direction: str  # "bullish" | "bearish"
    rule_count: int
    rule_notes: list[str] = []


class SignalChange(BaseModel):
    symbol: str
    market: str
    previous_label: str
    current_label: str
    previous_value: float
    current_value: float
    captured_previous_at: str


class EarningsItem(BaseModel):
    symbol: str
    market: str
    company: Optional[str] = None
    earnings_date: str
    days_until: int


class RiskTopWeight(BaseModel):
    symbol: str
    market: str
    weight_pct: float
    market_value: float
    currency_symbol: str


class CurrencyExposure(BaseModel):
    currency: str
    currency_symbol: str
    market_value: float
    pct_of_total_inr: float  # in INR-equivalent units; see note in code


class RiskPanel(BaseModel):
    top_weights: list[RiskTopWeight]
    currency_exposure: list[CurrencyExposure]
    biggest_winners: list[CardRowOut]
    biggest_losers: list[CardRowOut]


class InsightsOut(BaseModel):
    conviction: list[ConvictionRow]
    watchlist: list[CardRowOut]
    indices: list[IndexSnapshot]
    risk: RiskPanel
    signal_changes: list[SignalChange]
    upcoming_earnings: list[EarningsItem]
    generated_at: str
    note: str = (
        "Signals are deterministic from the scoring engine + rules. "
        "They are decision support, not advice."
    )
