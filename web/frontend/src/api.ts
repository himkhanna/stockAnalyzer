import type {
  CardRow,
  Dashboard,
  DigestPayload,
  Holding,
  HoldingIn,
  ImportResult,
  Lookup,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
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
