"""Batch digest generation.

Walks a list of (symbol, market) pairs, builds each digest, and writes the
markdown to disk. Designed for "kick it off and walk away" use on CPU
hardware where running 15 LLM syntheses sequentially takes a while.

Output layout:
    <out_dir>/<YYYY-MM-DD>/<SYMBOL>.<MARKET>.md   # one per ticker
    <out_dir>/<YYYY-MM-DD>/index.md               # scannable summary

Existing files for today are skipped unless force=True. Failures on one
ticker don't abort the batch — the rest continue and the failure is
recorded in the index.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from .data.base import DataSource
from .data.finnhub_news import FinnhubNewsSource
from .digest import build_digest
from .llm.ollama import DEFAULT_MODEL
from .markets import Market
from .portfolio.models import Holding
from .portfolio.store import PortfolioStore
from .render import render_digest_md


@dataclass
class BatchItem:
    symbol: str
    market: Market
    holding: Optional[Holding] = None  # set when sourced from the portfolio


@dataclass
class BatchOutcome:
    item: BatchItem
    status: str  # "ok" | "skipped" | "failed"
    path: Optional[Path]
    duration_s: float
    error: Optional[str] = None
    # Snapshot summary for the index (None on failure):
    last_price: Optional[float] = None
    trend_label: Optional[str] = None
    rsi: Optional[float] = None
    sentiment_label: Optional[str] = None
    sentiment_total: int = 0
    synthesis_first_line: Optional[str] = None


def items_from_portfolio(store: PortfolioStore) -> list[BatchItem]:
    items: list[BatchItem] = []
    for h in store.all():
        try:
            m = Market.from_code(h.market_code)
        except ValueError:
            continue
        items.append(BatchItem(symbol=h.ticker, market=m, holding=h))
    return items


def run_batch(
    items: list[BatchItem],
    *,
    data_source: DataSource,
    out_dir: Path,
    finnhub: Optional[FinnhubNewsSource] = None,
    period: str = "1y",
    run_llm: bool = True,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    on_progress: Optional[Callable[[int, int, BatchOutcome], None]] = None,
) -> list[BatchOutcome]:
    """Run digest generation for each item, writing markdown to disk.

    `on_progress(idx, total, outcome)` is called after each item so the CLI
    (or the future UI) can display live progress.
    """
    today = date.today().isoformat()
    day_dir = out_dir / today
    day_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[BatchOutcome] = []
    finnhub = finnhub or FinnhubNewsSource()

    for i, item in enumerate(items, start=1):
        file_path = day_dir / f"{item.symbol}.{item.market.code}.md"
        t0 = time.monotonic()

        if file_path.exists() and not force:
            outcome = BatchOutcome(
                item=item, status="skipped", path=file_path,
                duration_s=0.0,
            )
            outcomes.append(outcome)
            if on_progress:
                on_progress(i, len(items), outcome)
            continue

        try:
            position_note = None
            if item.holding is not None:
                h = item.holding
                position_note = (
                    f"holding {h.shares:g} shares at cost basis "
                    f"{item.market.currency_symbol}{h.cost_basis:,.2f} "
                    f"(added {h.date_added.isoformat()})"
                )
            digest = build_digest(
                item.symbol,
                item.market,
                data_source=data_source,
                finnhub=finnhub,
                period=period,
                run_llm=run_llm,
                model=model,
                position_note=position_note,
            )
            md = render_digest_md(digest, holding=item.holding)
            file_path.write_text(md, encoding="utf-8")

            first_line = None
            if digest.synthesis:
                first_line = digest.synthesis.strip().splitlines()[0]

            outcome = BatchOutcome(
                item=item,
                status="ok",
                path=file_path,
                duration_s=time.monotonic() - t0,
                last_price=(digest.quote.price if digest.quote else digest.snapshot.close),
                trend_label=digest.snapshot.trend_label,
                rsi=digest.snapshot.rsi,
                sentiment_label=digest.sentiment.label,
                sentiment_total=digest.sentiment.total,
                synthesis_first_line=first_line,
            )
        except Exception as e:
            outcome = BatchOutcome(
                item=item,
                status="failed",
                path=None,
                duration_s=time.monotonic() - t0,
                error=f"{type(e).__name__}: {e}",
            )
            # Drop a small failure note alongside successful files for debugging.
            err_path = day_dir / f"{item.symbol}.{item.market.code}.error.txt"
            err_path.write_text(traceback.format_exc(), encoding="utf-8")

        outcomes.append(outcome)
        if on_progress:
            on_progress(i, len(items), outcome)

    _write_index(day_dir, outcomes)
    return outcomes


def _write_index(day_dir: Path, outcomes: list[BatchOutcome]) -> None:
    today = day_dir.name
    lines: list[str] = []
    lines.append(f"# Digest index — {today}")
    lines.append("")
    lines.append(f"_{len(outcomes)} tickers · "
                 f"{sum(o.status == 'ok' for o in outcomes)} ok · "
                 f"{sum(o.status == 'skipped' for o in outcomes)} skipped · "
                 f"{sum(o.status == 'failed' for o in outcomes)} failed_")
    lines.append("")
    lines.append("| Ticker | Price | Trend | RSI | News | Note |")
    lines.append("|---|---|---|---|---|---|")
    for o in outcomes:
        sym = f"[{o.item.symbol}.{o.item.market.code}]({o.path.name})" if o.path else f"{o.item.symbol}.{o.item.market.code}"
        if o.status == "failed":
            lines.append(f"| {o.item.symbol}.{o.item.market.code} | — | — | — | — | failed: {o.error} |")
            continue
        cur = f"{o.item.market.currency_symbol}{o.last_price:,.2f}" if o.last_price is not None else "—"
        rsi = f"{o.rsi:.0f}" if o.rsi is not None else "—"
        news = f"{o.sentiment_total} ({o.sentiment_label})" if o.sentiment_total else "none"
        note = o.synthesis_first_line or ("(no synthesis)" if o.status == "ok" else "(skipped)")
        if len(note) > 100:
            note = note[:97] + "..."
        lines.append(f"| {sym} | {cur} | {o.trend_label or '—'} | {rsi} | {news} | {note} |")

    lines.append("")
    (day_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")
