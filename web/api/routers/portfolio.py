"""Portfolio CRUD: list/add/remove holdings + CSV import."""
from __future__ import annotations

from datetime import date as date_
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from portfolio_intel.markets import Market, parse_ticker
from portfolio_intel.portfolio.csv_import import import_csv_file
from portfolio_intel.portfolio.models import Holding

from ..schemas import HoldingIn, HoldingOut, ImportErrorRow, ImportResultOut
from ..serializers import holding_to_out
from ..state import DB_PATH, get_store, invalidate_dashboard

router = APIRouter()


@router.get("", response_model=list[HoldingOut])
def list_holdings() -> list[HoldingOut]:
    store = get_store()
    return [holding_to_out(h) for h in store.all()]


@router.post("", response_model=HoldingOut)
def add_holding(body: HoldingIn) -> HoldingOut:
    market = Market.from_code(body.market)
    symbol, market = parse_ticker(body.ticker, default_market=market)
    h = Holding(
        ticker=symbol, market_code=market.code, shares=float(body.shares),
        cost_basis=float(body.cost_basis), currency=market.currency,
        date_added=body.date_added or date_.today(),
    )
    get_store().upsert(h)
    invalidate_dashboard()
    return holding_to_out(h)


@router.delete("/{symbol}/{market}", status_code=204)
def remove_holding(symbol: str, market: str) -> Response:
    ok = get_store().remove(symbol.upper(), market.upper())
    if not ok:
        raise HTTPException(status_code=404, detail="holding not found")
    invalidate_dashboard()
    return Response(status_code=204)


@router.post("/import", response_model=ImportResultOut)
async def import_csv(
    file: UploadFile = File(...),
    replace: bool = Form(False),
) -> ImportResultOut:
    contents = await file.read()
    with NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        result = import_csv_file(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    store = get_store()
    if result.holdings:
        if replace:
            for h in store.all():
                store.remove(h.ticker, h.market_code)
        for h in result.holdings:
            store.upsert(h)
        invalidate_dashboard()

    return ImportResultOut(
        imported=len(result.holdings),
        errors=[
            ImportErrorRow(
                reason=err.reason,
                isin=err.raw.get("isin") if isinstance(err.raw, dict) else None,
                name=err.raw.get("name") if isinstance(err.raw, dict) else None,
                broker_symbol=err.raw.get("broker_symbol") if isinstance(err.raw, dict) else None,
            )
            for err in result.errors
        ],
    )
