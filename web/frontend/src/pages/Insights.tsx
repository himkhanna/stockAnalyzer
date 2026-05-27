import { AlertTriangle, Bell, BellOff, CalendarClock, Check, CheckCheck, Compass, Loader2, RefreshCw, Trash2, TrendingDown, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { LastRefreshed } from "../components/LastRefreshed";
import { StockCard } from "../components/StockCard";
import { TickerCombo } from "../components/TickerCombo";
import { fmtCurrency, fmtPct, SIGNAL_STYLES } from "../lib/format";
import type {
  Alert,
  AlertEvent,
  AlertKind,
  ConvictionRow,
  DiscoveryRow,
  EarningsItem,
  IndexSnapshot,
  RiskPanel,
  SignalChange,
  SignalLabel,
  WatchlistItem,
} from "../types";
import { SignalPill } from "../components/SignalPill";

export function InsightsPage() {
  const q = useQuery({ queryKey: ["insights"], queryFn: api.getInsights });

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 text-zinc-500 py-12 justify-center">
        <Loader2 className="animate-spin" size={16} /> Building insights…
      </div>
    );
  }
  if (q.error || !q.data) {
    const msg = (q.error as Error)?.message ?? "no data";
    const [head, ...rest] = msg.split("\n");
    return (
      <EmptyState title="Could not build insights">
        <div>{head}</div>
        {rest.length > 0 && (
          <pre className="mt-2 text-xs bg-zinc-100 dark:bg-zinc-800 rounded px-3 py-2 inline-block text-left whitespace-pre-wrap">
            {rest.join("\n")}
          </pre>
        )}
      </EmptyState>
    );
  }

  const d = q.data;

  return (
    <div className="space-y-8 pb-12">
      <header className="space-y-1">
        <h1 className="text-xl font-bold">Insights</h1>
        <p className="text-xs text-zinc-500 flex items-center gap-2 flex-wrap">
          <LastRefreshed at={d.generated_at} label="generated" />
          <span>· {d.note}</span>
        </p>
      </header>

      <AlertsSection />
      <TaxHarvestSection />
      <DiversificationSection />
      <DiscoverSection />
      <MarketPulse indices={d.indices} />
      <ConvictionBoard rows={d.conviction} />
      <WatchlistSection scanned={d.watchlist} />
      <SignalChangesPanel changes={d.signal_changes} />
      <EarningsPanel items={d.upcoming_earnings} />
      <RiskView risk={d.risk} />
    </div>
  );
}

// --- Tax-loss harvesting ---

function TaxHarvestSection() {
  const q = useQuery({
    queryKey: ["tax-harvest"],
    queryFn: api.taxHarvest,
    staleTime: 60 * 1000,
    retry: false,
  });

  const totalBySym = q.data?.total_saving_by_currency ?? {};
  const totalLine = Object.entries(totalBySym)
    .filter(([, v]) => v > 0)
    .map(([sym, v]) => `${sym}${Math.round(v).toLocaleString()}`)
    .join(" · ");

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h2 className="text-base font-bold flex items-center gap-2">
          <TrendingDown size={16} className="text-bear-500" />
          Tax-loss harvesting
        </h2>
        <div className="text-xs text-zinc-500">
          {totalLine && (
            <span>
              total est. saving:{" "}
              <span className="font-semibold text-bull-600">{totalLine}</span>
            </span>
          )}
        </div>
      </div>

      {q.isLoading ? (
        <div className="card p-4 text-sm text-zinc-500 flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      ) : q.error ? (
        <EmptyState title="Could not compute">{(q.error as Error).message}</EmptyState>
      ) : q.data && q.data.candidates.length === 0 ? (
        <div className="card p-4 text-xs text-zinc-500">
          No holdings are currently in the red beyond the noise threshold. Nothing
          to harvest right now.
        </div>
      ) : q.data ? (
        <div className="card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="text-zinc-500 uppercase tracking-wider text-[10px]">
              <tr>
                <th className="text-left px-3 py-2">Ticker</th>
                <th className="text-right px-2 py-2">Shares</th>
                <th className="text-right px-2 py-2">Cost</th>
                <th className="text-right px-2 py-2">Price</th>
                <th className="text-right px-2 py-2">Loss</th>
                <th className="text-right px-2 py-2">Loss %</th>
                <th className="text-left px-2 py-2">Held</th>
                <th className="text-left px-2 py-2">Term</th>
                <th className="text-right px-2 py-2">Est. saving</th>
              </tr>
            </thead>
            <tbody>
              {q.data.candidates.map((c) => (
                <tr key={`${c.ticker}.${c.market}`} className="border-t border-zinc-200 dark:border-zinc-800 align-top">
                  <td className="px-3 py-1.5">
                    <div className="font-semibold">{c.ticker}</div>
                    <div className="text-[10px] text-zinc-500 uppercase">{c.market}</div>
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{c.shares}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {c.currency_symbol}{c.cost_basis.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {c.currency_symbol}{c.price.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-bear-600 font-semibold">
                    {c.currency_symbol}{c.unrealised_loss.toFixed(0)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-bear-500">
                    {c.loss_pct.toFixed(1)}%
                  </td>
                  <td className="px-2 py-1.5 text-zinc-500">{c.days_held}d</td>
                  <td className="px-2 py-1.5">
                    <span
                      className={`pill text-[10px] ${
                        c.term === "long"
                          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                          : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                      }`}
                      title={`${(c.tax_rate * 100).toFixed(1)}% rate`}
                    >
                      {c.term === "long" ? "LTCG" : "STCG"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums font-semibold text-bull-600">
                    {c.currency_symbol}{c.est_tax_saving.toFixed(0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4 py-2 text-[11px] text-zinc-400 border-t border-zinc-200 dark:border-zinc-800">
            {q.data.note}
          </div>
          {q.data.candidates.some((c) => c.notes.length > 0) && (
            <div className="px-4 py-2 text-[11px] text-zinc-500 border-t border-zinc-200 dark:border-zinc-800 space-y-1">
              {q.data.candidates
                .filter((c) => c.notes.length > 0)
                .map((c) => (
                  <div key={c.ticker}>
                    <span className="font-semibold">{c.ticker}:</span>{" "}
                    {c.notes.join(" · ")}
                  </div>
                ))}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

// --- Diversification ---

const _CLASS_LABEL: Record<string, string> = {
  equity: "Equity",
  etf: "Broad ETF",
  reit: "REIT (property)",
  gold: "Gold",
  debt: "Debt / bonds",
  cash: "Cash equivalent",
  other: "Other",
};

const _CLASS_BG: Record<string, string> = {
  equity: "bg-blue-500",
  etf: "bg-indigo-500",
  reit: "bg-purple-500",
  gold: "bg-amber-500",
  debt: "bg-emerald-500",
  cash: "bg-zinc-400",
  other: "bg-zinc-300",
};

function DiversificationSection() {
  const q = useQuery({
    queryKey: ["diversification"],
    queryFn: api.diversification,
    staleTime: 60 * 1000,
    retry: false,
  });

  return (
    <section className="space-y-3">
      <div className="flex items-baseline gap-2">
        <h2 className="text-base font-bold">Diversification</h2>
        <span className="text-xs text-zinc-500">
          asset-class mix · gaps · common instruments per market
        </span>
      </div>

      {q.isLoading ? (
        <div className="card p-4 text-sm text-zinc-500 flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      ) : q.error ? (
        <EmptyState title="Could not classify">{(q.error as Error).message}</EmptyState>
      ) : q.data ? (
        <div className="space-y-3">
          <AllocationBar slices={q.data.by_asset.filter((s) => s.pct > 0)} />
          {q.data.gaps.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {q.data.gaps.map((gap) => (
                <GapBlock
                  key={gap}
                  asset={gap}
                  instruments={q.data!.suggestions[gap] ?? []}
                />
              ))}
            </div>
          ) : (
            <div className="card p-3 text-xs text-zinc-500">
              No obvious gaps detected — you hold something in every major
              diversifier bucket (debt, gold, REIT).
            </div>
          )}
          <div className="text-[11px] text-zinc-400">{q.data.note}</div>
        </div>
      ) : null}
    </section>
  );
}

function AllocationBar({ slices }: { slices: { asset_class: string; pct: number; market_value: number; n_positions: number }[] }) {
  if (slices.length === 0) {
    return (
      <div className="card p-3 text-xs text-zinc-500">
        No holdings to classify yet.
      </div>
    );
  }
  return (
    <div className="card p-4 space-y-3">
      <div className="text-[11px] text-zinc-500 uppercase tracking-wider">
        Current allocation
      </div>
      <div className="flex h-3 w-full rounded overflow-hidden">
        {slices.map((s) => (
          <div
            key={s.asset_class}
            className={`${_CLASS_BG[s.asset_class] ?? "bg-zinc-300"}`}
            style={{ width: `${s.pct}%` }}
            title={`${_CLASS_LABEL[s.asset_class] ?? s.asset_class}: ${s.pct.toFixed(1)}%`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {slices.map((s) => (
          <div key={s.asset_class} className="flex items-center gap-1.5">
            <span className={`inline-block w-2 h-2 rounded-sm ${_CLASS_BG[s.asset_class] ?? "bg-zinc-300"}`} />
            <span className="text-zinc-600 dark:text-zinc-400">
              {_CLASS_LABEL[s.asset_class] ?? s.asset_class}
            </span>
            <span className="text-zinc-500 tabular-nums">
              {s.pct.toFixed(1)}% · {s.n_positions} pos
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function GapBlock({
  asset,
  instruments,
}: {
  asset: string;
  instruments: { symbol: string; market: string; name: string; description: string }[];
}) {
  const qc = useQueryClient();
  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 flex items-baseline justify-between">
        <div className="text-sm font-semibold">
          Gap: {_CLASS_LABEL[asset] ?? asset}
        </div>
        <div className="text-[11px] text-zinc-500">
          common instruments below — not advice
        </div>
      </div>
      {instruments.length === 0 ? (
        <div className="p-4 text-xs text-zinc-500">No reference instruments listed.</div>
      ) : (
        <table className="w-full text-xs">
          <tbody>
            {instruments.map((i) => (
              <tr key={`${i.symbol}.${i.market}`} className="border-t border-zinc-200 dark:border-zinc-800">
                <td className="px-3 py-1.5 align-top">
                  <div className="font-semibold">{i.symbol}</div>
                  <div className="text-[10px] text-zinc-500 uppercase">{i.market}</div>
                </td>
                <td className="px-2 py-1.5 align-top">
                  <div className="font-medium">{i.name}</div>
                  <div className="text-[11px] text-zinc-500 leading-snug">{i.description}</div>
                </td>
                <td className="px-2 py-1.5 align-top w-20 text-right">
                  <AddInstrumentButton instrument={i} qc={qc} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function AddInstrumentButton({
  instrument: i,
  qc,
}: {
  instrument: { symbol: string; market: string };
  qc: ReturnType<typeof useQueryClient>;
}) {
  const [added, setAdded] = useState(false);
  const m = useMutation({
    mutationFn: () =>
      api.addWatchlist({
        ticker: i.symbol,
        market: i.market,
        note: "diversification",
      }),
    onSuccess: () => {
      setAdded(true);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["insights"] });
    },
    onError: (e: Error) => {
      const msg = e.message.toLowerCase();
      if (msg.includes("already") || msg.includes("unique") || msg.includes("conflict")) {
        setAdded(true);
      }
    },
  });
  return (
    <button
      className="text-[11px] px-2 py-0.5 rounded border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
      onClick={() => m.mutate()}
      disabled={added || m.isPending}
    >
      {m.isPending ? "…" : added ? "✓ watching" : "+ Watch"}
    </button>
  );
}

// --- Discover ---

function DiscoverSection() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["discover"],
    queryFn: () => api.discover(),
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
  const refresh = useMutation({
    mutationFn: () => api.discover({ refresh: true }),
    onSuccess: (data) => qc.setQueryData(["discover"], data),
  });

  const data = q.data;
  const markets = data ? Object.keys(data.by_market) : [];

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h2 className="text-base font-bold flex items-center gap-2">
          <Compass size={16} className="text-zinc-500" />
          Discover
        </h2>
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          {data && (
            <>
              <span>
                scanned {sumValues(data.universe_sizes)} names across{" "}
                {Object.keys(data.universe_sizes).length} markets · excluded{" "}
                {data.excluded_count} you already hold
              </span>
              <LastRefreshed
                at={data.scanned_at}
                label={data.cached ? "cached" : "scanned"}
              />
            </>
          )}
          <button
            className="btn-ghost text-xs"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
            title="Force a fresh scan (slow — ~1 min)"
          >
            {refresh.isPending ? (
              <><Loader2 size={12} className="animate-spin" /> Scanning…</>
            ) : (
              <><RefreshCw size={12} /> Rescan</>
            )}
          </button>
        </div>
      </div>

      {q.isLoading || (refresh.isPending && !data) ? (
        <div className="card p-6 text-center text-sm text-zinc-500 flex items-center justify-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Scanning curated universes…
        </div>
      ) : q.error ? (
        <EmptyState title="Could not scan">{(q.error as Error).message}</EmptyState>
      ) : data ? (
        <div className="space-y-4">
          {markets.length === 0 && (
            <EmptyState title="Nothing to surface yet">
              The scan returned no Buy-rated names outside your portfolio for the
              chosen markets. Try clicking Rescan after the next session.
            </EmptyState>
          )}
          {markets.map((mkt) => (
            <DiscoverMarketBlock
              key={mkt}
              market={mkt}
              rows={data.by_market[mkt]}
              universeSize={data.universe_sizes[mkt] ?? 0}
            />
          ))}
        </div>
      ) : null}

      {data?.note && (
        <div className="text-[11px] text-zinc-400 leading-relaxed">{data.note}</div>
      )}
    </section>
  );
}

function DiscoverMarketBlock({
  market,
  rows,
  universeSize,
}: {
  market: string;
  rows: DiscoveryRow[];
  universeSize: number;
}) {
  // Sector chip filter — toggle one or many. Empty = all.
  const [activeSectors, setActiveSectors] = useState<Set<string>>(new Set());
  const sectors = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows) counts.set(r.sector, (counts.get(r.sector) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [rows]);

  const filtered = useMemo(() => {
    if (activeSectors.size === 0) return rows;
    return rows.filter((r) => activeSectors.has(r.sector));
  }, [rows, activeSectors]);

  const toggleSector = (s: string) => {
    setActiveSectors((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  };

  return (
    <div className="card overflow-hidden">
      <div className="flex items-baseline justify-between px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40">
        <div className="text-sm font-semibold uppercase tracking-wider">{market}</div>
        <div className="text-[11px] text-zinc-500">
          {filtered.length}
          {activeSectors.size > 0 && ` (${rows.length} total)`} of {universeSize} scored ≥ Buy
        </div>
      </div>

      {sectors.length > 1 && (
        <div className="px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 flex flex-wrap gap-1.5">
          {sectors.map(([sec, n]) => {
            const active = activeSectors.has(sec);
            return (
              <button
                key={sec}
                onClick={() => toggleSector(sec)}
                className={`pill text-[10px] cursor-pointer transition-all ${
                  active
                    ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                    : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                }`}
              >
                {sec} <span className="opacity-60">{n}</span>
              </button>
            );
          })}
          {activeSectors.size > 0 && (
            <button
              onClick={() => setActiveSectors(new Set())}
              className="pill text-[10px] bg-zinc-100 dark:bg-zinc-800 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-700"
            >
              clear
            </button>
          )}
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="p-4 text-xs text-zinc-500">
          {rows.length === 0
            ? "No Buy-rated names in this market right now."
            : "No names match the selected sector(s)."}
        </div>
      ) : (
        <table className="w-full text-xs">
          <thead className="text-zinc-500 uppercase tracking-wider text-[10px]">
            <tr>
              <th className="text-left px-3 py-2">Ticker</th>
              <th className="text-left px-2 py-2">Sector</th>
              <th className="text-right px-2 py-2">Price</th>
              <th className="text-right px-2 py-2">Day</th>
              <th className="text-left px-2 py-2">Signal</th>
              <th className="text-right px-2 py-2">RSI</th>
              <th className="text-left px-2 py-2">Trend</th>
              <th className="text-left px-2 py-2">Rules</th>
              <th className="text-left px-2 py-2">News</th>
              <th className="w-20"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r) => (
              <DiscoveryTableRow key={`${r.symbol}.${r.market}`} row={r} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function DiscoveryTableRow({ row: r }: { row: DiscoveryRow }) {
  const qc = useQueryClient();
  const [added, setAdded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: () =>
      api.addWatchlist({ ticker: r.symbol, market: r.market, note: "from Discover" }),
    onSuccess: () => {
      setAdded(true);
      setErr(null);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["insights"] });
    },
    onError: (e: Error) => {
      // 409 / duplicate is still useful to surface as "already on list"
      const msg = e.message.toLowerCase();
      if (msg.includes("already") || msg.includes("unique") || msg.includes("conflict")) {
        setAdded(true);
        setErr(null);
      } else {
        setErr(e.message);
      }
    },
  });

  return (
    <tr className="border-t border-zinc-200 dark:border-zinc-800">
      <td className="px-3 py-1.5">
        <span className="font-semibold">{r.symbol}</span>
      </td>
      <td className="px-2 py-1.5 text-[11px] text-zinc-500">{r.sector}</td>
      <td className="px-2 py-1.5 text-right tabular-nums font-mono">
        {r.price != null ? `${r.currency_symbol}${r.price.toFixed(2)}` : "—"}
      </td>
      <td
        className={`px-2 py-1.5 text-right tabular-nums ${
          (r.change_pct ?? 0) > 0
            ? "text-bull-500"
            : (r.change_pct ?? 0) < 0
            ? "text-bear-500"
            : "text-zinc-500"
        }`}
      >
        {r.change_pct != null ? fmtPct(r.change_pct, 1) : "—"}
      </td>
      <td className="px-2 py-1.5">
        <SignalPill label={r.score_label} score={r.score_value} compact />
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums">
        {r.rsi != null ? r.rsi.toFixed(0) : "—"}
      </td>
      <td className="px-2 py-1.5 text-zinc-600 dark:text-zinc-400">{r.trend ?? "—"}</td>
      <td className="px-2 py-1.5 text-zinc-500">
        {r.rule_count > 0 ? r.rule_names.slice(0, 2).join(" · ") : "—"}
      </td>
      <td className="px-2 py-1.5 text-zinc-500">{r.sentiment_label ?? "—"}</td>
      <td className="px-2 py-1.5">
        <button
          className="text-[11px] px-2 py-0.5 rounded border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
          onClick={() => add.mutate()}
          disabled={added || add.isPending}
          title={err ?? "Add to watchlist"}
        >
          {add.isPending ? "…" : added ? "✓ watching" : "+ Watch"}
        </button>
      </td>
    </tr>
  );
}

function sumValues(obj: Record<string, number>): number {
  return Object.values(obj).reduce((a, b) => a + b, 0);
}

// --- Market pulse ---

function MarketPulse({ indices }: { indices: IndexSnapshot[] }) {
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold">Market pulse</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {indices.map((ix) => (
          <div key={ix.symbol} className="card p-4">
            <div className="flex items-baseline justify-between">
              <div>
                <div className="font-semibold">{ix.name}</div>
                <div className="text-xs text-zinc-500">
                  {ix.symbol} · {ix.market}
                </div>
              </div>
              {ix.score_label && (
                <span
                  className={`text-[11px] font-semibold px-2 py-0.5 rounded ${
                    SIGNAL_STYLES[ix.score_label as SignalLabel]?.bg ?? "bg-zinc-500"
                  } text-white`}
                >
                  {ix.score_label}
                </span>
              )}
            </div>
            {ix.error ? (
              <div className="text-xs text-bear-500 mt-2">{ix.error}</div>
            ) : (
              <div className="mt-3 flex items-baseline gap-3">
                <div className="text-xl font-mono">
                  {ix.price != null ? ix.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}
                </div>
                <div
                  className={`text-sm ${
                    (ix.change_pct ?? 0) > 0
                      ? "text-bull-500"
                      : (ix.change_pct ?? 0) < 0
                      ? "text-bear-500"
                      : "text-zinc-500"
                  }`}
                >
                  {fmtPct(ix.change_pct)}
                </div>
                <div className="text-xs text-zinc-500 ml-auto">
                  RSI {ix.rsi != null ? ix.rsi.toFixed(0) : "—"} · {ix.trend ?? "—"}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// --- Conviction board ---

function ConvictionBoard({ rows }: { rows: ConvictionRow[] }) {
  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-bold">High-conviction holdings</h2>
        <span className="text-xs text-zinc-500">
          Score ≥ 6 with a confirming rule · {rows.length}
        </span>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No high-conviction signals right now">
          Nothing in the portfolio is currently both strongly scored
          <em> and </em> confirmed by a rule trigger. That's a useful answer too —
          most days the right move is no move.
        </EmptyState>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {rows.map((c) => (
            <div key={`${c.row.symbol}.${c.row.market}`} className="space-y-2">
              <StockCard row={c.row} attention />
              {c.rule_notes.length > 0 && (
                <ul className="text-xs text-zinc-500 list-disc pl-5">
                  {c.rule_notes.slice(0, 3).map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// --- Watchlist scan ---

function WatchlistSection({ scanned }: { scanned: any[] }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["watchlist"], queryFn: api.listWatchlist });

  const [ticker, setTicker] = useState("");
  const [market, setMarket] = useState("US");
  const [note, setNote] = useState("");

  const add = useMutation({
    mutationFn: () => api.addWatchlist({ ticker, market, note }),
    onSuccess: () => {
      setTicker("");
      setNote("");
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["insights"] });
    },
  });
  const remove = useMutation({
    mutationFn: (it: WatchlistItem) => api.removeWatchlist(it.ticker, it.market),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["insights"] });
    },
  });

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-bold">Watchlist</h2>
        <span className="text-xs text-zinc-500">
          Tickers you don't own, scanned with the same pipeline · {scanned.length}
        </span>
      </div>

      <form
        className="card p-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (ticker.trim()) add.mutate();
        }}
      >
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-zinc-500 mb-1 block">
            Ticker or company
          </label>
          <TickerCombo
            value={ticker}
            onChange={setTicker}
            onPick={(hit) => {
              setTicker(hit.symbol);
              setMarket(hit.market);
            }}
            placeholder="AAPL or Reliance Industries"
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">Market</label>
          <select
            className="input w-32"
            value={market}
            onChange={(e) => setMarket(e.target.value)}
          >
            <option value="US">US</option>
            <option value="NSE">NSE (India)</option>
            <option value="BSE">BSE (India)</option>
            <option value="DFM">DFM (Dubai)</option>
            <option value="ADX">ADX (Abu Dhabi)</option>
          </select>
        </div>
        <div className="flex-1 min-w-[160px]">
          <label className="text-xs text-zinc-500 mb-1 block">Note (optional)</label>
          <input
            className="input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="why you're watching"
          />
        </div>
        <button
          type="submit"
          className="btn-primary"
          disabled={!ticker.trim() || add.isPending}
        >
          {add.isPending ? "Adding…" : "Add to watchlist"}
        </button>
        {add.error && (
          <div className="basis-full text-sm text-bear-500">
            {(add.error as Error).message}
          </div>
        )}
      </form>

      {list.data && list.data.length > 0 ? (
        <WatchlistTable
          entries={list.data}
          scanned={scanned}
          onRemove={(w) => remove.mutate(w)}
        />
      ) : list.data ? (
        <EmptyState title="Watchlist is empty">
          Add a ticker above to scan it with the same scoring engine the
          dashboard uses.
        </EmptyState>
      ) : null}
    </section>
  );
}

function WatchlistTable({
  entries,
  scanned,
  onRemove,
}: {
  entries: WatchlistItem[];
  scanned: any[];
  onRemove: (w: WatchlistItem) => void;
}) {
  // Merge raw entries with scored cards so each row carries everything.
  const scannedByKey = new Map<string, any>(
    scanned.map((s) => [`${(s.symbol ?? "").toUpperCase()}.${(s.market ?? "").toUpperCase()}`, s]),
  );
  const pendingCount = entries.filter(
    (w) => !scannedByKey.get(`${w.ticker.toUpperCase()}.${w.market.toUpperCase()}`),
  ).length;

  return (
    <div className="card overflow-x-auto">
      {pendingCount > 0 && (
        <div className="px-4 py-2 text-[11px] text-zinc-500 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/40 flex items-center gap-2">
          <Loader2 size={12} className="animate-spin" />
          {pendingCount} new entr{pendingCount === 1 ? "y" : "ies"} — price &
          signal will appear after the next Insights refresh.
        </div>
      )}
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 text-[10px] uppercase tracking-wider">
          <tr>
            <th className="text-left px-3 py-2">Ticker</th>
            <th className="text-right px-2 py-2">Price</th>
            <th className="text-right px-2 py-2">Day</th>
            <th className="text-left px-2 py-2">Signal</th>
            <th className="text-right px-2 py-2">RSI</th>
            <th className="text-left px-2 py-2">Trend</th>
            <th className="text-left px-3 py-2">Note</th>
            <th className="text-left px-2 py-2">Added</th>
            <th className="px-2 py-2 w-6"></th>
          </tr>
        </thead>
        <tbody>
          {entries.map((w) => {
            const key = `${w.ticker.toUpperCase()}.${w.market.toUpperCase()}`;
            const s = scannedByKey.get(key);
            const price = s?.price as number | null | undefined;
            const change = s?.change_pct as number | null | undefined;
            const err = s?.error as string | null | undefined;
            return (
              <tr
                key={key}
                className="border-t border-zinc-200 dark:border-zinc-800"
              >
                <td className="px-3 py-1.5">
                  <div className="font-semibold">{w.ticker}</div>
                  <div className="text-[10px] text-zinc-500 uppercase">
                    {w.market}
                  </div>
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums font-mono">
                  {price != null
                    ? `${s.currency_symbol ?? ""}${price.toFixed(2)}`
                    : err
                    ? <span className="text-bear-500 text-[11px]" title={err}>err</span>
                    : <span className="text-zinc-400">—</span>}
                </td>
                <td
                  className={`px-2 py-1.5 text-right tabular-nums text-xs ${
                    (change ?? 0) > 0
                      ? "text-bull-500"
                      : (change ?? 0) < 0
                      ? "text-bear-500"
                      : "text-zinc-500"
                  }`}
                >
                  {change != null ? fmtPct(change, 1) : "—"}
                </td>
                <td className="px-2 py-1.5">
                  {s?.score_label ? (
                    <SignalPill label={s.score_label} score={s.score_value} compact />
                  ) : (
                    <span className="text-zinc-400 text-xs">—</span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums text-xs">
                  {s?.rsi != null ? s.rsi.toFixed(0) : "—"}
                </td>
                <td className="px-2 py-1.5 text-xs text-zinc-600 dark:text-zinc-400">
                  {s?.trend ?? "—"}
                </td>
                <td className="px-3 py-1.5 text-zinc-500 text-xs">
                  {w.note || "—"}
                </td>
                <td className="px-2 py-1.5 text-zinc-500 text-[11px]">
                  {w.date_added}
                </td>
                <td className="px-2 py-1.5 text-right">
                  <button
                    className="text-zinc-400 hover:text-bear-500 p-1"
                    onClick={() => onRemove(w)}
                    aria-label={`Remove ${w.ticker}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// --- Signal changes ---

function SignalChangesPanel({ changes }: { changes: SignalChange[] }) {
  if (changes.length === 0) {
    return (
      <section className="space-y-3">
        <h2 className="text-base font-bold">Recent signal changes</h2>
        <EmptyState title="No flips since last refresh">
          The conviction score on each holding is the same as the last build.
          Try refreshing tomorrow.
        </EmptyState>
      </section>
    );
  }
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold">Recent signal changes</h2>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 text-xs uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-2.5">Ticker</th>
              <th className="text-left px-4 py-2.5">Was</th>
              <th className="text-left px-4 py-2.5">Now</th>
              <th className="text-right px-4 py-2.5">Δ score</th>
              <th className="text-left px-4 py-2.5">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {changes.map((c) => {
              const delta = c.current_value - c.previous_value;
              const positive = delta > 0;
              const Icon = positive ? TrendingUp : TrendingDown;
              return (
                <tr
                  key={`${c.symbol}.${c.market}`}
                  className="border-t border-zinc-200 dark:border-zinc-800"
                >
                  <td className="px-4 py-2.5 font-semibold">
                    {c.symbol}
                    <span className="text-xs text-zinc-500 ml-2">{c.market}</span>
                  </td>
                  <td className="px-4 py-2.5 text-zinc-500">{c.previous_label}</td>
                  <td className="px-4 py-2.5 font-semibold">{c.current_label}</td>
                  <td
                    className={`px-4 py-2.5 text-right font-mono ${
                      positive ? "text-bull-500" : "text-bear-500"
                    }`}
                  >
                    <span className="inline-flex items-center gap-1">
                      <Icon size={12} />
                      {(positive ? "+" : "") + delta.toFixed(1)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-zinc-500">
                    {c.captured_previous_at}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// --- Earnings ---

function EarningsPanel({ items }: { items: EarningsItem[] }) {
  return (
    <section className="space-y-3">
      <div className="flex items-baseline gap-2">
        <CalendarClock size={16} className="text-zinc-500" />
        <h2 className="text-base font-bold">Upcoming earnings (30 days)</h2>
      </div>
      {items.length === 0 ? (
        <EmptyState title="No earnings reports in the next 30 days">
          Nothing in your portfolio has a confirmed earnings date soon.
        </EmptyState>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left px-4 py-2.5">Ticker</th>
                <th className="text-left px-4 py-2.5">Market</th>
                <th className="text-left px-4 py-2.5">Date</th>
                <th className="text-right px-4 py-2.5">In</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr
                  key={`${e.symbol}.${e.market}-${e.earnings_date}`}
                  className="border-t border-zinc-200 dark:border-zinc-800"
                >
                  <td className="px-4 py-2.5 font-semibold">{e.symbol}</td>
                  <td className="px-4 py-2.5 text-zinc-500 text-xs uppercase">{e.market}</td>
                  <td className="px-4 py-2.5">{e.earnings_date}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-zinc-600 dark:text-zinc-300">
                    {e.days_until === 0 ? "today" : `${e.days_until}d`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// --- Risk view ---

function RiskView({ risk }: { risk: RiskPanel }) {
  return (
    <section className="space-y-3">
      <div className="flex items-baseline gap-2">
        <AlertTriangle size={16} className="text-zinc-500" />
        <h2 className="text-base font-bold">Portfolio risk</h2>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="card p-4">
          <div className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            Top 5 weights
          </div>
          {risk.top_weights.length === 0 ? (
            <div className="text-sm text-zinc-500">—</div>
          ) : (
            <ul className="space-y-1.5">
              {risk.top_weights.map((w) => (
                <li
                  key={`${w.symbol}.${w.market}`}
                  className="flex items-baseline justify-between text-sm"
                >
                  <span className="font-semibold">{w.symbol}</span>
                  <span className="text-xs text-zinc-500 mx-2">{w.market}</span>
                  <span className="ml-auto font-mono">{w.weight_pct.toFixed(1)}%</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-4">
          <div className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            Currency exposure
          </div>
          {risk.currency_exposure.length === 0 ? (
            <div className="text-sm text-zinc-500">—</div>
          ) : (
            <ul className="space-y-1.5">
              {risk.currency_exposure.map((c) => (
                <li
                  key={c.currency}
                  className="flex items-baseline justify-between text-sm"
                >
                  <span className="font-semibold">
                    {c.currency_symbol} {c.currency}
                  </span>
                  <span className="ml-auto font-mono">
                    {c.pct_of_total_inr.toFixed(1)}%
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="text-[11px] text-zinc-400 mt-3">
            Approximate split using a fixed USD↔INR rate. For position-sizing,
            not for P&L.
          </div>
        </div>

        <div className="card p-4 space-y-3">
          <div>
            <div className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
              Biggest winners
            </div>
            {risk.biggest_winners.length === 0 ? (
              <div className="text-sm text-zinc-500">—</div>
            ) : (
              <ul className="space-y-1">
                {risk.biggest_winners.map((r) => (
                  <li
                    key={`win-${r.symbol}.${r.market}`}
                    className="flex items-baseline justify-between text-sm"
                  >
                    <span className="font-semibold">{r.symbol}</span>
                    <span className="ml-auto font-mono text-bull-500">
                      {fmtPct(r.pnl_pct)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="border-t border-zinc-200 dark:border-zinc-800 pt-3">
            <div className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
              Biggest losers
            </div>
            {risk.biggest_losers.length === 0 ? (
              <div className="text-sm text-zinc-500">—</div>
            ) : (
              <ul className="space-y-1">
                {risk.biggest_losers.map((r) => (
                  <li
                    key={`lose-${r.symbol}.${r.market}`}
                    className="flex items-baseline justify-between text-sm"
                  >
                    <span className="font-semibold">{r.symbol}</span>
                    <span className="ml-auto font-mono text-bear-500">
                      {fmtPct(r.pnl_pct)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

// Silence unused-import warning for fmtCurrency when grid is empty.
void fmtCurrency;

// --- Alerts ---

const ALERT_KIND_LABEL: Record<AlertKind, string> = {
  price_above: "Price ≥",
  price_below: "Price ≤",
  rsi_above: "RSI ≥",
  rsi_below: "RSI ≤",
  score_at_or_above: "Score ≥",
  score_at_or_below: "Score ≤",
  score_flip_buy: "Flips to Buy",
  score_flip_sell: "Flips to Sell",
  pct_drop_day: "Drops % today ≥",
  pct_rise_day: "Rises % today ≥",
};

const ALERT_THRESHOLD_HINT: Record<AlertKind, string> = {
  price_above: "price level",
  price_below: "price level",
  rsi_above: "RSI value (typically 70)",
  rsi_below: "RSI value (typically 30)",
  score_at_or_above: "score value (e.g. 6 = Strong Buy)",
  score_at_or_below: "score value (e.g. -6 = Strong Sell)",
  score_flip_buy: "(ignored — flips into Buy region)",
  score_flip_sell: "(ignored — flips into Sell region)",
  pct_drop_day: "% drop (positive value)",
  pct_rise_day: "% rise (positive value)",
};

function AlertsSection() {
  const qc = useQueryClient();
  const events = useQuery({
    queryKey: ["alert-events"],
    queryFn: () => api.listAlertEvents(false),
  });
  const rules = useQuery({
    queryKey: ["alerts"],
    queryFn: api.listAlerts,
  });

  const unack = (events.data ?? []).filter((e) => !e.acknowledged);
  const recent = (events.data ?? []).slice(0, 20);

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-bold flex items-center gap-2">
          <Bell size={16} className="text-zinc-500" />
          Alerts
          {unack.length > 0 && (
            <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1 text-[11px] font-semibold rounded-full bg-bear-500 text-white">
              {unack.length}
            </span>
          )}
        </h2>
        {unack.length > 0 && (
          <button
            className="btn-ghost text-xs"
            onClick={async () => {
              await api.ackAllAlertEvents();
              qc.invalidateQueries({ queryKey: ["alert-events"] });
            }}
          >
            <CheckCheck size={14} /> Mark all read
          </button>
        )}
      </div>

      <AlertEventsList events={recent} onAcked={() => qc.invalidateQueries({ queryKey: ["alert-events"] })} />
      <AlertRuleForm onAdded={() => qc.invalidateQueries({ queryKey: ["alerts"] })} />
      <AlertRulesList rules={rules.data ?? []} onChanged={() => qc.invalidateQueries({ queryKey: ["alerts"] })} />
    </section>
  );
}

function AlertEventsList({
  events,
  onAcked,
}: {
  events: AlertEvent[];
  onAcked: () => void;
}) {
  if (events.length === 0) {
    return (
      <EmptyState title="No alerts have fired yet">
        Add a rule below. It will be evaluated on every dashboard refresh and
        anything that crosses your threshold will land here.
      </EmptyState>
    );
  }
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 text-xs uppercase tracking-wider">
          <tr>
            <th className="text-left px-4 py-2.5">Ticker</th>
            <th className="text-left px-4 py-2.5">Rule</th>
            <th className="text-left px-4 py-2.5">Message</th>
            <th className="text-left px-4 py-2.5">Fired</th>
            <th className="px-4 py-2.5"></th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr
              key={e.id}
              className={`border-t border-zinc-200 dark:border-zinc-800 ${
                e.acknowledged ? "opacity-50" : ""
              }`}
            >
              <td className="px-4 py-2.5 font-semibold">
                {e.ticker}
                <span className="text-xs text-zinc-500 ml-2">{e.market}</span>
              </td>
              <td className="px-4 py-2.5 text-xs text-zinc-500">
                {ALERT_KIND_LABEL[e.kind] ?? e.kind} {e.threshold}
              </td>
              <td className="px-4 py-2.5">{e.message ?? "—"}</td>
              <td className="px-4 py-2.5 text-xs text-zinc-500">{e.fired_at}</td>
              <td className="px-4 py-2.5 text-right">
                {!e.acknowledged && (
                  <button
                    className="btn-ghost text-xs"
                    onClick={async () => {
                      await api.ackAlertEvent(e.id);
                      onAcked();
                    }}
                    aria-label="Mark read"
                  >
                    <Check size={14} />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AlertRuleForm({ onAdded }: { onAdded: () => void }) {
  const [ticker, setTicker] = useState("");
  const [market, setMarket] = useState("US");
  const [kind, setKind] = useState<AlertKind>("price_above");
  const [threshold, setThreshold] = useState<string>("");
  const [note, setNote] = useState("");

  const add = useMutation({
    mutationFn: () =>
      api.addAlert({
        ticker,
        market,
        kind,
        threshold: parseFloat(threshold) || 0,
        note,
      }),
    onSuccess: () => {
      setThreshold("");
      setNote("");
      onAdded();
    },
  });

  const flipKind = kind === "score_flip_buy" || kind === "score_flip_sell";

  return (
    <form
      className="card p-4 grid grid-cols-1 md:grid-cols-6 gap-3 items-end"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ticker.trim()) return;
        if (!flipKind && !threshold) return;
        add.mutate();
      }}
    >
      <div className="md:col-span-2">
        <label className="text-xs text-zinc-500 mb-1 block">Ticker</label>
        <TickerCombo
          value={ticker}
          onChange={setTicker}
          onPick={(hit) => {
            setTicker(hit.symbol);
            setMarket(hit.market);
          }}
          placeholder="AAPL or RELIANCE"
        />
      </div>
      <div>
        <label className="text-xs text-zinc-500 mb-1 block">Market</label>
        <select className="input" value={market} onChange={(e) => setMarket(e.target.value)}>
          <option value="US">US</option>
          <option value="NSE">NSE (India)</option>
          <option value="BSE">BSE (India)</option>
          <option value="DFM">DFM (Dubai)</option>
          <option value="ADX">ADX (Abu Dhabi)</option>
        </select>
      </div>
      <div>
        <label className="text-xs text-zinc-500 mb-1 block">When</label>
        <select
          className="input"
          value={kind}
          onChange={(e) => setKind(e.target.value as AlertKind)}
        >
          {(Object.keys(ALERT_KIND_LABEL) as AlertKind[]).map((k) => (
            <option key={k} value={k}>
              {ALERT_KIND_LABEL[k]}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-xs text-zinc-500 mb-1 block">Threshold</label>
        <input
          className="input"
          type="number"
          step="any"
          disabled={flipKind}
          value={flipKind ? "" : threshold}
          onChange={(e) => setThreshold(e.target.value)}
          placeholder={ALERT_THRESHOLD_HINT[kind]}
        />
      </div>
      <button
        type="submit"
        className="btn-primary"
        disabled={
          add.isPending || !ticker.trim() || (!flipKind && !threshold)
        }
      >
        {add.isPending ? "Adding…" : "Add rule"}
      </button>
      <div className="md:col-span-6">
        <label className="text-xs text-zinc-500 mb-1 block">Note (optional)</label>
        <input
          className="input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="why this matters to you"
        />
      </div>
      {add.error && (
        <div className="md:col-span-6 text-sm text-bear-500">
          {(add.error as Error).message}
        </div>
      )}
    </form>
  );
}

function AlertRulesList({
  rules,
  onChanged,
}: {
  rules: Alert[];
  onChanged: () => void;
}) {
  if (rules.length === 0) return null;
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 text-xs uppercase tracking-wider">
          <tr>
            <th className="text-left px-4 py-2.5">Ticker</th>
            <th className="text-left px-4 py-2.5">Rule</th>
            <th className="text-left px-4 py-2.5">Note</th>
            <th className="text-left px-4 py-2.5">Last fired</th>
            <th className="px-4 py-2.5"></th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <tr
              key={r.id}
              className={`border-t border-zinc-200 dark:border-zinc-800 ${
                r.active ? "" : "opacity-50"
              }`}
            >
              <td className="px-4 py-2.5 font-semibold">
                {r.ticker}
                <span className="text-xs text-zinc-500 ml-2">{r.market}</span>
              </td>
              <td className="px-4 py-2.5 text-xs">
                {ALERT_KIND_LABEL[r.kind] ?? r.kind}{" "}
                {!(r.kind === "score_flip_buy" || r.kind === "score_flip_sell") && r.threshold}
              </td>
              <td className="px-4 py-2.5 text-zinc-500">{r.note || "—"}</td>
              <td className="px-4 py-2.5 text-xs text-zinc-500">
                {r.last_fired_at ?? "never"}
              </td>
              <td className="px-4 py-2.5 text-right flex gap-2 justify-end">
                <button
                  className="btn-ghost text-xs"
                  onClick={async () => {
                    await api.toggleAlert(r.id, !r.active);
                    onChanged();
                  }}
                  aria-label={r.active ? "Disable" : "Enable"}
                >
                  {r.active ? <BellOff size={14} /> : <Bell size={14} />}
                </button>
                <button
                  className="btn-ghost text-xs text-bear-500"
                  onClick={async () => {
                    await api.removeAlert(r.id);
                    onChanged();
                  }}
                  aria-label="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
