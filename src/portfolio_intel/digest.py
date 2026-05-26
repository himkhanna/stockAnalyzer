"""Per-stock digest orchestrator.

Pulls together data, technicals, news, sentiment, and LLM synthesis into a
single 'card' the CLI (and later, the UI) renders. Each input is wired
through its layer's interface — this module does no math itself.

Graceful degradation rules (from CLAUDE.md):
- If news fails, still show technicals.
- If Ollama is down, still show data + signals; just skip the synthesis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .data.base import DataSource, DataSourceError
from .data.finnhub_news import FinnhubNewsSource
from .data.models import NewsItem, Quote
from .llm.ollama import DEFAULT_MODEL, OllamaError, generate
from .llm.prompts import SYSTEM_PROMPT, build_user_prompt
from .markets import Market
from .news.router import fetch_news
from .news.sentiment import SentimentSummary, tally
from .technical.signals import TechnicalSnapshot, compute_snapshot


@dataclass
class Digest:
    symbol: str
    market: Market
    quote: Optional[Quote]
    snapshot: TechnicalSnapshot
    news: list[NewsItem]
    sentiment: SentimentSummary
    synthesis: Optional[str]  # None when LLM was skipped or failed
    synthesis_error: Optional[str]  # human-readable reason synthesis is missing
    model_used: Optional[str]


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
    position_note: Optional[str] = None,
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

    synthesis: Optional[str] = None
    synthesis_error: Optional[str] = None
    model_used: Optional[str] = None

    if run_llm:
        user_prompt = build_user_prompt(
            symbol=symbol,
            market_code=market.code,
            currency_symbol=market.currency_symbol,
            snap=snap,
            sentiment=sentiment,
            news=news,
            position_note=position_note,
        )
        try:
            resp = generate(
                user_prompt,
                system=SYSTEM_PROMPT,
                model=model,
                on_token=on_token,
            )
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
        synthesis=synthesis,
        synthesis_error=synthesis_error,
        model_used=model_used,
    )
