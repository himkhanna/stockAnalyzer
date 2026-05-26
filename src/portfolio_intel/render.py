"""Markdown rendering for a Digest.

Single place that turns a Digest into a markdown document. The CLI's
streaming output uses its own inline formatting; this module is used by
batch mode (writing files) and will be reused by the eventual web UI.
"""
from __future__ import annotations

from datetime import datetime

from .digest import Digest
from .portfolio.models import Holding


def _fmt(v, fmt="{:.2f}"):
    return fmt.format(v) if v is not None else "n/a"


def render_digest_md(digest: Digest, *, holding: Holding | None = None, generated_at: datetime | None = None) -> str:
    """Render a Digest as a complete markdown document."""
    m = digest.market
    sym = m.currency_symbol
    snap = digest.snapshot
    q = digest.quote
    s = digest.sentiment
    now = generated_at or datetime.now()

    out: list[str] = []
    out.append(f"# {digest.symbol}.{m.code}")
    out.append("")
    out.append(f"_Generated {now.isoformat(timespec='seconds')} · bars: {snap.bars_used}_")
    out.append("")

    # Signal banner — the headline read.
    out.append(f"## Signal: **{digest.score.label}**  ({digest.score.value:+.1f} / 10)")
    out.append("")
    if digest.score.breakdown:
        parts = [f"{k} {v:+.1f}" for k, v in digest.score.breakdown.items()]
        out.append(f"_Breakdown: {', '.join(parts)}_")
        out.append("")

    # Price
    if q is not None:
        chg = q.change_pct
        chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
        stale = " *[stale: market closed]*" if q.stale else ""
        out.append(f"**Price:** {sym}{q.price:,.2f}{chg_str}{stale}")
        if q.previous_close is not None:
            out.append(f"**Prev close:** {sym}{q.previous_close:,.2f}")
        out.append("")

    # Technicals table
    out.append("## Technicals")
    out.append("")
    out.append("| Indicator | Value | Read |")
    out.append("|---|---|---|")
    out.append(f"| RSI(14) | {_fmt(snap.rsi)} | {snap.rsi_label} |")
    out.append(
        f"| Trend | close {sym}{snap.close:,.2f} vs SMA50 {_fmt(snap.sma_50)} / "
        f"SMA200 {_fmt(snap.sma_200)} | {snap.trend_label} |"
    )
    out.append(
        f"| MACD | {_fmt(snap.macd, '{:.3f}')} / signal {_fmt(snap.macd_signal, '{:.3f}')} / "
        f"hist {_fmt(snap.macd_hist, '{:.3f}')} | {snap.macd_label} |"
    )
    out.append(
        f"| Bollinger | lower {_fmt(snap.bb_lower)} / upper {_fmt(snap.bb_upper)} · "
        f"%B {_fmt(snap.bb_pct_b)} | {snap.bb_label} |"
    )
    out.append(f"| ATR(14) | {_fmt(snap.atr)} ({_fmt(snap.atr_pct)}% of price) | volatility |")
    out.append(f"| Volume | {_fmt(snap.volume_ratio)}x 20-day avg | {snap.volume_label} |")
    sup = f"{sym}{snap.nearest_support:,.2f}" if snap.nearest_support is not None else "none below"
    res = f"{sym}{snap.nearest_resistance:,.2f}" if snap.nearest_resistance is not None else "none above"
    out.append(f"| Support / Resistance | {sup} / {res} | from swing highs/lows |")
    if snap.recent_golden_cross:
        out.append("| | recent golden cross (SMA50 ↑ SMA200) | bullish structure |")
    if snap.recent_death_cross:
        out.append("| | recent death cross (SMA50 ↓ SMA200) | bearish structure |")
    if snap.patterns:
        out.append(f"| Candlestick (last bar) | {', '.join(snap.patterns)} | |")
    out.append("")

    # News
    out.append("## News (last 7 days)")
    out.append("")
    if s.total == 0:
        out.append("_No items found from available sources._")
    else:
        themes = f"  themes: {', '.join(s.themes)}" if s.themes else ""
        out.append(
            f"**{s.total} items** — {s.positive} pos / {s.neutral} neu / "
            f"{s.negative} neg ({s.label}){themes}"
        )
        out.append("")
        for it in digest.news[:5]:
            line = f"- {it.title}"
            if it.publisher:
                line += f" _({it.publisher})_"
            out.append(line)
    out.append("")

    # Rules
    if digest.rules:
        out.append("## Rule triggers")
        out.append("")
        for r in digest.rules:
            out.append(f"- **[{r.direction}]** _{r.name}_ — {r.note}")
        out.append("")

    # Trade setup
    setup = digest.setup
    if setup is not None:
        out.append("## Trade setup")
        out.append("")
        if setup.entry is not None and setup.target is not None and setup.stop is not None:
            verb = "✅ Valid" if setup.valid else "⚠ Reference only (not actionable as-is)"
            rr = f" · **RR {setup.risk_reward:.1f}:1**" if setup.risk_reward else ""
            out.append(
                f"{verb} — entry **{sym}{setup.entry:,.2f}** / "
                f"stop **{sym}{setup.stop:,.2f}** / target **{sym}{setup.target:,.2f}**{rr}"
            )
        out.append("")
        out.append(setup.note)
        out.append("")

    # Position
    if holding is not None and q is not None:
        pos = digest.position
        cost_total = holding.cost_basis * holding.shares
        mv = q.price * holding.shares
        pnl = mv - cost_total
        pct = (pnl / cost_total * 100.0) if cost_total else 0.0
        out.append("## Position")
        out.append("")
        out.append(
            f"- **{holding.shares:g} sh** @ cost {sym}{holding.cost_basis:,.2f} "
            f"(added {holding.date_added.isoformat()})"
        )
        out.append(f"- **Current value:** {sym}{mv:,.2f}")
        out.append(f"- **P&L:** {sym}{pnl:,.2f} ({pct:+.2f}%)")
        if pos is not None and pos.weight_pct is not None:
            tag = " — **overweight**" if pos.overweight else ""
            out.append(f"- **Portfolio weight:** {pos.weight_pct:.1f}%{tag}")
            out.append(f"- _{pos.suggestion}_")
        out.append("")

    # Synthesis
    out.append("## Synthesis")
    out.append("")
    if digest.synthesis:
        out.append(digest.synthesis.strip())
        if digest.model_used:
            out.append("")
            out.append(f"_Model: {digest.model_used}_")
    elif digest.synthesis_error:
        out.append(f"_Synthesis skipped: {digest.synthesis_error}_")
    else:
        out.append("_Synthesis skipped._")
    out.append("")
    return "\n".join(out)
