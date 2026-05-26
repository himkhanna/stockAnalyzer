"""Scoring engine — turns deterministic signals into a single directional read.

CLAUDE.md's hard constraints govern this layer:
- The score is computed from indicator values and sentiment via fixed,
  config-driven weights. No LLM involved.
- Trade setups come from real swing highs/lows — never from the model.
- We don't attach a confidence percentage; that requires backtest data
  (Phase 5).
"""
from .score import Score, compute_score
from .rules import RuleHit, evaluate_rules
from .setup import TradeSetup, build_setup
from .weights import DEFAULT_WEIGHTS, Weights
from .position import PositionContext, build_position_context

__all__ = [
    "Score",
    "compute_score",
    "RuleHit",
    "evaluate_rules",
    "TradeSetup",
    "build_setup",
    "Weights",
    "DEFAULT_WEIGHTS",
    "PositionContext",
    "build_position_context",
]
