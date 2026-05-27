import type {
  Alert,
  AlertEvent,
  AlertIn,
  Backtest,
  BrokerStatus,
  CardRow,
  Dashboard,
  DigestPayload,
  Holding,
  HoldingIn,
  ImportResult,
  Insights,
  ChainStats,
  CoveredCalls,
  Discovery,
  DiversificationReport,
  IVSnapshot,
  Performance,
  TaxHarvest,
  LiveQuotes,
  Lookup,
  OptionChain,
  OptionExpiries,
  OptionExpiriesProbe,
  PayoffIn,
  PayoffOut,
  SearchOut,
  SyncApplyResult,
  SyncPreview,
  WatchlistItem,
  WatchlistItemIn,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  kind: "unreachable" | "non_json" | "http";
  constructor(message: string, status: number, kind: ApiError["kind"]) {
    super(message);
    this.status = status;
    this.kind = kind;
  }
}

function looksLikeJson(ct: string | null, body: string): boolean {
  if (ct && ct.includes("application/json")) return true;
  const trimmed = body.trimStart();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      ...init,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(
      "Backend unreachable on :8765. Start it with:\nuvicorn web.api.main:app --reload --port 8765",
      0,
      "unreachable",
    );
  }

  if (res.status === 204) return undefined as T;

  const ct = res.headers.get("content-type");
  const text = await res.text();

  if (!res.ok) {
    // Vite proxy returns 5xx (often with no/HTML body) when uvicorn isn't running.
    if (res.status >= 500 && !looksLikeJson(ct, text)) {
      throw new ApiError(
        `Backend unreachable on :8765 (proxy returned ${res.status}). Start it with:\nuvicorn web.api.main:app --reload --port 8765`,
        res.status,
        "unreachable",
      );
    }
    throw new ApiError(`${res.status}: ${text || res.statusText}`, res.status, "http");
  }

  if (!looksLikeJson(ct, text)) {
    // 200 but HTML — usually the Vite SPA fallback intercepting because the proxy
    // path didn't match, or a stale service worker.
    throw new ApiError(
      "Backend returned a non-JSON response (likely the SPA fallback). Is uvicorn running on :8765? Try:\nuvicorn web.api.main:app --reload --port 8765",
      res.status,
      "non_json",
    );
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError("Backend returned malformed JSON.", res.status, "non_json");
  }
}

export const api = {
  getDashboard: (refresh = false) =>
    request<Dashboard>(`/holdings${refresh ? "?refresh=true" : ""}`),
  refreshDashboard: () =>
    request<Dashboard>(`/holdings/refresh`, { method: "POST" }),

  listHoldings: () => request<Holding[]>("/portfolio"),
  addHolding: (h: HoldingIn) =>
    request<Holding>("/portfolio", {
      method: "POST",
      body: JSON.stringify(h),
    }),
  removeHolding: (symbol: string, market: string) =>
    request<void>(`/portfolio/${encodeURIComponent(symbol)}/${encodeURIComponent(market)}`, {
      method: "DELETE",
    }),
  importCsv: async (file: File, replace: boolean): Promise<ImportResult> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("replace", String(replace));
    const res = await fetch(`${BASE}/portfolio/import`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status}: ${detail}`);
    }
    return (await res.json()) as ImportResult;
  },

  lookup: (
    ticker: string,
    opts: { market?: string; run_llm?: boolean; period?: string } = {},
  ) => {
    const params = new URLSearchParams();
    if (opts.market) params.set("market", opts.market);
    if (opts.run_llm) params.set("run_llm", "true");
    if (opts.period) params.set("period", opts.period);
    const qs = params.toString();
    return request<Lookup>(
      `/lookup/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ""}`,
    );
  },

  getInsights: () => request<Insights>("/insights"),

  diversification: () => request<DiversificationReport>("/insights/diversification"),

  taxHarvest: () => request<TaxHarvest>("/insights/tax-harvest"),

  performance: (period: string) =>
    request<Performance>(`/insights/performance?period=${encodeURIComponent(period)}`),

  discover: (opts: { markets?: string[]; refresh?: boolean; minScore?: number; limitPerMarket?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.markets?.length) params.set("markets", opts.markets.join(","));
    if (opts.refresh) params.set("refresh", "true");
    if (opts.minScore != null) params.set("min_score", String(opts.minScore));
    if (opts.limitPerMarket != null) params.set("limit_per_market", String(opts.limitPerMarket));
    const qs = params.toString();
    return request<Discovery>(`/insights/discover${qs ? `?${qs}` : ""}`);
  },

  liveQuotes: () => request<LiveQuotes>("/quotes/live"),

  runBacktest: (symbol: string, market: string) =>
    request<Backtest>(
      `/backtest/${encodeURIComponent(symbol)}/${encodeURIComponent(market)}`,
      { method: "POST" },
    ),

  listAlerts: () => request<Alert[]>("/alerts"),
  addAlert: (a: AlertIn) =>
    request<Alert>("/alerts", { method: "POST", body: JSON.stringify(a) }),
  removeAlert: (id: number) =>
    request<void>(`/alerts/${id}`, { method: "DELETE" }),
  toggleAlert: (id: number, active: boolean) =>
    request<Alert>(
      `/alerts/${id}/active?active=${active ? "true" : "false"}`,
      { method: "PATCH" },
    ),
  listAlertEvents: (unacknowledgedOnly = false) =>
    request<AlertEvent[]>(
      `/alerts/events${unacknowledgedOnly ? "?unacknowledged_only=true" : ""}`,
    ),
  ackAlertEvent: (id: number) =>
    request<void>(`/alerts/events/${id}/ack`, { method: "POST" }),
  ackAllAlertEvents: () =>
    request<void>(`/alerts/events/ack_all`, { method: "POST" }),

  iciciStatus: () => request<BrokerStatus>("/brokers/icici/status"),
  iciciSetCredentials: (api_key: string, api_secret: string) =>
    request<BrokerStatus>("/brokers/icici/credentials", {
      method: "POST",
      body: JSON.stringify({ api_key, api_secret }),
    }),
  iciciSetSession: (session_token: string) =>
    request<BrokerStatus>("/brokers/icici/session", {
      method: "POST",
      body: JSON.stringify({ session_token }),
    }),
  iciciDisconnect: () =>
    request<void>("/brokers/icici/disconnect", { method: "POST" }),
  iciciSyncPreview: () =>
    request<SyncPreview>("/brokers/icici/sync/preview", { method: "POST" }),
  optionExpiries: () => request<OptionExpiries>("/options/expiries"),
  optionExpiriesProbe: (symbol: string, brokerCode?: string, refresh = false) => {
    const params = new URLSearchParams({ symbol });
    if (brokerCode) params.set("broker_code", brokerCode);
    if (refresh) params.set("refresh", "true");
    return request<OptionExpiriesProbe>(
      `/options/expiries/probe?${params.toString()}`,
    );
  },
  optionChain: (symbol: string, expiry: string, brokerCode?: string) => {
    const params = new URLSearchParams({ symbol, expiry });
    if (brokerCode) params.set("broker_code", brokerCode);
    return request<OptionChain>(`/options/chain?${params.toString()}`);
  },
  optionIVSnapshot: (symbol: string, expiry: string, brokerCode?: string) => {
    const params = new URLSearchParams({ symbol, expiry });
    if (brokerCode) params.set("broker_code", brokerCode);
    return request<IVSnapshot>(`/options/iv-snapshot?${params.toString()}`);
  },
  optionCoveredCalls: (symbol: string, expiry: string, brokerCode?: string) => {
    const params = new URLSearchParams({ symbol, expiry });
    if (brokerCode) params.set("broker_code", brokerCode);
    return request<CoveredCalls>(`/options/covered-calls?${params.toString()}`);
  },
  optionChainStats: (symbol: string, expiry: string, brokerCode?: string) => {
    const params = new URLSearchParams({ symbol, expiry });
    if (brokerCode) params.set("broker_code", brokerCode);
    return request<ChainStats>(`/options/chain-stats?${params.toString()}`);
  },
  optionPayoff: (body: PayoffIn) =>
    request<PayoffOut>("/options/payoff", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  iciciSyncApply: (replaceIndia = false) =>
    request<SyncApplyResult>(
      `/brokers/icici/sync/apply?replace_india=${replaceIndia ? "true" : "false"}`,
      { method: "POST" },
    ),

  listWatchlist: () => request<WatchlistItem[]>("/watchlist"),
  addWatchlist: (item: WatchlistItemIn) =>
    request<WatchlistItem>("/watchlist", {
      method: "POST",
      body: JSON.stringify(item),
    }),
  removeWatchlist: (symbol: string, market: string) =>
    request<void>(
      `/watchlist/${encodeURIComponent(symbol)}/${encodeURIComponent(market)}`,
      { method: "DELETE" },
    ),

  search: (q: string, limit = 10, signal?: AbortSignal) =>
    request<SearchOut>(
      `/search?q=${encodeURIComponent(q)}&limit=${limit}`,
      { signal },
    ),

  getDigest: (symbol: string, market: string) =>
    request<DigestPayload>(
      `/digest/${encodeURIComponent(symbol)}/${encodeURIComponent(market)}`,
    ),
  generateDigest: (symbol: string, market: string) =>
    request<DigestPayload>(
      `/digest/${encodeURIComponent(symbol)}/${encodeURIComponent(market)}/generate`,
      { method: "POST" },
    ),
};
