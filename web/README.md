# Portfolio Intelligence — Web UI

FastAPI backend + Vite/React/Tailwind frontend. Replaces the Streamlit UI
(which still runs from `src/portfolio_intel/ui/app.py` if you prefer it).

## One-time setup

```powershell
# Backend deps (from project root)
pip install -e ".[web]"

# Frontend deps
cd web/frontend
npm install
cd ../..
```

## Dev — run both processes

Terminal 1 — backend on :8765

```powershell
uvicorn web.api.main:app --reload --port 8765
```

Terminal 2 — frontend dev server on :5173 (proxies /api → :8765)

```powershell
cd web/frontend
npm run dev
```

Open http://localhost:5173

## Prod — single process

```powershell
cd web/frontend
npm run build
cd ../..
uvicorn web.api.main:app --port 8765
```

Then open http://localhost:8765 — the backend serves the built React app.

## Env

- `PORTFOLIO_DB` — sqlite path (default `portfolio.db`)
- `HISTORY_WINDOW` — `6mo` / `1y` / `2y` / `5y` (default `1y`)
- `DIGEST_DIR` — where daily markdown digests live (default `digests`)
- `OLLAMA_MODEL` — model name (default per `llm/ollama.py`)
- `FINNHUB_API_KEY` — optional US news source

All read at process start. Restart the backend after changing them.
