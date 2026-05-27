"""GET /api/holdings → DashboardOut (rows + KPIs).

Always returns from cache when fresh; pass ?refresh=true to force a refetch.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Query

from ..schemas import DashboardOut
from ..serializers import rows_to_dashboard
from ..state import get_dashboard, invalidate_dashboard

router = APIRouter()
_DIGEST_DIR = Path(os.environ.get("DIGEST_DIR", "digests"))


@router.get("", response_model=DashboardOut)
def get_holdings(refresh: bool = Query(False)) -> DashboardOut:
    payload = get_dashboard(force=refresh)
    return rows_to_dashboard(
        payload["rows"],
        loaded_at=payload["loaded_at"],
        digest_dir=_DIGEST_DIR,
    )


@router.post("/refresh", response_model=DashboardOut)
def refresh_holdings() -> DashboardOut:
    invalidate_dashboard()
    payload = get_dashboard(force=True)
    return rows_to_dashboard(
        payload["rows"],
        loaded_at=payload["loaded_at"],
        digest_dir=_DIGEST_DIR,
    )
