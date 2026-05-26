"""FastAPI backend for the React frontend.

Thin layer over the existing portfolio_intel modules — does no math itself.
Endpoints map 1:1 to what the UI needs.

Run (dev): uvicorn web.api.main:app --reload --port 8765
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routers import alerts as alerts_router
from .routers import backtest as backtest_router
from .routers import brokers as brokers_router
from .routers import digest as digest_router
from .routers import options as options_router
from .routers import holdings as holdings_router
from .routers import insights as insights_router
from .routers import lookup as lookup_router
from .routers import portfolio as portfolio_router
from .routers import search as search_router
from .routers import watchlist as watchlist_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Portfolio Intelligence API",
    version="0.1.0",
    description="Backend for the React UI. Personal use only.",
    lifespan=lifespan,
)

# Permissive CORS for local dev — Vite runs on 5173, FastAPI on 8765.
# Production serves the built frontend from this same process so CORS isn't needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(holdings_router.router, prefix="/api/holdings", tags=["holdings"])
app.include_router(portfolio_router.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(lookup_router.router, prefix="/api/lookup", tags=["lookup"])
app.include_router(digest_router.router, prefix="/api/digest", tags=["digest"])
app.include_router(search_router.router, prefix="/api/search", tags=["search"])
app.include_router(insights_router.router, prefix="/api/insights", tags=["insights"])
app.include_router(watchlist_router.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(backtest_router.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(alerts_router.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(brokers_router.router, prefix="/api/brokers", tags=["brokers"])
app.include_router(options_router.router, prefix="/api/options", tags=["options"])


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# Serve the built React app if it exists. In dev, Vite handles this on :5173.
_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        target = _FRONTEND_DIST / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(_FRONTEND_DIST / "index.html")
