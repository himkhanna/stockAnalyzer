"""Alerts: persistent threshold rules + fired-event feed.

Rules are evaluated on every dashboard refresh (see state._evaluate_alerts).
Each fire creates an alert_event row; the Insights page surfaces unack'd
events at the top. No prediction here — alerts only fire on conditions
the user explicitly defined.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from portfolio_intel.markets import Market

from ..schemas import AlertEventOut, AlertIn, AlertOut
from ..state import get_store

router = APIRouter()


_ALLOWED_KINDS = {
    "price_above", "price_below",
    "rsi_above", "rsi_below",
    "score_at_or_above", "score_at_or_below",
    "score_flip_buy", "score_flip_sell",
    "pct_drop_day", "pct_rise_day",
}


def _row_to_alert(d: dict) -> AlertOut:
    return AlertOut(
        id=int(d["id"]),
        ticker=d["ticker"],
        market=d["market"],
        kind=d["kind"],
        threshold=float(d["threshold"]),
        note=d.get("note"),
        active=bool(d["active"]),
        created_at=d["created_at"],
        last_fired_at=d.get("last_fired_at"),
    )


def _row_to_event(d: dict) -> AlertEventOut:
    return AlertEventOut(
        id=int(d["id"]),
        alert_id=int(d["alert_id"]),
        ticker=d["ticker"],
        market=d["market"],
        kind=d["kind"],
        threshold=float(d["threshold"]),
        fired_at=d["fired_at"],
        triggered_value=(
            float(d["triggered_value"])
            if d.get("triggered_value") is not None
            else None
        ),
        message=d.get("message"),
        acknowledged=bool(d["acknowledged"]),
    )


@router.get("", response_model=list[AlertOut])
def list_alerts(active_only: bool = False) -> list[AlertOut]:
    return [_row_to_alert(r) for r in get_store().alerts_list(active_only=active_only)]


@router.post("", response_model=AlertOut)
def add_alert(payload: AlertIn) -> AlertOut:
    if payload.kind not in _ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown kind: {payload.kind}")
    try:
        Market.from_code(payload.market)
    except Exception:
        raise HTTPException(status_code=400, detail=f"unknown market: {payload.market}")
    if not payload.ticker.strip():
        raise HTTPException(status_code=400, detail="ticker required")

    store = get_store()
    alert_id = store.alert_add(
        payload.ticker.strip(),
        payload.market,
        payload.kind,
        payload.threshold,
        payload.note or "",
    )
    for d in store.alerts_list():
        if int(d["id"]) == alert_id:
            return _row_to_alert(d)
    raise HTTPException(status_code=500, detail="failed to read back inserted alert")


@router.delete("/{alert_id}", status_code=204)
def remove_alert(alert_id: int) -> None:
    if not get_store().alert_remove(alert_id):
        raise HTTPException(status_code=404, detail="alert not found")


@router.patch("/{alert_id}/active", response_model=AlertOut)
def toggle_alert(alert_id: int, active: bool) -> AlertOut:
    store = get_store()
    if not store.alert_set_active(alert_id, active):
        raise HTTPException(status_code=404, detail="alert not found")
    for d in store.alerts_list():
        if int(d["id"]) == alert_id:
            return _row_to_alert(d)
    raise HTTPException(status_code=500, detail="failed to read back updated alert")


@router.get("/events", response_model=list[AlertEventOut])
def list_events(unacknowledged_only: bool = False, limit: int = 50) -> list[AlertEventOut]:
    return [
        _row_to_event(r)
        for r in get_store().alert_events_list(
            unacknowledged_only=unacknowledged_only,
            limit=limit,
        )
    ]


@router.post("/events/{event_id}/ack", status_code=204)
def ack_event(event_id: int) -> None:
    if not get_store().alert_event_ack(event_id):
        raise HTTPException(status_code=404, detail="event not found")


@router.post("/events/ack_all", status_code=204)
def ack_all_events() -> None:
    get_store().alert_event_ack_all()
