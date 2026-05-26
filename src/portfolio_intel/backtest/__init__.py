"""Backtest layer — the honesty check on every directional signal.

CLAUDE.md, verbatim:
  "CRITICAL — avoid lookahead bias. The backtest must only use information
   available at each point in time. Account for transaction costs. Do NOT
   overfit the scoring weights to historical data. A rule that 'matched
   buy-and-hold' is an honest and common result — report it truthfully,
   do not tune until it looks good."

We measure the technical/rules engine only. Historical news/sentiment
archives aren't available for personal use, so the backtest scores each
historical bar with sentiment treated as neutral. That's a real
limitation and we surface it on every backtest output.
"""
from .engine import run_backtest, compute_score_series
from .result import BacktestResult, Trade

__all__ = ["run_backtest", "compute_score_series", "BacktestResult", "Trade"]
