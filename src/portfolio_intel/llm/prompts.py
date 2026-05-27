"""Synthesis prompt builder.

This is the highest-leverage file in Phase 3+. The system prompt enforces
the honest tone CLAUDE.md demands. The user prompt is a structured fact
sheet — every number the model is allowed to reason over.

Hard constraints baked in:
- The model must NOT invent numbers. Prices, RSI, levels, the score, the
  trade-setup levels are facts provided in the prompt; the model only
  describes what they imply.
- No price targets from the model — target levels come from real swing
  highs/lows passed in below.
- No confidence percentages (those come from backtests in Phase 5).
- Output must end with the disclaimer.
- Hedged forward-looking language, no hype words.
"""
from __future__ import annotations

from typing import Optional

from ..backtest import BacktestResult
from ..data.models import NewsItem
from ..news.sentiment import SentimentSummary
from ..scoring import RuleHit, Score, TradeSetup
from ..technical.signals import TechnicalSnapshot


SYSTEM_PROMPT = """You are a careful analyst writing a short synthesis for a personal stock notebook.

Hard rules:
1. Use ONLY the numbers and facts in the user message. Do NOT invent prices,
   indicator values, support/resistance levels, price targets, scores, or
   percentages. If something is missing, say so or omit it.
2. The composite score, triggered rules, and trade-setup levels are provided
   as facts — explain what they imply, do not reinterpret or recompute them.
3. Stay measured. Describe what the signals imply; do not promise direction.
   Use hedged forward-looking language: "a pullback would not be unusual",
   "worth watching", "the main risk is", "the picture is mixed".
4. No hype words: "skyrocket", "moonshot", "guaranteed", "explode", etc.
5. No confidence percentages. No predictions of specific future prices
   beyond the provided target level.
6. Length: 4-7 sentences, one short paragraph. No headers, no bullet lists.
7. End with exactly this line on its own: Not advice — your call.
"""


def _fmt(v, fmt="{:.2f}"):
    return fmt.format(v) if v is not None else "n/a"


def build_user_prompt(
    symbol: str,
    market_code: str,
    currency_symbol: str,
    snap: TechnicalSnapshot,
    sentiment: SentimentSummary,
    news: list[NewsItem],
    *,
    score: Optional[Score] = None,
    rules: Optional[list[RuleHit]] = None,
    setup: Optional[TradeSetup] = None,
    backtest: Optional[BacktestResult] = None,
    position_note: Optional[str] = None,
) -> str:
    sym = currency_symbol

    lines: list[str] = [
        f"Ticker: {symbol}.{market_code}",
        f"Last close: {sym}{snap.close:,.2f}",
        "",
        "Technicals (computed deterministically — these are facts, not opinions):",
        f"  - RSI(14): {_fmt(snap.rsi)} ({snap.rsi_label})",
        f"  - Trend: close vs SMA50 {_fmt(snap.sma_50)} / SMA200 {_fmt(snap.sma_200)} -> {snap.trend_label}",
    ]
    if snap.recent_golden_cross:
        lines.append("  - Recent golden cross (SMA50 crossed above SMA200)")
    if snap.recent_death_cross:
        lines.append("  - Recent death cross (SMA50 crossed below SMA200)")
    lines += [
        f"  - MACD: {_fmt(snap.macd, '{:.3f}')} vs signal {_fmt(snap.macd_signal, '{:.3f}')} ({snap.macd_label})",
        f"  - Bollinger %B: {_fmt(snap.bb_pct_b)} ({snap.bb_label})",
        f"  - ATR(14): {_fmt(snap.atr)} ({_fmt(snap.atr_pct)}% of price — volatility)",
        f"  - Volume vs 20-day avg: {_fmt(snap.volume_ratio)}x ({snap.volume_label})",
    ]
    sup = f"{sym}{snap.nearest_support:,.2f}" if snap.nearest_support is not None else "none below"
    res = f"{sym}{snap.nearest_resistance:,.2f}" if snap.nearest_resistance is not None else "none above"
    lines.append(f"  - Nearest support: {sup}")
    lines.append(f"  - Nearest resistance: {res}")
    if snap.patterns:
        lines.append(f"  - Candlestick on last bar: {', '.join(snap.patterns)}")

    lines.append("")
    if sentiment.total == 0:
        lines.append("News (last 7 days): no items found from available sources.")
    else:
        themes = f"; themes: {', '.join(sentiment.themes)}" if sentiment.themes else ""
        lines.append(
            f"News (last 7 days, {sentiment.total} items, "
            f"{sentiment.positive} pos / {sentiment.neutral} neu / {sentiment.negative} neg — {sentiment.label}{themes}):"
        )
        for t in sentiment.sample_titles[:5]:
            lines.append(f"  - {t}")

    if score is not None:
        lines.append("")
        lines.append(
            f"Composite score: {score.value:+.1f} / 10 -> {score.label} "
            f"(direction: {score.direction})."
        )
        if score.breakdown:
            parts = [f"{k} {v:+.1f}" for k, v in score.breakdown.items()]
            lines.append(f"  Breakdown: {', '.join(parts)}")

    if rules:
        lines.append("")
        lines.append("Rule triggers:")
        for r in rules:
            lines.append(f"  - [{r.direction}] {r.name}: {r.note}")

    if setup is not None:
        lines.append("")
        if setup.entry is not None and setup.target is not None and setup.stop is not None:
            verb = "Valid setup" if setup.valid else "Reference setup (not actionable as-is)"
            lines.append(
                f"{verb}: entry {sym}{setup.entry:,.2f} / "
                f"stop {sym}{setup.stop:,.2f} / target {sym}{setup.target:,.2f}"
                + (f" / RR {setup.risk_reward:.1f}:1" if setup.risk_reward else "")
            )
        lines.append(f"  Note: {setup.note}")

    if backtest is not None:
        lines.append("")
        sentiment_caveat = (
            "technicals-only — historical news/sentiment not used"
            if not backtest.sentiment_used else ""
        )
        edge = backtest.edge_pct
        winrate = f"{backtest.win_rate_pct:.0f}%" if backtest.win_rate_pct is not None else "n/a"
        lines.append(
            f"Backtest ({backtest.start_date} to {backtest.end_date}, {backtest.bars} bars, "
            f"{sentiment_caveat}):"
        )
        lines.append(
            f"  - Strategy: {backtest.strategy_return_pct:+.1f}%  vs  "
            f"buy-and-hold: {backtest.buy_and_hold_return_pct:+.1f}%  "
            f"(edge {edge:+.1f}%)"
        )
        lines.append(
            f"  - Trades: {backtest.n_trades}, win rate {winrate}, "
            f"max drawdown {backtest.max_drawdown_pct:.1f}%, "
            f"in market {backtest.in_market_pct:.0f}% of bars"
        )
        lines.append(
            f"  - Costs: {backtest.transaction_cost_pct}% per side; "
            f"enter at score >= {backtest.score_threshold_enter}, "
            f"exit at score <= {backtest.score_threshold_exit}"
        )
        lines.append(
            "  Note: this is the technical-rule track record only; live "
            "synthesis also weighs news/sentiment which the backtest cannot."
        )

    if position_note:
        lines.append("")
        lines.append(f"Position context: {position_note}")

    lines.append("")
    lines.append(
        "Write a short synthesis paragraph (4-7 sentences) following all the rules "
        "in the system message. The composite score and any rule triggers are the "
        "primary read — use them. End with: Not advice — your call."
    )
    return "\n".join(lines)
