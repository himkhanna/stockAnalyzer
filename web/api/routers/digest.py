"""Per-ticker full digest — read from disk if cached, else generate on demand."""
from __future__ import annotations

import os
from datetime import date as date_, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from portfolio_intel.data.base import DataSourceError
from portfolio_intel.digest import build_digest
from portfolio_intel.llm.ollama import DEFAULT_MODEL, OllamaError
from portfolio_intel.markets import Market
from portfolio_intel.render import render_digest_md

from ..schemas import DigestOut
from ..state import DEFAULT_PERIOD, get_finnhub, get_source, get_store

router = APIRouter()
DIGEST_DIR = Path(os.environ.get("DIGEST_DIR", "digests"))


def _md_path(symbol: str, market: str) -> Path:
    return DIGEST_DIR / date_.today().isoformat() / f"{symbol}.{market}.md"


@router.get("/{symbol}/{market}", response_model=DigestOut)
def get_digest(symbol: str, market: str) -> DigestOut:
    p = _md_path(symbol.upper(), market.upper())
    if not p.exists():
        raise HTTPException(status_code=404, detail="no digest generated yet for today")
    return DigestOut(
        symbol=symbol.upper(), market=market.upper(),
        markdown=p.read_text(encoding="utf-8"),
        has_synthesis=True,
        generated_at=datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
    )


@router.post("/{symbol}/{market}/generate", response_model=DigestOut)
def generate_digest(
    symbol: str, market: str,
    model: str = Query(DEFAULT_MODEL),
    period: str = Query(DEFAULT_PERIOD),
) -> DigestOut:
    sym = symbol.upper()
    mkt_code = market.upper()
    try:
        mkt = Market.from_code(mkt_code)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown market: {mkt_code}")

    holding = get_store().get(sym, mkt_code)
    try:
        digest = build_digest(
            sym, mkt,
            data_source=get_source(),
            finnhub=get_finnhub(),
            period=period,
            run_llm=True,
            model=model,
            holding=holding,
            run_backtest_too=True,
        )
    except (DataSourceError, ValueError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    except OllamaError as e:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {e}")

    md = render_digest_md(digest, holding=holding)
    p = _md_path(sym, mkt_code)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(md, encoding="utf-8")

    return DigestOut(
        symbol=sym, market=mkt_code, markdown=md,
        has_synthesis=digest.synthesis is not None,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
