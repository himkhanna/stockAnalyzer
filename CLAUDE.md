# CLAUDE.md — Portfolio Intelligence App

## What we're building

A **personal stock analysis tool** that combines real market data, deterministic technical analysis, and a locally-run LLM (via Ollama) to produce a grounded analysis with directional — but honest — signals.

It works two ways:
1. **Portfolio mode** — analyze the user's own holdings (with position-aware logic).
2. **Lookup mode** — enter *any* ticker (not in the portfolio) and get the full analysis on demand. The same technical + news + synthesis pipeline runs; position-aware logic simply skips when there's no holding.

It supports **multiple markets — US and India (NSE/BSE) from the start — and must be architected so additional markets can be added with minimal friction.**

This is a **personal, non-commercial tool** for a single user. It is **not** a trading bot, not a financial advisor, and must never present itself as one.

---

## Core design philosophy (READ THIS FIRST — it governs every decision)

**APIs provide facts. Math provides signals. The LLM provides judgment. Never blur these.**

1. **The LLM never invents data.** Prices, financials, and news come from APIs. Technical indicators are computed with math libraries. The LLM only reasons over data it is given — it never produces a number (price, RSI, target) on its own.
2. **Directionality comes from the math layer, not the LLM's tone.** Clear buy/sell/hold signals come from a deterministic scoring engine, not from prompting the model to "sound confident."
3. **Every directional claim must be backed by a backtest.** If the app shows a buy/sell signal, it must also be able to show how that signal performed historically. No confidence percentages or price targets that aren't derived from real, backtested data or real resistance/support levels.
4. **Honesty over decisiveness.** The synthesis must stay measured ("a pullback would not be unusual," "main risk to watch") and never promise direction. False precision is the primary failure mode to avoid.
5. **The user decides.** Output is decision *support*, ending in "Not advice — your call."

If a feature would make the app *sound* more confident without being more *correct*, do not build it.

---

## Multi-market & on-demand lookup (core requirements)

**Markets:** Support US and India (NSE/BSE) from day one; architect for easy addition of others later.

- **Market abstraction:** Define a `Market` concept (e.g. `US`, `NSE`, `BSE`) that encapsulates everything market-specific. Adding a market should mean adding one config/class, not editing logic across the codebase.
- **Ticker formatting:** Handle per-market symbol conventions transparently. yfinance uses `.NS` for NSE (`RELIANCE.NS`), `.BO` for BSE (`RELIANCE.BO`), and plain symbols for US (`AAPL`). The user should be able to enter a natural ticker + market, or a fully-qualified symbol; the app normalizes it.
- **Currency:** Display in the market's native currency (₹ for India, $ for US). Store cost basis in the currency it was bought in. Do NOT silently convert or mix currencies in one total without labeling.
- **Trading hours & holidays:** Be aware that markets have different sessions and holiday calendars; "current price" may be a last-close when a market is shut. Label data freshness.
- **News:** News availability differs by market and provider. Degrade gracefully — if no news source covers a given market/ticker, run the analysis on technicals alone and say so, rather than failing.

**On-demand lookup:** The full analysis pipeline (data → technicals → news → scoring → synthesis) must run on **any** ticker the user enters, whether or not it's in their portfolio.

- Lookup mode and portfolio mode share the exact same analysis code. The only difference: position-aware logic (overweight flags, gain/loss vs cost basis, rebalancing) is **skipped or shown as N/A** when there's no holding.
- The user can optionally "add to portfolio" from a lookup result.

---

## Tech stack

- **Language:** Python 3.11+
- **LLM:** Ollama running locally (CPU-acceptable). Default model: `llama3.1:8b` or `qwen2.5:7b`. Make the model name a config variable.
- **Market data + news:** Use **yfinance** (Yahoo Finance) as the **primary** source — it covers both US and Indian (NSE/BSE) tickers, plus most global exchanges, through one free library. This directly supports the multi-market and "add more markets later" goals. **Finnhub (free tier)** is an *optional secondary* source for richer US news. **Important:** Finnhub's free tier does NOT reliably cover Indian markets — do not rely on it for India. Abstract ALL data access behind a common `DataSource` interface so providers can be swapped or added per market.
  - *Note: yfinance is an unofficial library and can occasionally break with Yahoo changes. Isolate it behind the interface so it can be replaced (e.g. with broker APIs like Zerodha Kite / Upstox for India) without touching the rest of the app.*
- **Technical analysis:** `pandas-ta` (preferred for ease) or `TA-Lib` (for candlestick pattern detection). Use pandas DataFrames as the common data structure.
- **Storage:** SQLite (holdings, cached data, signal history).
- **Backtesting:** `vectorbt` or `backtesting.py`.
- **UI:** Start with terminal/CLI output. A simple local web UI (FastAPI + a single HTML page, or Streamlit) is a later, optional layer. Do not start with the UI.

Keep dependencies minimal. Prefer well-maintained libraries.

---

## Architecture (layered — respect the separation)

```
┌─────────────────────────────────────────────┐
│  Data Layer        → yfinance (US+India) +   │  facts
│                      optional Finnhub news    │
├─────────────────────────────────────────────┤
│  Portfolio Store   → SQLite: holdings        │  state
├─────────────────────────────────────────────┤
│  Technical Layer   → pandas-ta/TA-Lib        │  signals (math)
├─────────────────────────────────────────────┤
│  Scoring Engine    → weighted composite      │  directionality
├─────────────────────────────────────────────┤
│  LLM Layer         → Ollama synthesis        │  judgment
├─────────────────────────────────────────────┤
│  Backtest Layer    → vectorbt                │  the honesty check
├─────────────────────────────────────────────┤
│  Presentation      → CLI, then optional web  │  output
└─────────────────────────────────────────────┘
```

Each layer should be its own module with a clean interface. The technical layer must not call the data API directly — it receives a DataFrame. The LLM layer must not compute indicators — it receives computed values. Enforce this separation.

---

## Build phases (BUILD STRICTLY IN ORDER — do not skip ahead)

The biggest risk is rushing to the exciting scoring/backtest layers before the foundation is solid. **Phases 1–3 deliver ~80% of the value.** Build them first, make them excellent, then proceed.

### Phase 1 — Data + display (foundation)
- [ ] Define the `DataSource` interface and the `Market` abstraction (US, NSE, BSE) up front — everything else depends on this.
- [ ] yfinance client implementing `DataSource`: fetch current quote + historical daily prices for any ticker across US and Indian markets. Normalize ticker formatting per market (`.NS`, `.BO`, plain). Handle errors gracefully.
- [ ] SQLite portfolio store: `ticker, market, shares, cost_basis, currency, date_added`. CRUD functions.
- [ ] **Lookup mode:** a code path that fetches + displays data for *any* entered ticker, independent of the portfolio.
- [ ] CLI display: (a) list portfolio holdings with current price and gain/loss vs cost basis in native currency; (b) look up an arbitrary ticker.
- **Done when:** the app shows a working portfolio tracker AND can pull live data for any US or Indian ticker on demand. No AI yet.

### Phase 2 — Technical layer
- [ ] Feed price history into pandas-ta/TA-Lib. Compute: RSI(14), MACD, SMA/EMA (50 & 200), Bollinger Bands, ATR, volume signals.
- [ ] Compute support/resistance from local highs/lows.
- [ ] Detect candlestick patterns (TA-Lib) — engulfing, doji, hammer.
- [ ] Display these as a per-stock signal table.
- **Done when:** each stock shows a table of real, reproducible technical readings.

### Phase 3 — News + Ollama synthesis
- [ ] Fetch recent news per ticker. yfinance provides some news; Finnhub can supplement for US. **News coverage varies by market** — if a ticker/market has no news source, run on technicals alone and state that clearly rather than failing.
- [ ] Simple sentiment tally (positive/neutral/negative counts + themes).
- [ ] Ollama integration: construct a prompt with news + computed technicals, get a plain-English synthesis. (See prompt spec below.)
- [ ] Combine into a per-stock "digest card."
- **Done when:** the app produces a grounded daily digest. **This is a genuinely useful product — pause here and use it for a few weeks before building Phase 4.**

### Phase 4 — Directional layer
- [ ] Composite scoring: weight indicators + sentiment into a −10..+10 score → Strong Sell / Sell / Hold / Buy / Strong Buy. Weights must be config-driven and easily adjustable.
- [ ] Rules engine: explicit threshold triggers (e.g. `RSI < 30 AND price near support → buy signal`; `death cross → reduce`).
- [ ] Trade setup generator: entry / stop (nearest support) / target (nearest resistance) / risk-reward ratio. Targets come from real levels, NEVER from the LLM.
- [ ] Position-aware logic: flag overweight positions, suggest rebalancing. (This is sound directional logic independent of prediction — prioritize it.)
- **Done when:** the digest card shows a single clear signal + concrete trade setup.

### Phase 5 — Backtesting (do this slowly and correctly)
- [ ] Run the scoring rules against historical data with vectorbt/backtesting.py.
- [ ] Report: signal-following return vs buy-and-hold, win rate, max drawdown.
- [ ] Display a backtest line on each card so the user knows how much to trust the signal.
- **CRITICAL — avoid lookahead bias.** The backtest must only use information available at each point in time. Account for transaction costs. Do NOT overfit the scoring weights to historical data. A rule that "matched buy-and-hold" is an honest and common result — report it truthfully, do not tune until it looks good.
- **Done when:** every directional signal is accompanied by its real historical track record.

### Phase 6 — Optional web UI
- [ ] Only after the above works in CLI. Compact cards (price, RSI/trend traffic-light, one-line synthesis), expandable to full detail. A 15-stock portfolio should be scannable in ~30 seconds.

---

## The Ollama synthesis prompt (Phase 3 — highest-leverage piece)

The system prompt must enforce the honest tone. Core requirements:
- Reason ONLY over the provided technicals and news — never invent numbers.
- Stay measured: describe what the signals mean, flag risks, avoid promising direction.
- Use hedged language for anything forward-looking ("would not be unusual," "worth watching").
- End with a clear but non-committal read and the disclaimer "Not advice — your call."
- Keep it to a short paragraph. No hype words ("skyrocket," "guaranteed," "moonshot").

Pass the computed indicators and news summary as structured context. Iterate on this prompt heavily — it most determines output quality.

---

## Hard constraints (do not violate)

- **No confidence percentages** unless derived from a real backtested base rate.
- **No price targets from the LLM** — only from computed support/resistance.
- **No data invented by the LLM** — ever.
- **Always include the "Not advice" disclaimer** on any output containing a signal.
- **Free-tier friendly** — respect Finnhub rate limits; cache data in SQLite to avoid redundant calls.
- **CPU-runnable** — don't assume a GPU; keep model choice to ~7–8B.

---

## Example target output (the Phase 4 card to aim for)

```
📊 AAPL — Apple Inc. · 50 shares @ $182 · now $211.40 (+16%)

⚖️ SIGNAL: HOLD  (score: +2 / 10)

Technicals:  RSI 68 (caution) · >50&200 MA (uptrend) · MACD rising
             · near upper Bollinger · at $215 resistance
News (7d):   5 articles · 3 pos / 1 neu / 1 neg · theme: services growth
Position:    now 18% of portfolio → overweight, consider trimming
Trade setup: entry $202 / stop $196 / target $225 · RR 2.3:1 (only on a dip)
Backtest:    rule +19.4% vs hold +22.1% · win rate 57% · slightly worse after costs

Synthesis: Strong uptrend and positive news, but overbought and pressing
resistance with poor risk/reward here. Nets to HOLD. The more defensible move
is trimming an overweight position, not adding. Not advice — your call.
```

---

## Coding conventions

- Clear module separation matching the architecture layers.
- Config in one place (model name, API keys via env vars, scoring weights).
- Never commit API keys. Use a `.env` file and `.gitignore` it.
- Type hints and docstrings on public functions.
- Graceful degradation: if news fails, still show technicals; if Ollama is down, still show the data and signals.
- Write the app so a layer can be tested in isolation.

## First task

Start with Phase 1: define the `DataSource` interface and `Market` abstraction (US/NSE/BSE), then implement the yfinance client against it and prove it can pull data for both a US ticker (e.g. `AAPL`) and an Indian one (e.g. `RELIANCE.NS`). Then set up the SQLite portfolio store. Confirm the project structure and these interfaces with me before moving on — they're the foundation everything else builds on.
