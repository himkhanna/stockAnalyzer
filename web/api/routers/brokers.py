"""Broker integration endpoints — read-only.

ICICI Direct (Breeze):
- POST /api/brokers/icici/credentials → save api_key + api_secret
- POST /api/brokers/icici/session     → exchange session token for active session
- GET  /api/brokers/icici/status      → connected? when does session expire?
- POST /api/brokers/icici/sync/preview → fetch holdings + diff vs DB, don't apply
- POST /api/brokers/icici/sync/apply   → upsert holdings into the portfolio
- POST /api/brokers/icici/disconnect   → wipe stored credentials

We never expose api_secret or session_token in any GET response. Status
returns booleans + an expiry timestamp only.
"""
from __future__ import annotations

from datetime import date as date_, datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from portfolio_intel.brokers import (
    BreezeClient,
    BreezeError,
    BreezeNotConnected,
    BreezeNotInstalled,
    BreezeSessionExpired,
    BrokerHolding,
)
from portfolio_intel.brokers.icici_breeze import login_url, next_session_expiry
from portfolio_intel.markets import Market
from portfolio_intel.portfolio.models import Holding
from portfolio_intel.portfolio.ticker_resolver import TickerResolver

from ..state import get_store

router = APIRouter()
_BROKER = "icici_breeze"


class CredentialsIn(BaseModel):
    api_key: str
    api_secret: str


class SessionIn(BaseModel):
    session_token: str


class BrokerStatus(BaseModel):
    broker: str = "icici_breeze"
    has_credentials: bool
    connected: bool
    session_expires_at: Optional[str] = None
    login_url: Optional[str] = None
    note: str = (
        "Read-only integration. We only pull holdings; no orders are ever placed."
    )


class BrokerHoldingPreview(BaseModel):
    broker_stock_code: str
    isin: str
    company_name: Optional[str]
    exchange_code: str
    quantity: float
    average_price: float
    current_price: Optional[float]

    # resolution
    resolved_ticker: Optional[str] = None
    resolved_market: Optional[str] = None
    resolution_source: Optional[str] = None

    # diff
    action: str  # "add" | "update" | "unchanged" | "unresolved"
    existing_shares: Optional[float] = None
    existing_cost_basis: Optional[float] = None


class SyncPreview(BaseModel):
    rows: list[BrokerHoldingPreview]
    add_count: int
    update_count: int
    unchanged_count: int
    unresolved_count: int


class SyncApplyResult(BaseModel):
    upserted: int
    unresolved: int
    removed: int = 0


def _is_session_live(cfg: dict) -> bool:
    if not cfg.get("session_token") or not cfg.get("session_expires_at"):
        return False
    try:
        exp = datetime.fromisoformat(cfg["session_expires_at"])
    except Exception:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > datetime.now(tz=timezone.utc)


@router.get("/icici/status", response_model=BrokerStatus)
def icici_status() -> BrokerStatus:
    cfg = get_store().broker_get(_BROKER)
    if not cfg:
        return BrokerStatus(has_credentials=False, connected=False)
    has_creds = bool(cfg.get("api_key") and cfg.get("api_secret"))
    return BrokerStatus(
        has_credentials=has_creds,
        connected=_is_session_live(cfg),
        session_expires_at=cfg.get("session_expires_at"),
        login_url=login_url(cfg["api_key"]) if has_creds else None,
    )


@router.post("/icici/credentials", response_model=BrokerStatus)
def icici_set_credentials(body: CredentialsIn) -> BrokerStatus:
    if not body.api_key.strip() or not body.api_secret.strip():
        raise HTTPException(status_code=400, detail="api_key and api_secret required")
    get_store().broker_set_credentials(_BROKER, body.api_key.strip(), body.api_secret.strip())
    return icici_status()


@router.post("/icici/session", response_model=BrokerStatus)
def icici_set_session(body: SessionIn) -> BrokerStatus:
    store = get_store()
    cfg = store.broker_get(_BROKER)
    if not cfg or not cfg.get("api_key") or not cfg.get("api_secret"):
        raise HTTPException(status_code=400, detail="Set credentials first.")
    if not body.session_token.strip():
        raise HTTPException(status_code=400, detail="session_token required")

    try:
        client = BreezeClient(cfg["api_key"])
        client.connect(cfg["api_secret"], body.session_token.strip())
    except BreezeNotInstalled as e:
        raise HTTPException(status_code=503, detail=str(e))
    except BreezeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    expires_at = next_session_expiry().isoformat()
    store.broker_set_session(_BROKER, body.session_token.strip(), expires_at)
    return icici_status()


@router.post("/icici/disconnect", status_code=204)
def icici_disconnect() -> None:
    get_store().broker_clear(_BROKER)


@router.post("/icici/sync/preview", response_model=SyncPreview)
def icici_sync_preview() -> SyncPreview:
    holdings = _fetch_holdings()
    return _diff_against_store(holdings)


@router.post("/icici/sync/apply", response_model=SyncApplyResult)
def icici_sync_apply(
    replace_india: bool = Query(
        False,
        description="If true, delete every existing NSE/BSE holding before "
                    "upserting the broker rows. US/UAE holdings are left alone.",
    ),
) -> SyncApplyResult:
    holdings = _fetch_holdings()
    preview = _diff_against_store(holdings)

    store = get_store()
    removed = 0
    if replace_india:
        removed = store.remove_by_markets(("NSE", "BSE"))

    upserted = 0
    for row in preview.rows:
        # In replace mode we re-add everything resolvable, even rows that
        # looked 'unchanged' against the (now-deleted) prior state.
        if not replace_india and row.action in ("unresolved", "unchanged"):
            continue
        if replace_india and row.action == "unresolved":
            continue
        if not row.resolved_ticker or not row.resolved_market:
            continue
        try:
            market = Market.from_code(row.resolved_market)
        except Exception:
            continue
        store.upsert(Holding(
            ticker=row.resolved_ticker,
            market_code=market.code,
            shares=row.quantity,
            cost_basis=row.average_price,
            currency=market.currency,
            date_added=date_.today(),
        ))
        upserted += 1
    return SyncApplyResult(
        upserted=upserted,
        unresolved=preview.unresolved_count,
        removed=removed,
    )


# --- internals ---


def _fetch_holdings() -> list[BrokerHolding]:
    cfg = get_store().broker_get(_BROKER)
    if not cfg or not cfg.get("api_key") or not cfg.get("api_secret"):
        raise HTTPException(status_code=400, detail="ICICI credentials not configured.")
    if not _is_session_live(cfg):
        raise HTTPException(
            status_code=401,
            detail="ICICI session expired or missing. Reconnect via /icici/session.",
        )
    try:
        client = BreezeClient(cfg["api_key"])
        client.connect(cfg["api_secret"], cfg["session_token"])
        return client.get_holdings()
    except BreezeNotInstalled as e:
        raise HTTPException(status_code=503, detail=str(e))
    except BreezeSessionExpired as e:
        raise HTTPException(status_code=401, detail=str(e))
    except (BreezeNotConnected, BreezeError) as e:
        raise HTTPException(status_code=502, detail=str(e))


def _diff_against_store(holdings: list[BrokerHolding]) -> SyncPreview:
    store = get_store()
    resolver = TickerResolver()

    rows: list[BrokerHoldingPreview] = []
    add = update = unchanged = unresolved = 0

    for h in holdings:
        if h.quantity <= 0:
            continue

        # Map ICICI's exchange_code to our market. They use NSE / BSE strings.
        market_code = "NSE" if h.exchange_code.upper().startswith("N") else "BSE"

        resolved_ticker: Optional[str] = None
        source: Optional[str] = None
        # Prefer ISIN → NSE bare ticker via the existing resolver (handles overrides + Yahoo search).
        try:
            res = resolver.resolve(isin=h.isin, name=h.company_name or "", fallback=h.stock_code)
            if res is not None:
                resolved_ticker = res.bare_symbol
                source = res.source
        except Exception:
            resolved_ticker = None

        action = "unresolved"
        existing_shares: Optional[float] = None
        existing_cost: Optional[float] = None
        if resolved_ticker:
            existing = store.get(resolved_ticker, market_code)
            if existing is None:
                action = "add"
                add += 1
            else:
                existing_shares = existing.shares
                existing_cost = existing.cost_basis
                if abs(existing.shares - h.quantity) < 1e-6 and abs(existing.cost_basis - h.average_price) < 1e-3:
                    action = "unchanged"
                    unchanged += 1
                else:
                    action = "update"
                    update += 1
        else:
            unresolved += 1

        rows.append(BrokerHoldingPreview(
            broker_stock_code=h.stock_code,
            isin=h.isin,
            company_name=h.company_name,
            exchange_code=h.exchange_code,
            quantity=h.quantity,
            average_price=h.average_price,
            current_price=h.current_price,
            resolved_ticker=resolved_ticker,
            resolved_market=market_code if resolved_ticker else None,
            resolution_source=source,
            action=action,
            existing_shares=existing_shares,
            existing_cost_basis=existing_cost,
        ))

    return SyncPreview(
        rows=rows,
        add_count=add,
        update_count=update,
        unchanged_count=unchanged,
        unresolved_count=unresolved,
    )
