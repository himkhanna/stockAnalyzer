"""CLI.

Commands:
  pintel lookup  <ticker> [--market US|NSE|BSE]
  pintel analyze <ticker> [--market ...] [--period 1y] [--interval 1d]
  pintel digest  <ticker> [--market ...] [--period 1y] [--no-llm] [--model NAME]
  pintel list
  pintel add     <ticker> --shares N --cost X [--market ...] [--date YYYY-MM-DD]
  pintel remove  <ticker> [--market ...]
  pintel import  <csv>  [--replace] [--dry-run] [--skip-errors]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()  # Pick up .env in cwd / parent dirs before reading env vars.
except ImportError:
    pass

from ..data.base import DataSource, DataSourceError
from ..data.models import Quote
from ..data.yfinance_source import YFinanceSource
from ..markets import Market, parse_ticker
from ..digest import build_digest
from ..llm.ollama import DEFAULT_MODEL
from ..portfolio.csv_import import import_csv_file
from ..portfolio.models import Holding
from ..portfolio.store import PortfolioStore
from ..technical.signals import TechnicalSnapshot, compute_snapshot


DEFAULT_DB = "portfolio.db"


def _resolve_ticker(raw: str, market_flag: Optional[str]) -> tuple[str, Market]:
    explicit = Market.from_code(market_flag) if market_flag else None
    symbol, market = parse_ticker(raw, default_market=explicit)
    # If the user gave both a qualified suffix and --market, the suffix wins
    # but we warn if they disagree.
    if explicit is not None and market is not explicit:
        print(
            f"note: ticker suffix implies {market.code}; --market {explicit.code} ignored",
            file=sys.stderr,
        )
    return symbol, market


def _fmt_money(amount: float, market: Market) -> str:
    return f"{market.currency_symbol}{amount:,.2f}"


def _fmt_quote_line(symbol: str, market: Market, q: Quote) -> str:
    chg = q.change_pct
    chg_str = f"  ({chg:+.2f}%)" if chg is not None else ""
    stale = "  [stale: market closed]" if q.stale else ""
    return f"{symbol}.{market.code}  {_fmt_money(q.price, market)}{chg_str}{stale}"


def cmd_lookup(args: argparse.Namespace) -> int:
    symbol, market = _resolve_ticker(args.ticker, args.market)
    source: DataSource = YFinanceSource()
    try:
        q = source.get_quote(symbol, market)
    except DataSourceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(_fmt_quote_line(symbol, market, q))
    if q.previous_close is not None:
        print(f"  prev close: {_fmt_money(q.previous_close, market)}")
    print(f"  as of:      {q.as_of.isoformat(timespec='seconds')}")
    return 0


def _fmt(v: float | None, fmt: str = "{:.2f}") -> str:
    return fmt.format(v) if v is not None else "n/a"


def _print_snapshot(symbol: str, market: Market, snap: TechnicalSnapshot, q: Optional[Quote] = None) -> None:
    sym = market.currency_symbol
    print(f"\n{symbol}.{market.code}  technicals  (bars: {snap.bars_used})")
    if q is not None:
        chg = q.change_pct
        chg_str = f"  ({chg:+.2f}%)" if chg is not None else ""
        stale = "  [stale]" if q.stale else ""
        print(f"  price       {sym}{q.price:,.2f}{chg_str}{stale}")
    print(f"  RSI(14)     {_fmt(snap.rsi)}  ({snap.rsi_label})")
    print(f"  trend       close {sym}{snap.close:,.2f} vs SMA50 {_fmt(snap.sma_50)} / SMA200 {_fmt(snap.sma_200)}  ({snap.trend_label})")
    if snap.recent_golden_cross:
        print(f"              recent golden cross")
    if snap.recent_death_cross:
        print(f"              recent death cross")
    print(f"  MACD        {_fmt(snap.macd, '{:.3f}')} / signal {_fmt(snap.macd_signal, '{:.3f}')} / hist {_fmt(snap.macd_hist, '{:.3f}')}  ({snap.macd_label})")
    print(f"  Bollinger   lower {_fmt(snap.bb_lower)} - upper {_fmt(snap.bb_upper)}  %B {_fmt(snap.bb_pct_b)}  ({snap.bb_label})")
    print(f"  ATR(14)     {_fmt(snap.atr)}  ({_fmt(snap.atr_pct)}% of price)")
    print(f"  Volume      {_fmt(snap.volume_ratio)}x 20-day avg  ({snap.volume_label})")
    sup = f"{sym}{snap.nearest_support:,.2f}" if snap.nearest_support else "none below"
    res = f"{sym}{snap.nearest_resistance:,.2f}" if snap.nearest_resistance else "none above"
    print(f"  Levels      support {sup}  /  resistance {res}")
    if snap.patterns:
        print(f"  Patterns    {', '.join(snap.patterns)} (last bar)")


def cmd_analyze(args: argparse.Namespace) -> int:
    symbol, market = _resolve_ticker(args.ticker, args.market)
    source: DataSource = YFinanceSource()
    try:
        df = source.get_history(symbol, market, period=args.period, interval=args.interval)
    except DataSourceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        snap = compute_snapshot(df)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    q: Optional[Quote] = None
    try:
        q = source.get_quote(symbol, market)
    except DataSourceError:
        pass  # quote is a nice-to-have here; history already loaded
    _print_snapshot(symbol, market, snap, q=q)
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    from ..data.finnhub_news import FinnhubNewsSource
    from ..llm.ollama import OllamaError, generate
    from ..llm.prompts import SYSTEM_PROMPT, build_user_prompt
    from ..news.router import fetch_news
    from ..news.sentiment import tally

    symbol, market = _resolve_ticker(args.ticker, args.market)
    source = YFinanceSource()

    store = PortfolioStore(args.db)
    holding = store.get(symbol, market.code)
    position_note: Optional[str] = None
    if holding is not None:
        position_note = (
            f"holding {holding.shares:g} shares at cost basis "
            f"{market.currency_symbol}{holding.cost_basis:,.2f} "
            f"(added {holding.date_added.isoformat()})"
        )

    # ---- Data + technicals ----
    try:
        df = source.get_history(symbol, market, period=args.period)
        snap = compute_snapshot(df)
    except (DataSourceError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    quote: Optional[Quote] = None
    try:
        quote = source.get_quote(symbol, market)
    except DataSourceError:
        pass

    print(f"\n=== {symbol}.{market.code} digest ===")
    _print_snapshot(symbol, market, snap, q=quote)

    # ---- News + sentiment ----
    news = fetch_news(symbol, market, data_source=source, finnhub=FinnhubNewsSource())
    sentiment = tally(news)

    print()
    if sentiment.total == 0:
        print("  News        no items found")
    else:
        themes = f"  themes: {', '.join(sentiment.themes)}" if sentiment.themes else ""
        print(
            f"  News (7d)   {sentiment.total} items  "
            f"{sentiment.positive} pos / {sentiment.neutral} neu / {sentiment.negative} neg  "
            f"({sentiment.label}){themes}"
        )
        for t in sentiment.sample_titles[:3]:
            print(f"              - {t}")

    if holding is not None and quote is not None:
        cost_total = holding.cost_basis * holding.shares
        mv = quote.price * holding.shares
        pnl = mv - cost_total
        pct = (pnl / cost_total * 100.0) if cost_total else 0.0
        sym = market.currency_symbol
        print()
        print(
            f"  Position    {holding.shares:g} sh @ {sym}{holding.cost_basis:,.2f}  "
            f"now {sym}{quote.price:,.2f}  "
            f"P&L {sym}{pnl:,.2f} ({pct:+.2f}%)"
        )

    # ---- Synthesis (streamed) ----
    print()
    if args.no_llm:
        print("(synthesis skipped: --no-llm)")
        return 0

    user_prompt = build_user_prompt(
        symbol=symbol,
        market_code=market.code,
        currency_symbol=market.currency_symbol,
        snap=snap,
        sentiment=sentiment,
        news=news,
        position_note=position_note,
    )
    print(f"Synthesis ({args.model}):")

    def _emit(chunk: str) -> None:
        sys.stdout.write(chunk)
        sys.stdout.flush()

    try:
        resp = generate(
            user_prompt,
            system=SYSTEM_PROMPT,
            model=args.model,
            on_token=_emit,
        )
    except OllamaError as e:
        # Newline in case partial output went to stdout before the error.
        print()
        print(f"(synthesis failed: {e})")
        return 0

    print()  # final newline after the streamed paragraph
    if resp.duration_ms:
        secs = resp.duration_ms / 1000.0
        tok = resp.eval_count or 0
        rate = (tok / secs) if secs else 0
        print(f"  [{tok} tokens in {secs:.1f}s, {rate:.1f} tok/s]")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = PortfolioStore(args.db)
    holdings = store.all()
    if not holdings:
        print("(no holdings — use `pintel add ...` to add one)")
        return 0

    source = YFinanceSource()
    totals_by_ccy: dict[str, tuple[float, float]] = {}  # ccy -> (cost, market)

    for h in holdings:
        try:
            market = Market.from_code(h.market_code)
        except ValueError:
            print(f"{h.ticker}.{h.market_code}  (unknown market — skipping)")
            continue
        try:
            q = source.get_quote(h.ticker, market)
        except DataSourceError as e:
            print(f"{h.ticker}.{market.code}  (quote unavailable: {e})")
            continue

        cost_total = h.cost_basis * h.shares
        mkt_value = q.price * h.shares
        pnl = mkt_value - cost_total
        pnl_pct = (pnl / cost_total * 100.0) if cost_total else 0.0
        stale = " [stale]" if q.stale else ""

        print(
            f"{h.ticker}.{market.code}  "
            f"{h.shares:g} sh @ {_fmt_money(h.cost_basis, market)}  "
            f"now {_fmt_money(q.price, market)}  "
            f"value {_fmt_money(mkt_value, market)}  "
            f"P&L {_fmt_money(pnl, market)} ({pnl_pct:+.2f}%){stale}"
        )

        cost, mv = totals_by_ccy.get(h.currency, (0.0, 0.0))
        totals_by_ccy[h.currency] = (cost + cost_total, mv + mkt_value)

    if totals_by_ccy:
        print("\nTotals by currency (no FX conversion):")
        for ccy, (cost, mv) in sorted(totals_by_ccy.items()):
            pnl = mv - cost
            pct = (pnl / cost * 100.0) if cost else 0.0
            print(f"  {ccy}: cost {cost:,.2f}  value {mv:,.2f}  P&L {pnl:,.2f} ({pct:+.2f}%)")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    symbol, market = _resolve_ticker(args.ticker, args.market)
    d = date.fromisoformat(args.date) if args.date else date.today()
    holding = Holding(
        ticker=symbol,
        market_code=market.code,
        shares=args.shares,
        cost_basis=args.cost,
        currency=market.currency,
        date_added=d,
    )
    store = PortfolioStore(args.db)
    store.upsert(holding)
    print(
        f"added/updated {symbol}.{market.code}  "
        f"{args.shares:g} sh @ {_fmt_money(args.cost, market)}  "
        f"({market.currency})"
    )
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    symbol, market = _resolve_ticker(args.ticker, args.market)
    store = PortfolioStore(args.db)
    if store.remove(symbol, market.code):
        print(f"removed {symbol}.{market.code}")
        return 0
    print(f"no holding {symbol}.{market.code}", file=sys.stderr)
    return 1


def cmd_import(args: argparse.Namespace) -> int:
    try:
        result = import_csv_file(args.csv_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if result.errors:
        print(f"{len(result.errors)} row(s) had errors:", file=sys.stderr)
        for err in result.errors:
            print(f"  line {err.row_number}: {err.reason}  ({err.raw})", file=sys.stderr)
        if not args.skip_errors:
            print("aborting (use --skip-errors to import the good rows anyway)", file=sys.stderr)
            return 2

    print(f"parsed {len(result.holdings)} holding(s) from {args.csv_path}")
    for h in result.holdings:
        market = Market.from_code(h.market_code)
        print(
            f"  {h.ticker}.{market.code}  {h.shares:g} sh @ "
            f"{_fmt_money(h.cost_basis, market)}  ({h.date_added.isoformat()})"
        )

    if args.dry_run:
        print("\n(dry-run: nothing written)")
        return 0

    store = PortfolioStore(args.db)
    if args.replace:
        existing = store.all()
        for h in existing:
            store.remove(h.ticker, h.market_code)
        print(f"\nreplaced {len(existing)} existing holding(s)")
    for h in result.holdings:
        store.upsert(h)
    print(f"wrote {len(result.holdings)} holding(s) to {args.db}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pintel", description="Personal portfolio intelligence.")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("lookup", help="Look up a quote for any ticker (no portfolio needed).")
    sp.add_argument("ticker")
    sp.add_argument("--market", choices=[m.code for m in Market])
    sp.set_defaults(func=cmd_lookup)

    sp = sub.add_parser("analyze", help="Compute technical indicators for any ticker.")
    sp.add_argument("ticker")
    sp.add_argument("--market", choices=[m.code for m in Market])
    sp.add_argument("--period", default="1y", help="yfinance period (e.g. 6mo, 1y, 2y).")
    sp.add_argument("--interval", default="1d", help="Bar interval (e.g. 1d, 1wk).")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser(
        "digest",
        help="Full digest: technicals + news + LLM synthesis (needs Ollama).",
    )
    sp.add_argument("ticker")
    sp.add_argument("--market", choices=[m.code for m in Market])
    sp.add_argument("--period", default="1y")
    sp.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip the Ollama synthesis (useful when Ollama isn't running).",
    )
    sp.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL} or $OLLAMA_MODEL).",
    )
    sp.set_defaults(func=cmd_digest)

    sp = sub.add_parser("list", help="List portfolio holdings with current prices and P&L.")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("add", help="Add or update a holding.")
    sp.add_argument("ticker")
    sp.add_argument("--shares", type=float, required=True)
    sp.add_argument("--cost", type=float, required=True, help="Per-share cost basis.")
    sp.add_argument("--market", choices=[m.code for m in Market])
    sp.add_argument("--date", help="Acquisition date YYYY-MM-DD (defaults to today).")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("remove", help="Remove a holding.")
    sp.add_argument("ticker")
    sp.add_argument("--market", choices=[m.code for m in Market])
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser(
        "import",
        help="Import holdings from a CSV (columns: ticker, market, shares, cost_basis, date).",
    )
    sp.add_argument("csv_path", help="Path to the CSV file.")
    sp.add_argument(
        "--replace",
        action="store_true",
        help="Wipe existing holdings before importing (default: upsert).",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and display, but do not write to the DB.",
    )
    sp.add_argument(
        "--skip-errors",
        action="store_true",
        help="Import valid rows even if some rows fail validation.",
    )
    sp.set_defaults(func=cmd_import)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
