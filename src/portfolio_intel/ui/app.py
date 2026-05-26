"""Portfolio Intelligence — Streamlit dashboard.

Design choices, informed by CLAUDE.md and the user's downside-protection lens:
- Compact cards in a grid, expandable to full detail. 15-stock portfolio
  scannable in ~30 seconds.
- Sell / Strong Sell signals get the loudest colour — those are the ones
  worth acting on for a downside-protection user.
- Per-currency summary strip at the top — CLAUDE.md forbids silent FX
  mixing, so each currency gets its own metric block.
- Today's batch markdown files (if present) are read first; the LLM
  synthesis only runs on demand (button) because it's CPU-slow.
- No new computation lives here; this is a view layer.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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
from portfolio_intel.scoring.weights import DEFAULT_WEIGHTS


st.set_page_config(
    page_title="Portfolio Intelligence",
    layout="wide",
    page_icon="📊",
    initial_sidebar_state="expanded",
)


# ---------------- Styling ----------------

SIGNAL_STYLES = {
    "Strong Sell": ("#7f1d1d", "#fff", "🔻"),
    "Sell":        ("#dc2626", "#fff", "⬇"),
    "Hold":        ("#52525b", "#fff", "—"),
    "Buy":         ("#16a34a", "#fff", "⬆"),
    "Strong Buy":  ("#15803d", "#fff", "🚀"),
}
SIGNAL_ORDER = ["Strong Sell", "Sell", "Hold", "Buy", "Strong Buy"]

CUSTOM_CSS = """
<style>
/* Card container */
.stock-card {
    background: var(--secondary-background-color, #fafafa);
    border: 1px solid rgba(120,120,120,0.18);
    border-radius: 10px;
    padding: 14px 16px 12px 16px;
    margin-bottom: 8px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    transition: box-shadow 0.15s ease-in-out;
}
.stock-card:hover {
    box-shadow: 0 3px 10px rgba(0,0,0,0.08);
}
.stock-card .ticker {
    font-size: 1.05rem; font-weight: 700; letter-spacing: 0.2px;
}
.stock-card .market {
    font-size: 0.72rem; color: #6b7280; font-weight: 500;
    text-transform: uppercase; letter-spacing: 0.5px; margin-left: 6px;
}
.stock-card .price {
    font-size: 1.35rem; font-weight: 600; margin: 4px 0 2px 0;
}
.stock-card .change-up   { color: #16a34a; font-weight: 500; }
.stock-card .change-down { color: #dc2626; font-weight: 500; }
.stock-card .change-flat { color: #6b7280; font-weight: 500; }
.stock-card .meta {
    font-size: 0.82rem; color: #6b7280; margin: 2px 0;
}
.stock-card .pnl-row {
    margin-top: 6px; padding-top: 6px;
    border-top: 1px dashed rgba(120,120,120,0.25);
    font-size: 0.85rem;
}
.stock-card .setup {
    font-size: 0.78rem; color: #4b5563; margin-top: 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.sig-pill {
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-weight: 600; font-size: 0.78rem; letter-spacing: 0.3px;
}
.tag {
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 0.7rem; font-weight: 500; margin-right: 4px;
    background: rgba(120,120,120,0.12); color: #374151;
}
.tag-warn { background: #fef3c7; color: #92400e; }
.tag-bad  { background: #fee2e2; color: #991b1b; }
.tag-good { background: #dcfce7; color: #166534; }
.summary-label { font-size: 0.7rem; color: #6b7280;
    text-transform: uppercase; letter-spacing: 0.5px; }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def signal_pill(label: str, score: float) -> str:
    bg, fg, glyph = SIGNAL_STYLES.get(label, ("#52525b", "#fff", "—"))
    return (
        f"<span class='sig-pill' style='background:{bg};color:{fg}'>"
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
def _quick_card(symbol: str, market_code: str, period: str) -> dict | None:
    """Compute the data + signals + setup for one ticker (no LLM, no portfolio
    context). Cached for 5 minutes per (ticker, market, period)."""
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
        return {"error": str(e), "symbol": symbol, "market_code": market_code}

    return {
        "symbol": symbol,
        "market_code": market_code,
        "currency": market.currency,
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
    }


def _holding_for(store: PortfolioStore, symbol: str, market: Market) -> Holding | None:
    return store.get(symbol, market.code)


@dataclass
class CardRow:
    """A card + its holding + computed portfolio context, ready to filter/sort."""
    card: dict
    holding: Optional[Holding]
    market_value: float = 0.0
    cost_total: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    weight_pct: float | None = None
    overweight: bool = False


def _build_rows(items: list[BatchItem], period: str) -> list[CardRow]:
    """Pull quick-card data for each item and compute per-row P&L + weight."""
    rows: list[CardRow] = []
    bucket_totals: dict[str, float] = defaultdict(float)

    # First pass: fetch cards + market values per currency bucket.
    for it in items:
        c = _quick_card(it.symbol, it.market.code, period)
        if c is None:
            continue
        row = CardRow(card=c, holding=it.holding)
        if it.holding and not c.get("error") and c.get("price") is not None:
            row.market_value = float(c["price"]) * it.holding.shares
            row.cost_total = it.holding.cost_basis * it.holding.shares
            row.pnl = row.market_value - row.cost_total
            row.pnl_pct = (row.pnl / row.cost_total * 100.0) if row.cost_total else 0.0
            bucket_totals[it.holding.currency] += row.market_value
        rows.append(row)

    # Second pass: weight + overweight flag.
    for row in rows:
        if row.holding and row.market_value > 0:
            total = bucket_totals.get(row.holding.currency, 0.0)
            if total > 0:
                row.weight_pct = row.market_value / total * 100.0
                row.overweight = row.weight_pct > DEFAULT_WEIGHTS.overweight_pct

    return rows


# ---------------- Card renderer ----------------

def _render_card(row: CardRow, out_dir: Path, model: str) -> None:
    c = row.card
    if c.get("error"):
        st.markdown(
            f"<div class='stock-card'><div class='ticker'>"
            f"{c.get('symbol','?')}<span class='market'>{c.get('market_code','?')}</span></div>"
            f"<div class='meta tag tag-bad' style='margin-top:8px'>error: {c['error']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    sym = c["currency_symbol"]
    symbol = c["symbol"]
    market_code = c["market_code"]
    holding = row.holding

    chg = c.get("change_pct")
    if chg is None:
        chg_html = ""
    elif chg > 0:
        chg_html = f"<span class='change-up'>▲ {chg:+.2f}%</span>"
    elif chg < 0:
        chg_html = f"<span class='change-down'>▼ {chg:+.2f}%</span>"
    else:
        chg_html = f"<span class='change-flat'>0.00%</span>"

    stale_tag = "<span class='tag tag-warn'>stale</span>" if c.get("stale") else ""
    ow_tag = "<span class='tag tag-warn'>overweight</span>" if row.overweight else ""

    header_html = (
        f"<div class='stock-card'>"
        f"<div style='display:flex;justify-content:space-between;align-items:flex-start'>"
        f"<div><span class='ticker'>{symbol}</span>"
        f"<span class='market'>{market_code}</span></div>"
        f"<div>{signal_pill(c['score_label'], c['score_value'])}</div>"
        f"</div>"
        f"<div class='price'>{sym}{c['price']:,.2f} &nbsp;{chg_html}</div>"
        f"<div class='meta'>RSI {c['rsi']:.0f} · {c['trend']} · "
        f"news {c['sentiment_total']} ({c['sentiment_label']}) "
        f"{stale_tag}{ow_tag}</div>"
    )

    if holding is not None and row.cost_total > 0:
        pnl_color = "change-up" if row.pnl >= 0 else "change-down"
        weight_txt = f" · {row.weight_pct:.1f}% of {holding.currency}" if row.weight_pct else ""
        header_html += (
            f"<div class='pnl-row'>"
            f"{holding.shares:g} sh @ {sym}{holding.cost_basis:,.2f} → "
            f"<span class='{pnl_color}'>{sym}{row.pnl:,.2f} ({row.pnl_pct:+.2f}%)</span>"
            f"{weight_txt}</div>"
        )

    if c.get("setup_valid") and c.get("setup_target"):
        header_html += (
            f"<div class='setup'>📐 entry {sym}{c['setup_entry']:,.2f} · "
            f"stop {sym}{c['setup_stop']:,.2f} · target {sym}{c['setup_target']:,.2f} · "
            f"RR {c['setup_rr']:.1f}:1</div>"
        )

    header_html += "</div>"
    st.markdown(header_html, unsafe_allow_html=True)

    md_path = _existing_md_for(symbol, Market.from_code(market_code), out_dir)
    with st.expander("Full digest", expanded=False):
        if md_path is not None:
            st.markdown(md_path.read_text(encoding="utf-8"))
            st.caption(f"_from {md_path}_")
        else:
            st.info("No full digest cached for today.")
            if st.button(
                f"Generate digest for {symbol}.{market_code}",
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


# ---------------- Summary strip ----------------

def _render_summary(rows: list[CardRow]) -> None:
    """Per-currency totals + signal counts. CLAUDE.md: never silently mix
    currencies into one number."""
    valid = [r for r in rows if r.holding and not r.card.get("error")]

    # Per-currency totals.
    by_ccy: dict[str, dict[str, float]] = defaultdict(lambda: {"mv": 0.0, "cost": 0.0, "n": 0})
    for r in valid:
        sym = r.card["currency_symbol"]
        by_ccy[sym]["mv"] += r.market_value
        by_ccy[sym]["cost"] += r.cost_total
        by_ccy[sym]["n"] += 1

    # Signal counts (across all rows that resolved, holding or not).
    sig_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        lbl = r.card.get("score_label")
        if lbl:
            sig_counts[lbl] += 1

    if not by_ccy and not sig_counts:
        return

    # Render currency totals as metric tiles, one column per currency.
    ccy_items = list(by_ccy.items())
    if ccy_items:
        cols = st.columns(len(ccy_items) + 1)
        for col, (sym, agg) in zip(cols[:-1], ccy_items):
            pnl = agg["mv"] - agg["cost"]
            pnl_pct = (pnl / agg["cost"] * 100.0) if agg["cost"] else 0.0
            col.metric(
                label=f"{sym} portfolio ({int(agg['n'])} positions)",
                value=f"{sym}{agg['mv']:,.0f}",
                delta=f"{pnl:+,.0f} ({pnl_pct:+.2f}%)",
                delta_color="normal",
            )
        # Last column: signal counts.
        with cols[-1]:
            st.markdown("<div class='summary-label'>signals</div>", unsafe_allow_html=True)
            pills = []
            for lbl in SIGNAL_ORDER:
                n = sig_counts.get(lbl, 0)
                if n == 0:
                    continue
                bg, fg, glyph = SIGNAL_STYLES[lbl]
                pills.append(
                    f"<span class='sig-pill' style='background:{bg};color:{fg};"
                    f"margin-right:4px'>{glyph} {n}</span>"
                )
            st.markdown(
                " ".join(pills) if pills else "<span class='summary-label'>no signals yet</span>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown("<div class='summary-label'>no holdings — use Lookup or Portfolio tab</div>",
                    unsafe_allow_html=True)


# ---------------- Sidebar ----------------

with st.sidebar:
    st.title("📊 Portfolio Intelligence")
    st.caption("Personal stock analysis · facts → signals → grounded synthesis")

    with st.expander("⚙ Settings", expanded=False):
        db_path = st.text_input("Database", value="portfolio.db")
        period = st.selectbox("History window", ["6mo", "1y", "2y", "5y"], index=1)
        out_dir = Path(st.text_input("Digest output dir", value="digests"))
        model = st.text_input("Ollama model", value=DEFAULT_MODEL)

    st.divider()
    st.markdown("**Filters**")
    sig_filter = st.multiselect(
        "Signal", SIGNAL_ORDER, default=[],
        help="Empty = show all signals.",
    )
    mkt_filter = st.multiselect(
        "Market", ["US", "NSE", "BSE"], default=[],
        help="Empty = all markets.",
    )
    pos_filter = st.selectbox(
        "Position",
        ["All", "Overweight only", "Winners (P&L > 0)", "Losers (P&L < 0)"],
        index=0,
    )
    search = st.text_input("Search ticker", value="", placeholder="e.g. RELI").strip().upper()

    st.divider()
    sort_by = st.selectbox(
        "Sort by",
        ["Signal (Sell first)", "Signal (Buy first)", "Ticker",
         "Weight (largest first)", "P&L % (worst first)", "P&L % (best first)"],
        index=0,
    )

    st.divider()
    if st.button("🔄 Refresh data cache", use_container_width=True):
        _quick_card.clear()
        st.rerun()


store = _store(db_path)


# ---------------- Tabs ----------------

tab_dash, tab_lookup, tab_portfolio = st.tabs(["📈 Dashboard", "🔍 Lookup", "💼 Portfolio"])


# ====================== Dashboard ======================

with tab_dash:
    items = items_from_portfolio(store)

    if not items:
        st.info(
            "**No holdings yet.** Use the **💼 Portfolio** tab to import a CSV "
            "or add a holding manually, or jump to **🔍 Lookup** to analyse any ticker."
        )
    else:
        # Build all rows once (cached at the _quick_card layer).
        with st.spinner(f"loading {len(items)} holding(s)..."):
            rows = _build_rows(items, period)

        _render_summary(rows)
        st.divider()

        # Top action bar.
        bar = st.columns([3, 1, 1])
        with bar[0]:
            st.caption("Sell / Strong Sell get the loudest colour — those are the ones to act on.")
        with bar[2]:
            run_full = st.button(
                "🤖 Generate today's batch (LLM)",
                help="Runs the full digest pipeline including LLM synthesis. Slow on CPU.",
                use_container_width=True,
            )

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
            st.rerun()

        # Apply filters.
        filtered = rows
        if sig_filter:
            filtered = [r for r in filtered if r.card.get("score_label") in sig_filter]
        if mkt_filter:
            filtered = [r for r in filtered if r.card.get("market_code") in mkt_filter]
        if pos_filter == "Overweight only":
            filtered = [r for r in filtered if r.overweight]
        elif pos_filter == "Winners (P&L > 0)":
            filtered = [r for r in filtered if r.holding and r.pnl > 0]
        elif pos_filter == "Losers (P&L < 0)":
            filtered = [r for r in filtered if r.holding and r.pnl < 0]
        if search:
            filtered = [r for r in filtered if search in r.card.get("symbol", "")]

        # Sort.
        sell_idx = {lbl: i for i, lbl in enumerate(SIGNAL_ORDER)}
        buy_idx = {lbl: i for i, lbl in enumerate(reversed(SIGNAL_ORDER))}
        if sort_by == "Signal (Sell first)":
            filtered.sort(key=lambda r: sell_idx.get(r.card.get("score_label", ""), 99))
        elif sort_by == "Signal (Buy first)":
            filtered.sort(key=lambda r: buy_idx.get(r.card.get("score_label", ""), 99))
        elif sort_by == "Ticker":
            filtered.sort(key=lambda r: r.card.get("symbol", ""))
        elif sort_by == "Weight (largest first)":
            filtered.sort(key=lambda r: -(r.weight_pct or 0))
        elif sort_by == "P&L % (worst first)":
            filtered.sort(key=lambda r: r.pnl_pct)
        elif sort_by == "P&L % (best first)":
            filtered.sort(key=lambda r: -r.pnl_pct)

        st.caption(f"Showing **{len(filtered)}** of {len(rows)} holdings.")

        if not filtered:
            st.info("No holdings match the current filters.")
        else:
            for row_start in range(0, len(filtered), 3):
                cols = st.columns(3, gap="small")
                for col, row in zip(cols, filtered[row_start:row_start + 3]):
                    with col:
                        _render_card(row, out_dir, model)


# ====================== Lookup ======================

with tab_lookup:
    st.subheader("Look up any ticker")
    st.caption("Same pipeline as your portfolio — works for any US/NSE/BSE ticker, even one you don't own.")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        raw_ticker = st.text_input("Ticker", value="AAPL",
                                   help="Bare symbol (AAPL) or qualified (RELIANCE.NS).")
    with col2:
        market_flag = st.selectbox("Market", ["(auto)", "US", "NSE", "BSE"], index=0,
                                   help="Used when ticker is bare (no .NS / .BO suffix).")
    with col3:
        run_llm_lookup = st.checkbox("Run LLM synthesis", value=False,
                                     help="Slow on CPU. Off = signals + setup only.")

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
    # CSV import is the most-used action — put it first.
    st.subheader("📥 Import CSV")
    st.caption(
        "Auto-detects ICICI Direct's PortFolioEqtSummary export (resolves NSE tickers from ISIN) "
        "**or** the canonical `ticker, market, shares, cost_basis, date` format. "
        "See `examples/portfolio.example.csv`."
    )
    up = st.file_uploader("Drop a CSV here", type=["csv"], label_visibility="collapsed")
    cols = st.columns([1, 3])
    with cols[0]:
        replace = st.checkbox("Replace existing holdings", value=False)
    with cols[1]:
        do_import = st.button("Import", type="primary", disabled=(up is None))
    if up is not None and do_import:
        tmp = Path(".upload.csv")
        tmp.write_bytes(up.getvalue())
        progress = st.progress(0.0, text="resolving tickers...")
        last_msg = st.empty()

        def _on_resolve(i: int, total: int, key: str, resolved: Optional[str]) -> None:
            progress.progress(i / total, text=f"resolving {i}/{total}: {key}")
            last_msg.caption(f"{key} → {resolved or '(unresolved)'}")

        try:
            result = import_csv_file(tmp, on_resolve=_on_resolve)
        finally:
            tmp.unlink(missing_ok=True)
            progress.empty()
            last_msg.empty()

        if result.errors:
            st.warning(f"{len(result.errors)} row(s) had problems:")
            rows_err = [
                {
                    "reason": err.reason,
                    "isin": err.raw.get("isin") if isinstance(err.raw, dict) else "",
                    "name": err.raw.get("name") if isinstance(err.raw, dict) else "",
                    "broker_symbol": err.raw.get("broker_symbol") if isinstance(err.raw, dict) else "",
                }
                for err in result.errors
            ]
            st.dataframe(rows_err, use_container_width=True)
            st.caption(
                "To fix unresolved rows, add entries to `.ticker_overrides.json` "
                "in the project root (`{\"ISIN\": \"NSE_SYMBOL\"}`) and re-import."
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

    st.divider()

    # Holdings table.
    st.subheader("📋 Current holdings")
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
            hide_index=True,
        )

        with st.expander("🗑 Remove a holding"):
            rm_cols = st.columns([2, 1, 1])
            with rm_cols[0]:
                rm_choice = st.selectbox(
                    "Pick one",
                    [f"{h.ticker}.{h.market_code}" for h in holdings],
                    key="rm_choice",
                )
            with rm_cols[2]:
                if st.button("Remove", type="secondary"):
                    sym, mkt = rm_choice.rsplit(".", 1)
                    store.remove(sym, mkt)
                    _quick_card.clear()
                    st.success(f"Removed {rm_choice}.")
                    st.rerun()
    else:
        st.info("No holdings yet. Import a CSV above or add one manually below.")

    st.divider()
    st.subheader("➕ Add a holding manually")
    with st.form("add_holding", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            t = st.text_input("Ticker", value="")
            mk = st.selectbox("Market", ["US", "NSE", "BSE"], index=0)
        with c2:
            sh = st.number_input("Shares", min_value=0.0, step=1.0)
            cb = st.number_input("Cost basis (per share, native currency)",
                                 min_value=0.0, step=1.0)
        with c3:
            d = st.date_input("Date added", value=date_.today())
        submit = st.form_submit_button("Add / update", type="primary")
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
