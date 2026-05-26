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
