"""Portfolio Intelligence — Streamlit dashboard.

Design choices, informed by CLAUDE.md and the user's downside-protection lens:
- Compact cards in a grid, expandable to full detail. 15-stock portfolio
  scannable in ~30 seconds.
- Sell / Strong Sell signals get the loudest colour — those are the ones
  worth acting on for a downside-protection user.
- Today's batch markdown files (if present) are read first; the LLM
  synthesis only runs on demand (button) because it's CPU-slow.
- No new computation lives here; this is a view layer.
"""
from __future__ import annotations

import sys
from datetime import date as date_
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import streamlit as st

from portfolio_intel.batch import BatchItem, items_from_portfolio, run_batch
from portfolio_intel.data.base import DataSourceError
from portfolio_intel.data.finnhub_news import FinnhubNewsSource
from portfolio_intel.data.yfinance_source import YFinanceSource
from portfolio_intel.digest import build_digest
from portfolio_intel.llm.ollama import DEFAULT_MODEL
from portfolio_intel.markets import Market, parse_ticker
from portfolio_intel.portfolio.csv_import import import_csv_file
from portfolio_intel.portfolio.models import Holding
from portfolio_intel.portfolio.store import PortfolioStore
from portfolio_intel.render import render_digest_md


st.set_page_config(
    page_title="Portfolio Intelligence",
    layout="wide",
    page_icon="📊",
)


# ---------------- Styling ----------------

SIGNAL_STYLES = {
    "Strong Sell": ("#7f1d1d", "#fff", "🔻"),   # loud — downside-protection lens
    "Sell":         ("#dc2626", "#fff", "⬇"),
    "Hold":         ("#52525b", "#fff", "—"),
    "Buy":          ("#16a34a", "#fff", "⬆"),
    "Strong Buy":   ("#15803d", "#fff", "🚀"),
}


def signal_pill(label: str, score: float) -> str:
    bg, fg, glyph = SIGNAL_STYLES.get(label, ("#52525b", "#fff", "—"))
    return (
        f"<span style='background:{bg};color:{fg};padding:4px 10px;"
        f"border-radius:6px;font-weight:600;font-size:0.9em'>"
        f"{glyph} {label} ({score:+.1f})</span>"
    )


# ---------------- State ----------------

def _store(db_path: str) -> PortfolioStore:
    return PortfolioStore(db_path)


@st.cache_resource
def _source() -> YFinanceSource:
    return YFinanceSource()


# ---------------- Helpers ----------------

def _today_dir(out_dir: Path) -> Path:
    return out_dir / date_.today().isoformat()


def _existing_md_for(symbol: str, market: Market, out_dir: Path) -> Path | None:
    p = _today_dir(out_dir) / f"{symbol}.{market.code}.md"
    return p if p.exists() else None


@st.cache_data(ttl=300, show_spinner=False)
def _quick_card(
    symbol: str, market_code: str, period: str
) -> dict | None:
    """Compute the data + signals + setup for one ticker (no LLM). Cached for
    5 minutes per (ticker, market, period) so re-rendering is snappy."""
    market = Market.from_code(market_code)
    try:
        digest = build_digest(
            symbol,
            market,
            data_source=_source(),
            finnhub=FinnhubNewsSource(),
            period=period,
            run_llm=False,
        )
    except (DataSourceError, ValueError) as e:
        return {"error": str(e)}

    return {
        "symbol": symbol,
        "market_code": market_code,
        "currency_symbol": market.currency_symbol,
        "price": digest.quote.price if digest.quote else digest.snapshot.close,
        "change_pct": digest.quote.change_pct if digest.quote else None,
        "stale": digest.quote.stale if digest.quote else False,
        "score_value": digest.score.value,
        "score_label": digest.score.label,
        "rsi": digest.snapshot.rsi,
        "trend": digest.snapshot.trend_label,
        "sentiment_label": digest.sentiment.label,
        "sentiment_total": digest.sentiment.total,
        "setup_valid": digest.setup.valid if digest.setup else False,
        "setup_entry": digest.setup.entry if digest.setup else None,
        "setup_stop": digest.setup.stop if digest.setup else None,
        "setup_target": digest.setup.target if digest.setup else None,
        "setup_rr": digest.setup.risk_reward if digest.setup else None,
        "rules": [(r.name, r.direction, r.note) for r in digest.rules],
    }


def _holding_for(store: PortfolioStore, symbol: str, market: Market) -> Holding | None:
    return store.get(symbol, market.code)


# ---------------- Card renderer ----------------

def _render_card(c: dict, out_dir: Path, model: str) -> None:
    if c.get("error"):
        st.error(c["error"])
        return

    sym = c["currency_symbol"]
    symbol = c["symbol"]
    market_code = c["market_code"]
    holding: Holding | None = c.get("holding")

    cols = st.columns([2, 3])
    with cols[0]:
        st.markdown(f"### {symbol}.{market_code}")
    with cols[1]:
        st.markdown(signal_pill(c["score_label"], c["score_value"]), unsafe_allow_html=True)

    chg = c.get("change_pct")
    chg_txt = f"  ({chg:+.2f}%)" if chg is not None else ""
    stale_txt = "  *[stale]*" if c.get("stale") else ""
    st.markdown(f"**{sym}{c['price']:,.2f}**{chg_txt}{stale_txt}")

    st.caption(
        f"RSI {c['rsi']:.0f} · trend {c['trend']} · "
        f"news {c['sentiment_total']} ({c['sentiment_label']})"
    )

    if holding is not None:
        cost_total = holding.cost_basis * holding.shares
        mv = c["price"] * holding.shares
        pnl = mv - cost_total
        pct = (pnl / cost_total * 100.0) if cost_total else 0.0
        sign = "🟢" if pnl >= 0 else "🔴"
        st.caption(f"{sign} {holding.shares:g} sh · P&L {sym}{pnl:,.2f} ({pct:+.2f}%)")

    if c.get("setup_valid") and c.get("setup_target"):
        st.caption(
            f"📐 entry {sym}{c['setup_entry']:,.2f} / stop {sym}{c['setup_stop']:,.2f} "
            f"/ target {sym}{c['setup_target']:,.2f} · RR {c['setup_rr']:.1f}:1"
        )

    md_path = _existing_md_for(symbol, Market.from_code(market_code), out_dir)
    with st.expander("Full digest", expanded=False):
        if md_path is not None:
            st.markdown(md_path.read_text(encoding="utf-8"))
            st.caption(f"_from {md_path}_")
        else:
            st.info("No full digest cached for today. Click below to generate.")
            if st.button(
                f"Generate full digest for {symbol}.{market_code}",
                key=f"gen_{symbol}_{market_code}",
            ):
                with st.spinner("Running LLM synthesis..."):
                    market = Market.from_code(market_code)
                    digest = build_digest(
                        symbol, market,
                        data_source=_source(),
                        finnhub=FinnhubNewsSource(),
                        period="1y",
                        run_llm=True,
                        model=model,
                        holding=holding,
                    )
                    md = render_digest_md(digest, holding=holding)
                    today_dir = _today_dir(out_dir)
                    today_dir.mkdir(parents=True, exist_ok=True)
                    (today_dir / f"{symbol}.{market_code}.md").write_text(md, encoding="utf-8")
                st.rerun()


# ---------------- Sidebar ----------------

with st.sidebar:
    st.title("📊 Portfolio Intelligence")
    st.caption("Personal stock analysis · facts → signals → grounded synthesis")

    db_path = st.text_input("Database", value="portfolio.db")
    period = st.selectbox("History window", ["6mo", "1y", "2y", "5y"], index=1)
    out_dir = Path(st.text_input("Digest output dir", value="digests"))
    model = st.text_input("Ollama model", value=DEFAULT_MODEL)

    st.divider()
    if st.button("🔄 Refresh data cache"):
        _quick_card.clear()
        st.rerun()

store = _store(db_path)


# ---------------- Tabs ----------------

tab_dash, tab_lookup, tab_portfolio = st.tabs(["Dashboard", "Lookup", "Portfolio"])


# ====================== Dashboard ======================

with tab_dash:
    st.subheader("Holdings")
    st.caption("Sell / Strong Sell signals get the loudest colour — those are the ones to actually act on.")

    items = items_from_portfolio(store)
    if not items:
        st.info("No holdings yet. Use **Portfolio** tab to add one, or **Lookup** to analyse any ticker.")
    else:
        col_left, col_right = st.columns([4, 1])
        with col_left:
            sort_by = st.selectbox(
                "Sort by",
                ["Signal (Sell first)", "Signal (Buy first)", "Ticker", "Overweight first"],
                index=0,
            )
        with col_right:
            run_full = st.button("🤖 Generate today's batch (LLM)", help="Runs the full digest pipeline including the LLM synthesis. Slow on CPU.")

        if run_full:
            with st.spinner("Running batch — this can take a while on CPU..."):
                progress = st.progress(0.0)
                def cb(i, total, outcome):
                    progress.progress(i / total)
                run_batch(
                    items,
                    data_source=_source(),
                    out_dir=out_dir,
                    period=period,
                    run_llm=True,
                    model=model,
                    force=True,
                    on_progress=cb,
                )
            st.success("Batch complete.")
            _quick_card.clear()

        # Build cards
        cards: list[dict] = []
        for it in items:
            with st.spinner(f"loading {it.symbol}.{it.market.code}..."):
                c = _quick_card(it.symbol, it.market.code, period)
            if c is None:
                continue
            c["holding"] = it.holding
            cards.append(c)

        # Sort
        signal_order_sell_first = ["Strong Sell", "Sell", "Hold", "Buy", "Strong Buy"]
        signal_order_buy_first = list(reversed(signal_order_sell_first))
        if sort_by == "Signal (Sell first)":
            cards.sort(key=lambda c: (signal_order_sell_first.index(c.get("score_label", "Hold")) if c.get("score_label") in signal_order_sell_first else 99))
        elif sort_by == "Signal (Buy first)":
            cards.sort(key=lambda c: (signal_order_buy_first.index(c.get("score_label", "Hold")) if c.get("score_label") in signal_order_buy_first else 99))
        elif sort_by == "Overweight first":
            cards.sort(key=lambda c: 0 if c.get("error") else 1)
        else:
            cards.sort(key=lambda c: c.get("symbol", ""))

        # Render grid
        for row_start in range(0, len(cards), 3):
            cols = st.columns(3)
            for col, c in zip(cols, cards[row_start:row_start + 3]):
                with col:
                    _render_card(c, out_dir, model)


# ====================== Lookup ======================

with tab_lookup:
    st.subheader("Look up any ticker")
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        raw_ticker = st.text_input("Ticker", value="AAPL", help="Bare symbol (AAPL) or qualified (RELIANCE.NS).")
    with col2:
        market_flag = st.selectbox("Market (when ticker is bare)", ["(auto)", "US", "NSE", "BSE"], index=0)
    with col3:
        run_llm_lookup = st.checkbox("Run LLM synthesis", value=False, help="Slow on CPU.")

    if st.button("Analyse", type="primary"):
        explicit = Market.from_code(market_flag) if market_flag != "(auto)" else None
        symbol, market = parse_ticker(raw_ticker, default_market=explicit)
        with st.spinner(f"analysing {symbol}.{market.code}..."):
            try:
                holding = _holding_for(store, symbol, market)
                digest = build_digest(
                    symbol, market,
                    data_source=_source(),
                    finnhub=FinnhubNewsSource(),
                    period=period,
                    run_llm=run_llm_lookup,
                    model=model,
                    holding=holding,
                )
            except (DataSourceError, ValueError) as e:
                st.error(str(e))
                digest = None
        if digest is not None:
            md = render_digest_md(digest, holding=holding)
            st.markdown(md)
            if holding is None and st.button(f"➕ Add {symbol}.{market.code} to portfolio"):
                st.session_state["pending_add"] = (symbol, market.code, digest.snapshot.close)


# ====================== Portfolio ======================

with tab_portfolio:
    st.subheader("Holdings")

    holdings = store.all()
    if holdings:
        st.dataframe(
            [
                {
                    "ticker": h.ticker,
                    "market": h.market_code,
                    "shares": h.shares,
                    "cost basis": h.cost_basis,
                    "currency": h.currency,
                    "added": h.date_added.isoformat(),
                }
                for h in holdings
            ],
            use_container_width=True,
        )
    else:
        st.info("No holdings yet.")

    st.divider()
    st.subheader("Add a holding")
    with st.form("add_holding", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            t = st.text_input("Ticker", value="")
            mk = st.selectbox("Market", ["US", "NSE", "BSE"], index=0)
        with c2:
            sh = st.number_input("Shares", min_value=0.0, step=1.0)
            cb = st.number_input("Cost basis (per share, native currency)", min_value=0.0, step=1.0)
        with c3:
            d = st.date_input("Date added", value=date_.today())
        submit = st.form_submit_button("Add / update")
        if submit and t and sh > 0:
            market = Market.from_code(mk)
            symbol, market = parse_ticker(t, default_market=market)
            store.upsert(Holding(
                ticker=symbol, market_code=market.code, shares=float(sh),
                cost_basis=float(cb), currency=market.currency, date_added=d,
            ))
            st.success(f"Added/updated {symbol}.{market.code}.")
            _quick_card.clear()
            st.rerun()

    st.divider()
    st.subheader("Import CSV")
    st.caption(
        "Auto-detects ICICI Direct's PortFolioEqtSummary export (uses ISIN to "
        "resolve NSE tickers) **or** the canonical "
        "`ticker, market, shares, cost_basis, date` format. See "
        "`examples/portfolio.example.csv`."
    )
    up = st.file_uploader("portfolio.csv", type=["csv"])
    replace = st.checkbox("Replace existing holdings", value=False)
    if up is not None and st.button("Import"):
        tmp = Path(".upload.csv")
        tmp.write_bytes(up.getvalue())
        progress = st.progress(0.0, text="resolving tickers...")
        last_msg = st.empty()

        def _on_resolve(i: int, total: int, key: str, resolved: Optional[str]) -> None:
            progress.progress(i / total, text=f"resolving {i}/{total}: {key}")
            last_msg.caption(f"{key} -> {resolved or '(unresolved)'}")

        try:
            result = import_csv_file(tmp, on_resolve=_on_resolve)
        finally:
            tmp.unlink(missing_ok=True)
            progress.empty()
            last_msg.empty()

        if result.errors:
            st.warning(f"{len(result.errors)} row(s) had problems:")
            rows = [
                {
                    "reason": err.reason,
                    "isin": err.raw.get("isin") if isinstance(err.raw, dict) else "",
                    "name": err.raw.get("name") if isinstance(err.raw, dict) else "",
                    "broker_symbol": err.raw.get("broker_symbol") if isinstance(err.raw, dict) else "",
                }
                for err in result.errors
            ]
            st.dataframe(rows, use_container_width=True)
            st.caption(
                "To fix unresolved rows, create `.ticker_overrides.json` in the "
                "project root with `{\"ISIN\": \"NSE_SYMBOL\"}` entries and "
                "re-import."
            )
        if result.holdings:
            if replace:
                for h in store.all():
                    store.remove(h.ticker, h.market_code)
            for h in result.holdings:
                store.upsert(h)
            st.success(f"Imported {len(result.holdings)} holding(s).")
            _quick_card.clear()
            st.rerun()


