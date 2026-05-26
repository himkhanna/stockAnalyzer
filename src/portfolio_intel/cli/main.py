"""Phase 1 CLI.

Commands:
  pintel lookup <ticker> [--market US|NSE|BSE]
  pintel list
  pintel add <ticker> --shares N --cost X [--market ...] [--date YYYY-MM-DD]
  pintel remove <ticker> [--market ...]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional

from ..data.base import DataSource, DataSourceError
from ..data.models import Quote
from ..data.yfinance_source import YFinanceSource
from ..markets import Market, parse_ticker
from ..portfolio.models import Holding
from ..portfolio.store import PortfolioStore


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pintel", description="Personal portfolio intelligence.")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("lookup", help="Look up a quote for any ticker (no portfolio needed).")
    sp.add_argument("ticker")
    sp.add_argument("--market", choices=[m.code for m in Market])
    sp.set_defaults(func=cmd_lookup)

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

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
