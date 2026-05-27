"""Portfolio Intelligence — Streamlit dashboard.

Design choices, informed by CLAUDE.md and the user's downside-protection lens:
- Compact cards in a responsive grid with inline price sparklines; a 15-stock
  portfolio is scannable in ~30 seconds.
- Sell / Strong Sell signals get the loudest colour — those are the ones
  worth acting on for a downside-protection user.
- A "Needs attention" spotlight surfaces strong sells + overweight positions
  before the full grid, so the most important holdings can't be missed.
- Per-currency summary strip at the top — CLAUDE.md forbids silent FX
  mixing, so each currency gets its own metric block.
- Filters live in a horizontal toolbar above the grid (not buried in the
  sidebar) so they feel like part of the dashboard.
- Today's batch markdown files (if present) are read first; the LLM
  synthesis only runs on demand (button) because it's CPU-slow.
- Rows are cached in session_state so filter changes don't trigger
  re-fetching — only the explicit "Refresh data" button does.
- No new computation lives here; this is a view layer.
"""
from __future__ import annotations

import pickle
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_, datetime
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
    initial_sidebar_state="collapsed",
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
SIGNAL_LINE_COLOR = {
    "Strong Sell": "#7f1d1d",
    "Sell":        "#dc2626",
    "Hold":        "#737373",
    "Buy":         "#16a34a",
    "Strong Buy":  "#15803d",
}

CUSTOM_CSS = """
<style>
/* Tighten Streamlit defaults so the page feels like an app, not a doc. */
.block-container { padding-top: 1.2rem !important; padding-bottom: 2rem !important; max-width: 1400px; }
header[data-testid="stHeader"] { background: transparent; }
section[data-testid="stSidebar"] { background: #fafafa; }

/* App-style top bar */
.topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 6px 0 14px 0; border-bottom: 1px solid rgba(120,120,120,0.18);
    margin-bottom: 18px;
}
.topbar .app-title { font-size: 1.25rem; font-weight: 700; letter-spacing: -0.2px; }
.topbar .app-subtitle { font-size: 0.78rem; color: #6b7280; margin-top: 2px; }

/* KPI tiles */
.kpi-grid { display: grid; gap: 12px; margin-bottom: 18px; }
.kpi {
    background: #fff; border: 1px solid rgba(120,120,120,0.18);
    border-radius: 12px; padding: 14px 18px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.kpi .label {
    font-size: 0.7rem; color: #6b7280;
    text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600;
}
.kpi .value { font-size: 1.6rem; font-weight: 700; margin: 4px 0 2px 0; }
.kpi .delta-up   { color: #16a34a; font-size: 0.85rem; font-weight: 600; }
.kpi .delta-down { color: #dc2626; font-size: 0.85rem; font-weight: 600; }
.kpi .delta-flat { color: #6b7280; font-size: 0.85rem; font-weight: 600; }
.kpi .meta { font-size: 0.75rem; color: #6b7280; margin-top: 2px; }

/* Stock card */
.stock-card {
    background: #fff;
    border: 1px solid rgba(120,120,120,0.18);
    border-radius: 12px;
    padding: 14px 16px 12px 16px;
    margin-bottom: 8px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    transition: box-shadow 0.15s, transform 0.15s;
    min-height: 178px;
}
.stock-card:hover {
    box-shadow: 0 4px 14px rgba(0,0,0,0.08);
    transform: translateY(-1px);
}
.stock-card.attention {
    border-left: 4px solid #dc2626;
}
.stock-card .head {
    display: flex; justify-content: space-between; align-items: center;
}
.stock-card .ticker { font-size: 1.05rem; font-weight: 700; letter-spacing: 0.2px; }
.stock-card .market {
    font-size: 0.7rem; color: #6b7280; font-weight: 500;
    text-transform: uppercase; letter-spacing: 0.5px; margin-left: 6px;
}
.stock-card .pricerow {
    display: flex; justify-content: space-between; align-items: flex-end;
    margin: 6px 0 2px 0;
}
.stock-card .price { font-size: 1.4rem; font-weight: 600; line-height: 1.1; }
.stock-card .chg-up   { color: #16a34a; font-weight: 500; font-size: 0.9rem; }
.stock-card .chg-down { color: #dc2626; font-weight: 500; font-size: 0.9rem; }
.stock-card .chg-flat { color: #6b7280; font-weight: 500; font-size: 0.9rem; }
.stock-card .meta {
    font-size: 0.78rem; color: #6b7280; margin: 4px 0 6px 0;
    display: flex; flex-wrap: wrap; gap: 6px;
}
.stock-card .spark { margin: 4px 0 6px 0; }
.stock-card .pnl-row {
    margin-top: 6px; padding-top: 6px;
    border-top: 1px dashed rgba(120,120,120,0.25);
    font-size: 0.85rem;
}
.stock-card .setup {
    font-size: 0.75rem; color: #4b5563; margin-top: 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

/* Signal pill */
.sig-pill {
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    font-weight: 600; font-size: 0.74rem; letter-spacing: 0.3px;
    white-space: nowrap;
}

/* Tags */
.tag {
    display: inline-block; padding: 1px 8px; border-radius: 999px;
    font-size: 0.68rem; font-weight: 600;
    background: rgba(120,120,120,0.12); color: #374151;
}
.tag-warn { background: #fef3c7; color: #92400e; }
.tag-bad  { background: #fee2e2; color: #991b1b; }
.tag-good { background: #dcfce7; color: #166534; }

/* Section headers */
.section-h {
    display: flex; align-items: baseline; justify-content: space-between;
    margin: 24px 0 10px 0; padding-bottom: 6px;
    border-bottom: 1px solid rgba(120,120,120,0.18);
}
.section-h .title { font-size: 1.05rem; font-weight: 700; letter-spacing: -0.2px; }
.section-h .sub { font-size: 0.78rem; color: #6b7280; }
.attention-banner {
    background: #fef2f2; border: 1px solid #fecaca;
    border-radius: 10px; padding: 10px 14px; margin-bottom: 10px;
    color: #991b1b; font-weight: 600; font-size: 0.85rem;
}

/* Empty state */
.empty {
    text-align: center; padding: 50px 20px;
    background: #fafafa; border: 1px dashed #d4d4d8;
    border-radius: 12px; color: #6b7280;
}
.empty .big { font-size: 1.1rem; font-weight: 600; color: #374151; margin-bottom: 4px; }

/* Dark mode tweaks (Streamlit's dark theme inverts some bg vars). */
@media (prefers-color-scheme: dark) {
    .kpi, .stock-card { background: #1c1c1c; border-color: rgba(255,255,255,0.1); }
    .kpi .value, .stock-card .ticker { color: #f5f5f5; }
    .attention-banner { background: #2a1010; border-color: #5b2020; color: #fca5a5; }
    .empty { background: #161616; border-color: #303030; }
    section[data-testid="stSidebar"] { background: #131313; }
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------- Helpers: HTML fragments ----------------

def _signal_pill_html(label: str, score: float) -> str:
    bg, fg, glyph = SIGNAL_STYLES.get(label, ("#52525b", "#fff", "—"))
    return (
        f"<span class='sig-pill' style='background:{bg};color:{fg}'>"
        f"{glyph} {label} ({score:+.1f})</span>"
    )


def _sparkline_svg(closes: list[float], color: str = "#16a34a", width: int = 220, height: int = 36) -> str:
    """Render a tiny inline SVG sparkline from a list of closes. No deps."""
    if not closes or len(closes) < 2:
        return ""
    lo, hi = min(closes), max(closes)
    rng = (hi - lo) or 1.0
    pad_y = 2
    pts = []
    n = len(closes)
    for i, v in enumerate(closes):
        x = i * (width - 2) / (n - 1) + 1
        y = height - pad_y - (v - lo) / rng * (height - 2 * pad_y)
        pts.append(f"{x:.1f},{y:.1f}")
    # Choose line color from price direction if not provided explicitly.
    polyline = (
        f"<polyline fill='none' stroke='{color}' stroke-width='1.6' "
        f"stroke-linecap='round' stroke-linejoin='round' points='{' '.join(pts)}'/>"
    )
    # Subtle fill underneath
    poly_fill = f"M1,{height-pad_y} " + " ".join(f"L{p}" for p in pts) + f" L{width-1},{height-pad_y} Z"
    fill = (
        f"<path d='{poly_fill}' fill='{color}' fill-opacity='0.08'/>"
    )
    return (
        f"<svg class='spark' width='100%' height='{height}' viewBox='0 0 {width} {height}' "
        f"preserveAspectRatio='none'>{fill}{polyline}</svg>"
    )


# ---------------- State ----------------

def _store(db_path: str) -> PortfolioStore:
    return PortfolioStore(db_path)


@st.cache_resource
def _source() -> YFinanceSource:
    return YFinanceSource()


# ---------------- Disk persistence for the rows cache ----------------
#
# Streamlit's session_state lives only as long as the browser session, so a
# page refresh or server restart causes a re-fetch. We pickle the computed
# rows to a small file in cwd so the dashboard loads instantly on cold start
# and only refetches when the user clicks Refresh (or the cache ages past
# ROWS_CACHE_TTL_S, in which case we still show the stale rows AND surface
# a banner offering a refresh — never blocking the page on first paint).

ROWS_CACHE_FILE = Path(".rows_cache.pkl")
ROWS_CACHE_TTL_S = 60 * 60  # 1 hour — quotes from market hours are fresher than this anyway


def _load_rows_disk() -> dict | None:
    if not ROWS_CACHE_FILE.exists():
        return None
    try:
        with ROWS_CACHE_FILE.open("rb") as f:
            return pickle.load(f)
    except (pickle.UnpicklingError, EOFError, AttributeError, ImportError):
        # Schema drift or corruption — drop the file, treat as cold.
        try:
            ROWS_CACHE_FILE.unlink()
        except OSError:
            pass
        return None


def _save_rows_disk(payload: dict) -> None:
    try:
        with ROWS_CACHE_FILE.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError:
        pass  # caching is best-effort


def _invalidate_rows_cache() -> None:
    st.session_state.pop("rows_cache", None)
    try:
        ROWS_CACHE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------- Data fetch ----------------

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
        "recent_closes": digest.recent_closes,
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

    for row in rows:
        if row.holding and row.market_value > 0:
            total = bucket_totals.get(row.holding.currency, 0.0)
            if total > 0:
                row.weight_pct = row.market_value / total * 100.0
                row.overweight = row.weight_pct > DEFAULT_WEIGHTS.overweight_pct

    return rows


# ---------------- Card renderer ----------------

def _render_card(row: CardRow, out_dir: Path, model: str, *, attention: bool = False, scope: str = "grid") -> None:
    c = row.card
    if c.get("error"):
        st.markdown(
            f"<div class='stock-card'><div class='head'>"
            f"<div><span class='ticker'>{c.get('symbol','?')}</span>"
            f"<span class='market'>{c.get('market_code','?')}</span></div></div>"
            f"<div class='meta'><span class='tag tag-bad'>error</span> {c['error']}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    sym = c["currency_symbol"]
    symbol = c["symbol"]
    market_code = c["market_code"]
    holding = row.holding
    closes = c.get("recent_closes") or []

    chg = c.get("change_pct")
    if chg is None:
        chg_html = ""
    elif chg > 0:
        chg_html = f"<span class='chg-up'>▲ {chg:+.2f}%</span>"
    elif chg < 0:
        chg_html = f"<span class='chg-down'>▼ {chg:+.2f}%</span>"
    else:
        chg_html = "<span class='chg-flat'>0.00%</span>"

    # Sparkline color follows the signal so the line carries directional weight.
    spark_color = SIGNAL_LINE_COLOR.get(c["score_label"], "#737373")
    spark_html = _sparkline_svg(closes, color=spark_color)

    tags = []
    if c.get("stale"):
        tags.append("<span class='tag tag-warn'>stale</span>")
    if row.overweight:
        tags.append("<span class='tag tag-warn'>overweight</span>")
    if row.pnl_pct < -10:
        tags.append("<span class='tag tag-bad'>−10%+</span>")
    tags_html = " ".join(tags)

    attention_cls = " attention" if attention else ""

    html = (
        f"<div class='stock-card{attention_cls}'>"
        f"<div class='head'>"
        f"<div><span class='ticker'>{symbol}</span>"
        f"<span class='market'>{market_code}</span></div>"
        f"<div>{_signal_pill_html(c['score_label'], c['score_value'])}</div>"
        f"</div>"
        f"<div class='pricerow'>"
        f"<div class='price'>{sym}{c['price']:,.2f}</div>"
        f"<div>{chg_html}</div>"
        f"</div>"
        f"{spark_html}"
        f"<div class='meta'>"
        f"<span>RSI {c['rsi']:.0f}</span>"
        f"<span>· {c['trend']}</span>"
        f"<span>· news {c['sentiment_total']} ({c['sentiment_label']})</span>"
        f"{(' &nbsp;' + tags_html) if tags_html else ''}"
        f"</div>"
    )

    if holding is not None and row.cost_total > 0:
        pnl_color = "chg-up" if row.pnl >= 0 else "chg-down"
        weight_txt = f" · <strong>{row.weight_pct:.1f}%</strong> of {holding.currency}" if row.weight_pct else ""
        html += (
            f"<div class='pnl-row'>"
            f"{holding.shares:g} sh @ {sym}{holding.cost_basis:,.2f} → "
            f"<span class='{pnl_color}'>{sym}{row.pnl:,.2f} ({row.pnl_pct:+.2f}%)</span>"
            f"{weight_txt}</div>"
        )

    if c.get("setup_valid") and c.get("setup_target"):
        html += (
            f"<div class='setup'>📐 entry {sym}{c['setup_entry']:,.2f} · "
            f"stop {sym}{c['setup_stop']:,.2f} · target {sym}{c['setup_target']:,.2f} · "
            f"RR {c['setup_rr']:.1f}:1</div>"
        )

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

    md_path = _existing_md_for(symbol, Market.from_code(market_code), out_dir)
    with st.expander("📄 Full digest"):
        if md_path is not None:
            st.markdown(md_path.read_text(encoding="utf-8"))
            st.caption(f"_from {md_path}_")
        else:
            st.caption("No full digest cached for today.")
            if st.button(
                f"Generate digest for {symbol}.{market_code}",
                key=f"gen_{scope}_{symbol}_{market_code}",
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


# ---------------- KPI / spotlight sections ----------------

def _render_kpis(rows: list[CardRow]) -> None:
    valid = [r for r in rows if r.holding and not r.card.get("error")]

    by_ccy: dict[str, dict[str, float]] = defaultdict(lambda: {"mv": 0.0, "cost": 0.0, "n": 0})
    for r in valid:
        sym = r.card["currency_symbol"]
        by_ccy[sym]["mv"] += r.market_value
        by_ccy[sym]["cost"] += r.cost_total
        by_ccy[sym]["n"] += 1

    sig_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        lbl = r.card.get("score_label")
        if lbl:
            sig_counts[lbl] += 1

    n_overweight = sum(1 for r in rows if r.overweight)

    ccy_items = list(by_ccy.items())
    # Layout: one tile per currency + signals tile + position-state tile.
    n_tiles = len(ccy_items) + 2
    cols = st.columns(n_tiles, gap="small")

    for col, (sym, agg) in zip(cols[:len(ccy_items)], ccy_items):
        pnl = agg["mv"] - agg["cost"]
        pnl_pct = (pnl / agg["cost"] * 100.0) if agg["cost"] else 0.0
        d_cls = "delta-up" if pnl > 0 else ("delta-down" if pnl < 0 else "delta-flat")
        d_arrow = "▲" if pnl > 0 else ("▼" if pnl < 0 else "—")
        with col:
            st.markdown(
                f"<div class='kpi'>"
                f"<div class='label'>{sym} portfolio</div>"
                f"<div class='value'>{sym}{agg['mv']:,.0f}</div>"
                f"<div class='{d_cls}'>{d_arrow} {sym}{abs(pnl):,.0f} ({pnl_pct:+.2f}%)</div>"
                f"<div class='meta'>{int(agg['n'])} positions · cost {sym}{agg['cost']:,.0f}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Signals tile
    with cols[len(ccy_items)]:
        pills = []
        for lbl in SIGNAL_ORDER:
            n = sig_counts.get(lbl, 0)
            if n == 0:
                continue
            bg, fg, glyph = SIGNAL_STYLES[lbl]
            pills.append(
                f"<span class='sig-pill' style='background:{bg};color:{fg};"
                f"margin:2px 4px 2px 0;display:inline-block'>{glyph} {n}</span>"
            )
        body = " ".join(pills) if pills else "<div class='meta'>no signals yet</div>"
        st.markdown(
            f"<div class='kpi'>"
            f"<div class='label'>signals</div>"
            f"<div style='margin-top:8px'>{body}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # Position-state tile
    with cols[len(ccy_items) + 1]:
        winners = sum(1 for r in valid if r.pnl > 0)
        losers = sum(1 for r in valid if r.pnl < 0)
        st.markdown(
            f"<div class='kpi'>"
            f"<div class='label'>positions</div>"
            f"<div class='value' style='font-size:1.05rem;margin-top:8px'>"
            f"<span class='chg-up'>{winners} winners</span> · "
            f"<span class='chg-down'>{losers} losers</span></div>"
            f"<div class='meta'>{n_overweight} overweight (&gt;{DEFAULT_WEIGHTS.overweight_pct:.0f}%)</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def _attention_rows(rows: list[CardRow]) -> list[CardRow]:
    """Holdings that warrant a second look right now."""
    out: list[CardRow] = []
    seen: set[tuple] = set()
    # 1) Strong Sell / Sell first
    for r in rows:
        if r.card.get("error"):
            continue
        if r.card.get("score_label") in ("Strong Sell", "Sell"):
            key = (r.card["symbol"], r.card["market_code"])
            if key not in seen:
                seen.add(key); out.append(r)
    # 2) Overweight that aren't already in
    for r in rows:
        if r.card.get("error") or not r.overweight:
            continue
        key = (r.card["symbol"], r.card["market_code"])
        if key not in seen:
            seen.add(key); out.append(r)
    return out[:6]  # cap so the section doesn't dominate the page


# ---------------- Top bar ----------------

def _render_topbar(loaded_at: Optional[str], on_refresh_key: str) -> None:
    cols = st.columns([5, 2, 1])
    with cols[0]:
        st.markdown(
            "<div class='topbar'>"
            "<div>"
            "<div class='app-title'>📊 Portfolio Intelligence</div>"
            "<div class='app-subtitle'>facts → signals → grounded synthesis · not advice</div>"
            "</div></div>",
            unsafe_allow_html=True,
        )
    with cols[1]:
        if loaded_at:
            st.caption(f"data loaded · {loaded_at}")
    with cols[2]:
        if st.button("🔄 Refresh", key=on_refresh_key, use_container_width=True,
                     help="Re-fetch quotes & recompute. Filters apply instantly without this."):
            _quick_card.clear()
            st.session_state.pop("rows_cache", None)
            st.rerun()


# ---------------- Sidebar (settings only) ----------------

with st.sidebar:
    st.markdown("### ⚙ Settings")
    db_path = st.text_input("Database", value="portfolio.db")
    period = st.selectbox("History window", ["6mo", "1y", "2y", "5y"], index=1)
    out_dir = Path(st.text_input("Digest output dir", value="digests"))
    model = st.text_input("Ollama model", value=DEFAULT_MODEL)
    st.divider()
    st.caption(
        "Filters & sort live in the **Dashboard** toolbar.\n\n"
        "The sidebar is collapsed by default — toggle the « icon to hide it."
    )


store = _store(db_path)


# ---------------- Tabs ----------------

tab_dash, tab_lookup, tab_portfolio = st.tabs(["📈 Dashboard", "🔍 Lookup", "💼 Portfolio"])


# ====================== Dashboard ======================

with tab_dash:
    items = items_from_portfolio(store)

    # Build rows ONCE per (portfolio, period). Cached two layers deep:
    #   - st.session_state (fast, in-memory, lost on page reload / restart)
    #   - .rows_cache.pkl on disk (survives reload + restart)
    # The page never blocks on a stale cache; it shows what it has and
    # surfaces a "stale" banner if the disk cache is older than the TTL.
    loaded_at: Optional[str] = None
    stale_age_s: Optional[float] = None
    rows: list[CardRow] = []
    if items:
        fingerprint = (
            db_path, period,
            tuple(sorted((it.symbol, it.market.code) for it in items)),
        )
        cached = st.session_state.get("rows_cache")
        if not cached or cached.get("fp") != fingerprint:
            disk = _load_rows_disk()
            if disk and disk.get("fp") == fingerprint:
                cached = disk
                st.session_state["rows_cache"] = disk

        if cached and cached.get("fp") == fingerprint:
            rows = cached["rows"]
            loaded_at = cached.get("loaded_at", "")
            saved_ts = cached.get("saved_ts", 0.0)
            if saved_ts:
                stale_age_s = time.time() - saved_ts
        else:
            with st.spinner(f"loading {len(items)} holding(s) for the first time..."):
                rows = _build_rows(items, period)
            payload = {
                "fp": fingerprint,
                "rows": rows,
                "loaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "saved_ts": time.time(),
            }
            st.session_state["rows_cache"] = payload
            _save_rows_disk(payload)
            loaded_at = payload["loaded_at"]
            stale_age_s = 0.0

    _render_topbar(loaded_at, on_refresh_key="refresh_dash")

    if not items:
        st.markdown(
            "<div class='empty'>"
            "<div class='big'>No holdings yet</div>"
            "Use the <strong>💼 Portfolio</strong> tab to import a CSV or add holdings manually, "
            "or jump to <strong>🔍 Lookup</strong> to analyse any ticker."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        _render_kpis(rows)

        # Attention spotlight
        attn = _attention_rows(rows)
        if attn:
            st.markdown(
                "<div class='section-h'><div class='title'>🚨 Needs attention</div>"
                f"<div class='sub'>{len(attn)} holding(s) — sells &amp; overweight first</div></div>",
                unsafe_allow_html=True,
            )
            for row_start in range(0, len(attn), 3):
                cols = st.columns(3, gap="small")
                for col, row in zip(cols, attn[row_start:row_start + 3]):
                    with col:
                        _render_card(row, out_dir, model, attention=True, scope="attn")

        # Toolbar: filters live ABOVE the grid (not in sidebar)
        st.markdown(
            "<div class='section-h'><div class='title'>📋 All holdings</div>"
            "<div class='sub'>filters apply instantly · no refetch</div></div>",
            unsafe_allow_html=True,
        )

        tb = st.columns([1.4, 1, 1, 1.2, 1.4, 1])
        with tb[0]:
            search = st.text_input("Search", value="",
                                   placeholder="ticker…",
                                   label_visibility="collapsed").strip().upper()
        with tb[1]:
            sig_filter = st.multiselect("Signal", SIGNAL_ORDER, default=[],
                                        placeholder="Signal",
                                        label_visibility="collapsed")
        with tb[2]:
            mkt_filter = st.multiselect("Market", ["US", "NSE", "BSE"], default=[],
                                        placeholder="Market",
                                        label_visibility="collapsed")
        with tb[3]:
            pos_filter = st.selectbox(
                "Position",
                ["All positions", "Overweight only", "Winners (P&L > 0)", "Losers (P&L < 0)"],
                index=0,
                label_visibility="collapsed",
            )
        with tb[4]:
            sort_by = st.selectbox(
                "Sort",
                ["Signal (Sell first)", "Signal (Buy first)", "Ticker",
                 "Weight (largest first)", "P&L % (worst first)", "P&L % (best first)"],
                index=0,
                label_visibility="collapsed",
            )
        with tb[5]:
            run_full = st.button(
                "🤖 LLM batch",
                help="Run the full LLM digest pipeline. Slow on CPU.",
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
            st.session_state.pop("rows_cache", None)
            st.rerun()

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
            st.markdown(
                "<div class='empty'><div class='big'>No holdings match the filters</div>"
                "Clear a filter to see more.</div>",
                unsafe_allow_html=True,
            )
        else:
            for row_start in range(0, len(filtered), 3):
                cols = st.columns(3, gap="small")
                for col, row in zip(cols, filtered[row_start:row_start + 3]):
                    with col:
                        _render_card(row, out_dir, model)


# ====================== Lookup ======================

with tab_lookup:
    _render_topbar(None, on_refresh_key="refresh_lookup")
    st.markdown(
        "<div class='section-h'><div class='title'>🔍 Look up any ticker</div>"
        "<div class='sub'>same pipeline as your portfolio · works for any US/NSE/BSE ticker</div></div>",
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns([3, 1.2, 1.2, 1])
    with col1:
        raw_ticker = st.text_input("Ticker", value="AAPL",
                                   help="Bare symbol (AAPL) or qualified (RELIANCE.NS).",
                                   label_visibility="collapsed", placeholder="ticker e.g. AAPL or RELIANCE.NS")
    with col2:
        market_flag = st.selectbox("Market", ["(auto)", "US", "NSE", "BSE"], index=0,
                                   label_visibility="collapsed")
    with col3:
        run_llm_lookup = st.checkbox("LLM synthesis", value=False,
                                     help="Slow on CPU. Off = signals + setup only.")
    with col4:
        do_lookup = st.button("Analyse", type="primary", use_container_width=True)

    if do_lookup:
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
    _render_topbar(None, on_refresh_key="refresh_portfolio")

    # Import first — most-used action.
    st.markdown(
        "<div class='section-h'><div class='title'>📥 Import CSV</div>"
        "<div class='sub'>ICICI Direct PortFolioEqtSummary or canonical format</div></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Auto-detects ICICI Direct's PortFolioEqtSummary export (resolves NSE tickers from ISIN) "
        "or the canonical `ticker, market, shares, cost_basis, date` format. "
        "See `examples/portfolio.example.csv`."
    )
    up = st.file_uploader("Drop a CSV here", type=["csv"], label_visibility="collapsed")
    icols = st.columns([1, 1, 3])
    with icols[0]:
        replace = st.checkbox("Replace existing holdings", value=False)
    with icols[1]:
        do_import = st.button("Import", type="primary", disabled=(up is None),
                              use_container_width=True)
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
            st.dataframe(rows_err, use_container_width=True, hide_index=True)
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
            st.session_state.pop("rows_cache", None)
            st.rerun()

    # Holdings table.
    st.markdown(
        "<div class='section-h'><div class='title'>📋 Current holdings</div>"
        "<div class='sub'>edit or remove below</div></div>",
        unsafe_allow_html=True,
    )
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
            rm_cols = st.columns([3, 1])
            with rm_cols[0]:
                rm_choice = st.selectbox(
                    "Pick one",
                    [f"{h.ticker}.{h.market_code}" for h in holdings],
                    key="rm_choice",
                    label_visibility="collapsed",
                )
            with rm_cols[1]:
                if st.button("Remove", type="secondary", use_container_width=True):
                    sym, mkt = rm_choice.rsplit(".", 1)
                    store.remove(sym, mkt)
                    _quick_card.clear()
                    st.session_state.pop("rows_cache", None)
                    st.success(f"Removed {rm_choice}.")
                    st.rerun()
    else:
        st.markdown(
            "<div class='empty'><div class='big'>No holdings yet</div>"
            "Import a CSV above or add one manually below.</div>",
            unsafe_allow_html=True,
        )

    # Manual add.
    st.markdown(
        "<div class='section-h'><div class='title'>➕ Add a holding manually</div></div>",
        unsafe_allow_html=True,
    )
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
            st.session_state.pop("rows_cache", None)
            st.rerun()
