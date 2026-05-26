"""Backtest engine.

Strategy (intentionally simple — the score IS the model; this measures
that model honestly):
  - Long when composite score >= enter_threshold (default +2.0, i.e. Buy)
  - Flat when score <= exit_threshold (default 0, i.e. neutral/Hold lean
    down)
  - Hold position otherwise (hysteresis prevents whipsaw)
  - Decisions taken on bar i act at bar i+1's open (no same-bar peek)
  - Transaction cost charged on each entry and exit

Lookahead avoidance: every indicator series is computed once over the full
history, but each is naturally causal — rolling/EMA windows look BACKWARD
only. We never read score[i] before deciding what to do at bar i+1.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..scoring import DEFAULT_WEIGHTS, Weights
from ..technical import indicators as ind
from ..technical.patterns import bearish_engulfing, bullish_engulfing, hammer
from .result import BacktestResult, Trade


def compute_score_series(
    df: pd.DataFrame,
    *,
    weights: Weights = DEFAULT_WEIGHTS,
    cross_lookback: int = 60,
) -> pd.Series:
    """Score at each bar, computed using only data up to and including that
    bar. The cross flag at bar i looks at crosses in the previous
    `cross_lookback` bars — strictly backward."""
    close = df["close"]

    rsi_s = ind.rsi(close, 14)
    macd_df = ind.macd(close)
    bb_df = ind.bollinger(close)
    sma50 = ind.sma(close, 50)
    sma200 = ind.sma(close, 200)

    gc = ind.golden_cross(close, fast=50, slow=200)
    dc = ind.death_cross(close, fast=50, slow=200)
    # Rolling 'any in last N bars' — uses .shift(1) implicitly via the bool
    # series indexed at the cross bar. To stay strictly backward at bar i,
    # we want "did a cross happen in bars i-cross_lookback+1..i" — which is
    # exactly rolling(window).max() over the bool series.
    gc_recent = gc.rolling(cross_lookback, min_periods=1).max().astype(bool)
    dc_recent = dc.rolling(cross_lookback, min_periods=1).max().astype(bool)

    bull_eng = bullish_engulfing(df)
    bear_eng = bearish_engulfing(df)
    hammer_s = hammer(df)
    # doji is intentionally neutral in scoring

    n = len(df)
    score_vals = np.zeros(n)

    # Vectorise as much as we can. Each contribution is computed as a series.
    contrib = pd.DataFrame(index=df.index)

    # Trend label per bar
    trend_score = pd.Series(0.0, index=df.index)
    is_uptrend = (close > sma50) & (sma50 > sma200)
    is_downtrend = (close < sma50) & (sma50 < sma200)
    trend_score = trend_score.where(~is_uptrend, +weights.trend)
    trend_score = trend_score.where(~is_downtrend, -weights.trend)
    contrib["trend"] = trend_score

    # RSI extremes
    rsi_score = pd.Series(0.0, index=df.index)
    rsi_score = rsi_score.where(~(rsi_s <= weights.rsi_oversold), +weights.rsi)
    rsi_score = rsi_score.where(~(rsi_s >= weights.rsi_overbought), -weights.rsi)
    contrib["rsi"] = rsi_score

    # MACD
    macd_score = pd.Series(0.0, index=df.index)
    macd_bullish = (macd_df["macd"] > macd_df["signal"]) & (macd_df["hist"] > 0)
    macd_bearish = (macd_df["macd"] < macd_df["signal"]) & (macd_df["hist"] < 0)
    macd_score = macd_score.where(~macd_bullish, +weights.macd)
    macd_score = macd_score.where(~macd_bearish, -weights.macd)
    contrib["macd"] = macd_score

    # Bollinger
    bb_score = pd.Series(0.0, index=df.index)
    near_lower = bb_df["pct_b"] <= 0.2
    near_upper = bb_df["pct_b"] >= 0.8
    bb_score = bb_score.where(~near_lower, +weights.bollinger)
    bb_score = bb_score.where(~near_upper, -weights.bollinger)
    contrib["bollinger"] = bb_score

    # Cross
    cross_score = pd.Series(0.0, index=df.index)
    cross_score = cross_score.where(~gc_recent, +weights.cross)
    cross_score = cross_score.where(~dc_recent, -weights.cross)
    contrib["cross"] = cross_score

    # Patterns (bullish engulfing / hammer / bearish engulfing)
    pat = pd.Series(0.0, index=df.index)
    pat = pat.where(~(bull_eng | hammer_s), pat + weights.pattern)
    pat = pat.where(~bear_eng, pat - weights.pattern)
    # Clip so multiple patterns on one bar don't dominate
    pat = pat.clip(lower=-weights.pattern, upper=weights.pattern)
    contrib["pattern"] = pat

    raw = contrib.sum(axis=1)
    # Clamp to [-10, +10] to match compute_score.
    raw = raw.clip(lower=-10.0, upper=10.0)
    # Fill warmup NaNs (where indicators aren't ready) with 0 so the
    # strategy is naturally flat at the start.
    return raw.fillna(0.0)


def run_backtest(
    df: pd.DataFrame,
    *,
    weights: Weights = DEFAULT_WEIGHTS,
    enter_threshold: float = 2.0,
    exit_threshold: float = 0.0,
    transaction_cost_pct: float = 0.1,
    warmup_bars: int = 200,
) -> BacktestResult:
    """Walk the price series, applying the score-driven long/flat strategy.

    `warmup_bars` ensures we don't trade until SMA200 (and friends) are
    valid. Default 200 matches the long-SMA window.
    """
    if len(df) < warmup_bars + 5:
        raise ValueError(
            f"need at least {warmup_bars + 5} bars to backtest, got {len(df)}"
        )

    close = df["close"]
    opens = df["open"]
    score = compute_score_series(df, weights=weights)

    # State: position in {0, 1}. Decisions at bar i act at bar i+1's open.
    n = len(df)
    in_market = np.zeros(n, dtype=bool)
    position = 0  # current state

    cost = transaction_cost_pct / 100.0
    equity = np.ones(n)
    trades: list[Trade] = []
    entry_idx: Optional[int] = None

    for i in range(n):
        if i < warmup_bars:
            in_market[i] = False
            equity[i] = 1.0
            continue

        # Carry equity by today's return *if* we held into today.
        if i > 0:
            if in_market[i - 1] and not (i - 1 == entry_idx):
                # Already in market: gain today's close-over-close return.
                day_ret = close.iloc[i] / close.iloc[i - 1] - 1.0
                equity[i] = equity[i - 1] * (1.0 + day_ret)
            else:
                equity[i] = equity[i - 1]
        # Action taken on bar i-1's signal, executed at bar i's open.
        # i.e. we look at score.iloc[i-1] and trade at opens.iloc[i].
        if i >= 1:
            signal = score.iloc[i - 1]
            if position == 0 and signal >= enter_threshold:
                # Enter long at today's open.
                entry_price = float(opens.iloc[i])
                # Pay cost on entry (reduces equity).
                equity[i] *= (1.0 - cost)
                # Apply the gap from today's open to today's close.
                day_ret = close.iloc[i] / entry_price - 1.0
                equity[i] *= (1.0 + day_ret)
                position = 1
                in_market[i] = True
                entry_idx = i
            elif position == 1 and signal <= exit_threshold:
                # Exit long at today's open.
                exit_price = float(opens.iloc[i])
                # Reverse out the close-over-close return we already accrued
                # for today, since we actually exited at the open.
                if in_market[i - 1]:
                    day_ret_was = close.iloc[i] / close.iloc[i - 1] - 1.0
                    equity[i] = equity[i - 1] * (1.0 + (exit_price / close.iloc[i - 1] - 1.0))
                # Pay cost on exit.
                equity[i] *= (1.0 - cost)
                # Record trade
                e_date = df.index[entry_idx].date() if hasattr(df.index[entry_idx], "date") else df.index[entry_idx]
                x_date = df.index[i].date() if hasattr(df.index[i], "date") else df.index[i]
                entry_price = float(opens.iloc[entry_idx])
                # Trade return: net of costs (entry cost + exit cost)
                gross = exit_price / entry_price - 1.0
                net = (1.0 + gross) * (1.0 - cost) * (1.0 - cost) - 1.0
                trades.append(Trade(
                    entry_date=e_date, entry_price=entry_price,
                    exit_date=x_date, exit_price=exit_price,
                    return_pct=net * 100.0,
                ))
                position = 0
                in_market[i] = False
                entry_idx = None
            else:
                in_market[i] = position == 1

    # If we end the run still holding, close at the last close (mark-to-market
    # trade record so win-rate reflects open positions honestly).
    if position == 1 and entry_idx is not None:
        last = n - 1
        exit_price = float(close.iloc[last])
        entry_price = float(opens.iloc[entry_idx])
        gross = exit_price / entry_price - 1.0
        net = (1.0 + gross) * (1.0 - cost) * (1.0 - cost) - 1.0
        e_date = df.index[entry_idx].date() if hasattr(df.index[entry_idx], "date") else df.index[entry_idx]
        x_date = df.index[last].date() if hasattr(df.index[last], "date") else df.index[last]
        trades.append(Trade(
            entry_date=e_date, entry_price=entry_price,
            exit_date=x_date, exit_price=exit_price,
            return_pct=net * 100.0,
        ))

    # Returns
    final_eq = float(equity[-1])
    strat_ret_pct = (final_eq - 1.0) * 100.0

    first_traded_idx = warmup_bars
    first_close = float(close.iloc[first_traded_idx])
    last_close = float(close.iloc[-1])
    hold_ret_pct = (last_close / first_close - 1.0) * 100.0

    # Max drawdown on the strategy equity
    eq_series = pd.Series(equity)
    running_max = eq_series.cummax()
    dd = (eq_series / running_max - 1.0)
    max_dd_pct = float(dd.min()) * 100.0 if len(dd) else 0.0

    # Trade stats
    n_trades = len(trades)
    win_rate = None
    avg_hold = None
    if n_trades > 0:
        wins = sum(1 for t in trades if t.return_pct > 0)
        win_rate = wins / n_trades * 100.0
        holds = [(t.exit_date - t.entry_date).days for t in trades]
        avg_hold = sum(holds) / len(holds) if holds else None

    in_market_pct = float(in_market.sum()) / float(n - warmup_bars) * 100.0 if n > warmup_bars else 0.0

    def _to_date(v):
        return v.date() if hasattr(v, "date") else v

    return BacktestResult(
        start_date=_to_date(df.index[first_traded_idx]),
        end_date=_to_date(df.index[-1]),
        bars=n,
        strategy_return_pct=round(strat_ret_pct, 2),
        buy_and_hold_return_pct=round(hold_ret_pct, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        n_trades=n_trades,
        win_rate_pct=round(win_rate, 1) if win_rate is not None else None,
        avg_holding_days=round(avg_hold, 1) if avg_hold is not None else None,
        in_market_pct=round(in_market_pct, 1),
        transaction_cost_pct=transaction_cost_pct,
        score_threshold_enter=enter_threshold,
        score_threshold_exit=exit_threshold,
        sentiment_used=False,
        trades=trades,
    )
