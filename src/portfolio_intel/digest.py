"""Per-stock digest orchestrator.

Pulls together data, technicals, news, sentiment, scoring/rules/setup, and
LLM synthesis into a single 'card' the CLI (and later, the UI) renders.
Each input is wired through its layer's interface — this module does no
math itself.

Graceful degradation (CLAUDE.md):
- If news fails, still show technicals + score.
- If Ollama is down, still show data, signals, score, rules, and setup;
  just skip the LLM synthesis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .data.base import DataSource, DataSourceError
from .data.finnhub_news import FinnhubNewsSource
from .data.models import NewsItem, Quote
from .llm.ollama import DEFAULT_MODEL, OllamaError, generate
from .llm.prompts import SYSTEM_PROMPT, build_user_prompt
from .markets import Market
from .news.router import fetch_news
from .news.sentiment import SentimentSummary, tally
from .portfolio.models import Holding
from .scoring import (
    DEFAULT_WEIGHTS,
    PositionContext,
    RuleHit,
    Score,
    TradeSetup,
    Weights,
    build_position_context,
    build_setup,
    compute_score,
    evaluate_rules,
)
from .technical.signals import TechnicalSnapshot, compute_snapshot


@dataclass
class Digest:
    symbol: str
    market: Market
    quote: Optional[Quote]
    snapshot: TechnicalSnapshot
    news: list[NewsItem]
    sentiment: SentimentSummary
    score: Score
    rules: list[RuleHit] = field(default_factory=list)
    setup: Optional[TradeSetup] = None
    position: Optional[PositionContext] = None
    synthesis: Optional[str] = None
    synthesis_error: Optional[str] = None
    model_used: Optional[str] = None


def build_digest(
    symbol: str,
    market: Market,
    *,
    data_source: DataSource,
    finnhub: Optional[FinnhubNewsSource] = None,
    period: str = "1y",
    interval: str = "1d",
    run_llm: bool = True,
    model: str = DEFAULT_MODEL,
    holding: Optional[Holding] = None,
    currency_bucket_total: Optional[float] = None,
    weights: Weights = DEFAULT_WEIGHTS,
    on_token: Optional[Callable[[str], None]] = None,
) -> Digest:
    df = data_source.get_history(symbol, market, period=period, interval=interval)
    snap = compute_snapshot(df)

    quote: Optional[Quote] = None
    try:
        quote = data_source.get_quote(symbol, market)
    except DataSourceError:
        pass

    news = fetch_news(symbol, market, data_source=data_source, finnhub=finnhub)
    sentiment = tally(news)

    score = compute_score(snap, sentiment, weights=weights)
    rules = evaluate_rules(snap, sentiment, weights=weights)
    setup = build_setup(snap, score, weights=weights)

    position: Optional[PositionContext] = None
    if holding is not None:
        current_price = quote.price if quote is not None else snap.close
        position = build_position_context(
            holding,
            current_price=current_price,
            currency_bucket_total=currency_bucket_total,
            weights=weights,
        )

    synthesis: Optional[str] = None
    synthesis_error: Optional[str] = None
    model_used: Optional[str] = None

    if run_llm:
        position_note = _position_note(position, market)
        user_prompt = build_user_prompt(
            symbol=symbol,
            market_code=market.code,
            currency_symbol=market.currency_symbol,
            snap=snap,
            sentiment=sentiment,
            news=news,
            score=score,
            rules=rules,
            setup=setup,
            position_note=position_note,
        )
        try:
            resp = generate(user_prompt, system=SYSTEM_PROMPT, model=model, on_token=on_token)
            synthesis = resp.text
            model_used = resp.model
        except OllamaError as e:
            synthesis_error = str(e)

    return Digest(
        symbol=symbol.upper(),
        market=market,
        quote=quote,
        snapshot=snap,
        news=news,
        sentiment=sentiment,
        score=score,
        rules=rules,
        setup=setup,
        position=position,
        synthesis=synthesis,
        synthesis_error=synthesis_error,
        model_used=model_used,
    )


def _position_note(pos: Optional[PositionContext], market: Market) -> Optional[str]:
    if pos is None:
        return None
    sym = market.currency_symbol
    base = (
        f"holding {pos.shares:g} shares; market value {sym}{pos.market_value:,.2f}; "
        f"P&L {sym}{pos.pnl:,.2f} ({pos.pnl_pct:+.2f}%)."
    )
    return base + " " + pos.suggestion
