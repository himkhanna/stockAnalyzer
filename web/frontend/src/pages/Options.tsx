import {
  Calculator,
  ChevronRight,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { LastRefreshed } from "../components/LastRefreshed";
import { TickerCombo } from "../components/TickerCombo";
import { bsPrice } from "../lib/blackScholes";
import type { OptionChain, OptionRow, PayoffLeg } from "../types";

export function OptionsPage() {
  // Lift state so IV panel + covered-calls section can react to the chain's
  // chosen symbol/expiry without forcing the user to re-enter them.
  const [symbol, setSymbol] = useState("");
  const [brokerCode, setBrokerCode] = useState("");
  const [expiry, setExpiry] = useState<string>("");

  // Template legs the user has clicked. Consumed by PayoffSection.
  const [templateLegs, setTemplateLegs] = useState<TemplateLegs | null>(null);

  return (
    <div className="space-y-10 pb-12">
      <header className="space-y-1">
        <h1 className="text-xl font-bold">Options (NSE F&amp;O)</h1>
        <p className="text-xs text-zinc-500">
          Read-only chain data + payoff math. Greeks via Black-Scholes (r =
          7%). No directional recommendations are made for options.
        </p>
      </header>

      <ChainSection
        symbol={symbol}
        setSymbol={setSymbol}
        brokerCode={brokerCode}
        setBrokerCode={setBrokerCode}
        expiry={expiry}
        setExpiry={setExpiry}
      />
      <ChainStatsPanel symbol={symbol} brokerCode={brokerCode} expiry={expiry} />
      <IVSmilePanel symbol={symbol} brokerCode={brokerCode} expiry={expiry} />
      <IVPanel symbol={symbol} brokerCode={brokerCode} expiry={expiry} />
      <CoveredCallsSection
        symbol={symbol}
        brokerCode={brokerCode}
        expiry={expiry}
      />
      <PayoffSection initialLegs={templateLegs} onTemplate={setTemplateLegs} />
    </div>
  );
}

// ---- Chain ----

interface ChainProps {
  symbol: string;
  setSymbol: (v: string) => void;
  brokerCode: string;
  setBrokerCode: (v: string) => void;
  expiry: string;
  setExpiry: (v: string) => void;
}

function ChainSection({
  symbol,
  setSymbol,
  brokerCode,
  setBrokerCode,
  expiry,
  setExpiry,
}: ChainProps) {

  // Verified per-symbol expiries (asks Breeze which last-week dates actually
  // have contracts). Falls back to the calendar list if probe hasn't run /
  // hasn't returned anything.
  const probe = useQuery({
    queryKey: ["option-expiries-probe", symbol.trim().toUpperCase(), brokerCode.trim().toUpperCase()],
    queryFn: () => api.optionExpiriesProbe(symbol.trim(), brokerCode.trim() || undefined),
    enabled: symbol.trim().length >= 2,
    staleTime: 60 * 60 * 1000, // 1h — backend already caches per-day
    retry: false,
  });
  const qc = useQueryClient();
  const rescanProbe = useMutation({
    mutationFn: () => api.optionExpiriesProbe(symbol.trim(), brokerCode.trim() || undefined, true),
    onSuccess: (data) => {
      qc.setQueryData(
        ["option-expiries-probe", symbol.trim().toUpperCase(), brokerCode.trim().toUpperCase()],
        data,
      );
    },
  });

  const fallback = useQuery({
    queryKey: ["option-expiries"],
    queryFn: api.optionExpiries,
  });

  // Drop a previously-picked expiry if the probed list no longer contains it.
  const probedExpiries = probe.data?.expiries ?? [];
  useEffect(() => {
    if (expiry && probedExpiries.length > 0 && !probedExpiries.includes(expiry)) {
      setExpiry("");
    }
  }, [expiry, probedExpiries]);

  const chain = useMutation({
    mutationFn: () => api.optionChain(symbol, expiry, brokerCode || undefined),
  });

  const grouped = useMemo(() => groupByStrike(chain.data?.rows ?? []), [chain.data]);

  // Pick the strike closest to spot.
  const atmStrike = useMemo(() => {
    if (!chain.data?.spot || grouped.length === 0) return null;
    const spot = chain.data.spot;
    return grouped.reduce((best, g) =>
      Math.abs(g.strike - spot) < Math.abs(best.strike - spot) ? g : best,
    ).strike;
  }, [chain.data, grouped]);

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h2 className="text-base font-bold">Option chain</h2>
        <div className="flex items-baseline gap-3">
          {chain.data?.spot && (
            <span className="text-xs text-zinc-500">
              spot ₹{chain.data.spot.toFixed(2)} · {chain.data.days_to_expiry}d to expiry · r {(chain.data.risk_free_rate * 100).toFixed(1)}%
            </span>
          )}
          {chain.data && chain.submittedAt && (
            <LastRefreshed at={new Date(chain.submittedAt).toISOString()} label="fetched" compact />
          )}
        </div>
      </div>

      <form
        className="card p-4 grid grid-cols-1 md:grid-cols-12 gap-3 items-end"
        onSubmit={(e) => {
          e.preventDefault();
          if (symbol && expiry) chain.mutate();
        }}
      >
        <div className="md:col-span-4">
          <label className="text-xs text-zinc-500 mb-1 block">Underlying</label>
          <TickerCombo
            value={symbol}
            onChange={setSymbol}
            placeholder="RELIANCE / NIFTY / INFY"
          />
        </div>
        <div className="md:col-span-3">
          <label className="text-xs text-zinc-500 mb-1 block">
            Broker code <span className="text-zinc-400">(if different)</span>
          </label>
          <input
            className="input"
            value={brokerCode}
            onChange={(e) => setBrokerCode(e.target.value.toUpperCase())}
            placeholder="e.g. RELIND, EXIIND"
          />
        </div>
        <div className="md:col-span-3">
          <label className="text-xs text-zinc-500 mb-1 block flex items-center gap-1.5">
            <span>Expiry</span>
            {(probe.isFetching || rescanProbe.isPending) && (
              <Loader2 size={10} className="inline animate-spin text-zinc-400" />
            )}
            {probe.data && !probe.isFetching && !rescanProbe.isPending && (
              <span className="text-zinc-400">· verified</span>
            )}
            <button
              type="button"
              className="ml-auto text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
              onClick={() => rescanProbe.mutate()}
              disabled={rescanProbe.isPending || !symbol.trim()}
              title="Re-probe Breeze (bypass cache)"
              aria-label="Rescan expiries"
            >
              <RefreshCw size={11} />
            </button>
          </label>
          <select
            className="input"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          >
            <option value="">— pick one —</option>
            {probedExpiries.length > 0 ? (
              <optgroup label={`Available for ${probe.data?.underlying_broker_code ?? symbol}`}>
                {probedExpiries.map((d) => (
                  <option key={`p-${d}`} value={d}>{d}</option>
                ))}
              </optgroup>
            ) : (
              <>
                {fallback.data?.weekly && (
                  <optgroup label="Weekly (NIFTY/BANKNIFTY only)">
                    {fallback.data.weekly.map((d) => (
                      <option key={`w-${d}`} value={d}>{d}</option>
                    ))}
                  </optgroup>
                )}
                {fallback.data?.monthly && (
                  <optgroup label="Monthly (calendar)">
                    {fallback.data.monthly.map((d) => (
                      <option key={`m-${d}`} value={d}>{d}</option>
                    ))}
                  </optgroup>
                )}
              </>
            )}
          </select>
        </div>
        <div className="md:col-span-2">
          <button
            type="submit"
            className="btn-primary w-full"
            disabled={!symbol || !expiry || chain.isPending}
          >
            {chain.isPending ? (
              <><Loader2 size={14} className="animate-spin" /> Loading…</>
            ) : (
              <><ChevronRight size={14} /> Load chain</>
            )}
          </button>
        </div>
        {chain.error && (
          <div className="md:col-span-12 text-sm text-bear-500">
            {(chain.error as Error).message}
          </div>
        )}
      </form>

      {chain.data && grouped.length === 0 && (
        <EmptyState title="No chain rows">
          Breeze returned no contracts for this combination. Try a different
          underlying, expiry, or specify the ICICI broker code (e.g. RELIND
          for Reliance).
        </EmptyState>
      )}

      {grouped.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 uppercase tracking-wider">
              <tr>
                <th colSpan={5} className="text-center py-2 border-r border-zinc-200 dark:border-zinc-800 text-bull-600 font-bold">CALLS</th>
                <th className="px-2 py-2 text-center bg-zinc-100 dark:bg-zinc-800">STRIKE</th>
                <th colSpan={5} className="text-center py-2 border-l border-zinc-200 dark:border-zinc-800 text-bear-600 font-bold">PUTS</th>
              </tr>
              <tr>
                <th className="px-2 py-1 text-right">OI</th>
                <th className="px-2 py-1 text-right">IV</th>
                <th className="px-2 py-1 text-right">Δ</th>
                <th className="px-2 py-1 text-right">LTP</th>
                <th className="px-2 py-1 text-right border-r border-zinc-200 dark:border-zinc-800">Bid/Ask</th>
                <th className="px-2 py-1 text-center bg-zinc-100 dark:bg-zinc-800">K</th>
                <th className="px-2 py-1 text-left border-l border-zinc-200 dark:border-zinc-800">Bid/Ask</th>
                <th className="px-2 py-1 text-left">LTP</th>
                <th className="px-2 py-1 text-left">Δ</th>
                <th className="px-2 py-1 text-left">IV</th>
                <th className="px-2 py-1 text-left">OI</th>
              </tr>
            </thead>
            <tbody>
              {grouped.map((g) => {
                const isAtm = atmStrike != null && g.strike === atmStrike;
                return (
                  <tr
                    key={g.strike}
                    className={`border-t border-zinc-200 dark:border-zinc-800 ${
                      isAtm ? "bg-amber-50 dark:bg-amber-900/10" : ""
                    }`}
                  >
                    <CallCell row={g.call} field="open_interest" align="right" />
                    <CallCell row={g.call} field="iv" align="right" pct />
                    <CallCell row={g.call} field="delta" align="right" />
                    <CallCell row={g.call} field="ltp" align="right" />
                    <td className="px-2 py-1 text-right text-zinc-500 border-r border-zinc-200 dark:border-zinc-800">
                      <BidAsk row={g.call} />
                    </td>
                    <td className="px-2 py-1 text-center font-mono font-bold bg-zinc-50 dark:bg-zinc-900/50">
                      {g.strike}
                    </td>
                    <td className="px-2 py-1 text-left text-zinc-500 border-l border-zinc-200 dark:border-zinc-800">
                      <BidAsk row={g.put} />
                    </td>
                    <PutCell row={g.put} field="ltp" />
                    <PutCell row={g.put} field="delta" />
                    <PutCell row={g.put} field="iv" pct />
                    <PutCell row={g.put} field="open_interest" />
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---- Chain stats: max-pain + PCR + OI by strike ----

function ChainStatsPanel({
  symbol,
  brokerCode,
  expiry,
}: {
  symbol: string;
  brokerCode: string;
  expiry: string;
}) {
  const stats = useQuery({
    queryKey: ["chain-stats", symbol.trim().toUpperCase(), brokerCode.trim().toUpperCase(), expiry],
    queryFn: () => api.optionChainStats(symbol.trim(), expiry, brokerCode.trim() || undefined),
    enabled: !!symbol.trim() && !!expiry,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  if (!symbol.trim() || !expiry) return null;

  const data = stats.data;
  const pcrTone = (pcr: number | null | undefined) =>
    pcr == null ? "text-zinc-400" : pcr >= 1.3 ? "text-bull-500" : pcr <= 0.7 ? "text-bear-500" : "text-zinc-600 dark:text-zinc-300";

  return (
    <section className="space-y-2">
      <div className="flex items-baseline gap-2">
        <h2 className="text-base font-bold">Max-pain &amp; PCR</h2>
        <span className="text-xs text-zinc-500">
          where option writers want spot to land · open-interest skew
        </span>
      </div>
      <div className="card p-4 space-y-4">
        {stats.isFetching && !data ? (
          <div className="text-sm text-zinc-500 flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : stats.error ? (
          <div className="text-sm text-bear-500">{(stats.error as Error).message}</div>
        ) : data ? (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat
                label="Max-pain strike"
                v={data.max_pain_strike}
                subtitle={
                  data.max_pain_distance_pct != null
                    ? `${data.max_pain_distance_pct >= 0 ? "+" : ""}${data.max_pain_distance_pct.toFixed(1)}% vs spot`
                    : "—"
                }
                tone="neutral"
              />
              <Stat
                label="PCR (OI)"
                v={data.pcr_oi}
                subtitle={
                  data.pcr_oi == null
                    ? "—"
                    : data.pcr_oi >= 1.3
                    ? "puts heavy — fear or hedging"
                    : data.pcr_oi <= 0.7
                    ? "calls heavy — bullish positioning"
                    : "balanced"
                }
                tone="neutral"
              />
              <div className="rounded-md border border-zinc-200 dark:border-zinc-800 p-3">
                <div className="text-[11px] text-zinc-500 uppercase tracking-wider">
                  Call OI
                </div>
                <div className="text-lg font-mono font-semibold text-bull-500">
                  {Math.round(data.total_call_oi).toLocaleString()}
                </div>
                <div className="text-xs text-zinc-500 mt-0.5">total contracts</div>
              </div>
              <div className="rounded-md border border-zinc-200 dark:border-zinc-800 p-3">
                <div className="text-[11px] text-zinc-500 uppercase tracking-wider">
                  Put OI
                </div>
                <div className="text-lg font-mono font-semibold text-bear-500">
                  {Math.round(data.total_put_oi).toLocaleString()}
                </div>
                <div className="text-xs text-zinc-500 mt-0.5">total contracts</div>
              </div>
            </div>

            {data.oi_by_strike.length > 0 && (
              <div className="h-64 w-full">
                <ResponsiveContainer>
                  <BarChart data={data.oi_by_strike} margin={{ left: 10, right: 10, top: 10, bottom: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(120,120,120,0.2)" />
                    <XAxis
                      dataKey="strike"
                      tick={{ fontSize: 10 }}
                      tickFormatter={(v) => v.toFixed(0)}
                      label={{ value: "Strike", position: "insideBottom", offset: -5, fontSize: 10 }}
                    />
                    <YAxis
                      tick={{ fontSize: 10 }}
                      tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)}
                    />
                    <Tooltip
                      contentStyle={{ fontSize: 12 }}
                      formatter={(v: number) => Math.round(v).toLocaleString()}
                    />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {data.spot != null && (
                      <ReferenceLine
                        x={data.spot}
                        stroke="rgba(245,158,11,0.7)"
                        strokeDasharray="3 3"
                        label={{ value: "spot", fontSize: 10, fill: "rgb(245,158,11)" }}
                      />
                    )}
                    {data.max_pain_strike != null && (
                      <ReferenceLine
                        x={data.max_pain_strike}
                        stroke="rgba(120,120,120,0.7)"
                        strokeDasharray="2 4"
                        label={{ value: "max-pain", fontSize: 10, fill: "rgb(120,120,120)" }}
                      />
                    )}
                    <Bar dataKey="call_oi" name="Calls OI" fill="#22c55e" opacity={0.7} />
                    <Bar dataKey="put_oi" name="Puts OI" fill="#ef4444" opacity={0.7} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        ) : null}
        {data && (
          <div className="text-[11px] text-zinc-400 leading-relaxed">{data.note}</div>
        )}
      </div>
    </section>
  );
}

// ---- IV smile chart ----

function IVSmilePanel({
  symbol,
  brokerCode,
  expiry,
}: {
  symbol: string;
  brokerCode: string;
  expiry: string;
}) {
  const q = useQuery({
    queryKey: ["chain-for-smile", symbol.trim().toUpperCase(), brokerCode.trim().toUpperCase(), expiry],
    queryFn: () => api.optionChain(symbol.trim(), expiry, brokerCode.trim() || undefined),
    enabled: !!symbol.trim() && !!expiry,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const points = useMemo(() => extractSmile(q.data), [q.data]);

  if (!symbol.trim() || !expiry) return null;
  if (!q.data && !q.isFetching) return null;

  return (
    <section className="space-y-2">
      <div className="flex items-baseline gap-2">
        <h2 className="text-base font-bold">IV smile</h2>
        <span className="text-xs text-zinc-500">
          implied vol vs strike · skew shows where the market is paying up
        </span>
      </div>
      <div className="card p-4">
        {q.isFetching && !q.data ? (
          <div className="text-sm text-zinc-500 flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : q.error ? (
          <div className="text-sm text-bear-500">{(q.error as Error).message}</div>
        ) : points.length < 3 ? (
          <div className="text-sm text-zinc-500">
            Not enough IV-solved strikes to draw the smile.
          </div>
        ) : (
          <div className="h-64 w-full">
            <ResponsiveContainer>
              <ComposedChart data={points} margin={{ left: 10, right: 10, top: 10, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(120,120,120,0.2)" />
                <XAxis
                  dataKey="strike"
                  tick={{ fontSize: 10 }}
                  tickFormatter={(v) => v.toFixed(0)}
                  label={{ value: "Strike", position: "insideBottom", offset: -5, fontSize: 10 }}
                  type="number"
                  domain={["dataMin", "dataMax"]}
                />
                <YAxis
                  tick={{ fontSize: 10 }}
                  tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                  label={{ value: "IV", angle: -90, position: "insideLeft", fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12 }}
                  formatter={(v: number) => `${(v * 100).toFixed(1)}%`}
                  labelFormatter={(s: number) => `K = ${s.toFixed(2)}`}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {q.data?.spot != null && (
                  <ReferenceLine
                    x={q.data.spot}
                    stroke="rgba(245,158,11,0.7)"
                    strokeDasharray="3 3"
                    label={{ value: "spot", fontSize: 10, fill: "rgb(245,158,11)" }}
                  />
                )}
                <Line
                  type="monotone"
                  dataKey="call_iv"
                  name="Call IV"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="put_iv"
                  name="Put IV"
                  stroke="#ef4444"
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </section>
  );
}

function extractSmile(chain: OptionChain | undefined) {
  if (!chain) return [];
  const byStrike = new Map<number, { strike: number; call_iv: number | null; put_iv: number | null }>();
  for (const r of chain.rows) {
    const slot = byStrike.get(r.strike) ?? { strike: r.strike, call_iv: null, put_iv: null };
    if (r.right === "call") slot.call_iv = r.iv;
    else slot.put_iv = r.iv;
    byStrike.set(r.strike, slot);
  }
  return Array.from(byStrike.values())
    .filter((p) => p.call_iv != null || p.put_iv != null)
    .sort((a, b) => a.strike - b.strike);
}

// ---- IV vs RV panel ----

function IVPanel({
  symbol,
  brokerCode,
  expiry,
}: {
  symbol: string;
  brokerCode: string;
  expiry: string;
}) {
  const snap = useQuery({
    queryKey: ["iv-snapshot", symbol.trim().toUpperCase(), brokerCode.trim().toUpperCase(), expiry],
    queryFn: () => api.optionIVSnapshot(symbol.trim(), expiry, brokerCode.trim() || undefined),
    enabled: !!symbol.trim() && !!expiry,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  if (!symbol.trim() || !expiry) return null;

  const data = snap.data;
  const labelColor =
    data?.label === "rich"
      ? "text-bear-500"
      : data?.label === "cheap"
      ? "text-bull-500"
      : data?.label === "fair"
      ? "text-zinc-500"
      : "text-zinc-400";

  return (
    <section className="space-y-2">
      <div className="flex items-baseline gap-2">
        <h2 className="text-base font-bold">IV vs realised vol</h2>
        <span className="text-xs text-zinc-500">
          single highest-information options datapoint
        </span>
      </div>
      <div className="card p-4">
        {snap.isFetching && !data ? (
          <div className="text-sm text-zinc-500 flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : snap.error ? (
          <div className="text-sm text-bear-500">{(snap.error as Error).message}</div>
        ) : data ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat
              label="ATM IV"
              v={data.atm_iv != null ? data.atm_iv * 100 : null}
              suffix="%"
              subtitle={data.atm_strike != null ? `strike ₹${data.atm_strike}` : undefined}
              tone="neutral"
            />
            <Stat
              label="Realised vol (30d)"
              v={data.realized_vol_30d != null ? data.realized_vol_30d * 100 : null}
              suffix="%"
              subtitle="annualised"
              tone="neutral"
            />
            <Stat
              label="IV ÷ RV"
              v={data.iv_rv_ratio}
              subtitle={data.iv_rv_ratio != null ? "ratio" : "—"}
              tone="neutral"
            />
            <div className="rounded-md border border-zinc-200 dark:border-zinc-800 p-3">
              <div className="text-[11px] text-zinc-500 uppercase tracking-wider">
                Verdict
              </div>
              <div className={`text-lg font-semibold uppercase ${labelColor}`}>
                {data.label}
              </div>
              <div className="text-xs text-zinc-500 mt-0.5">
                {data.label === "rich" && "options pricing in more move than the stock has shown"}
                {data.label === "cheap" && "options pricing in less move than the stock has shown"}
                {data.label === "fair" && "implied and realised roughly in line"}
                {data.label === "n/a" && "not enough data"}
              </div>
            </div>
          </div>
        ) : null}
        {data && (
          <div className="text-[11px] text-zinc-400 mt-3 leading-relaxed">
            {data.note}
          </div>
        )}
      </div>
    </section>
  );
}

// ---- Covered calls ----

function CoveredCallsSection({
  symbol,
  brokerCode,
  expiry,
}: {
  symbol: string;
  brokerCode: string;
  expiry: string;
}) {
  const cc = useQuery({
    queryKey: ["covered-calls", symbol.trim().toUpperCase(), brokerCode.trim().toUpperCase(), expiry],
    queryFn: () => api.optionCoveredCalls(symbol.trim(), expiry, brokerCode.trim() || undefined),
    enabled: !!symbol.trim() && !!expiry,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  if (!symbol.trim() || !expiry) return null;

  return (
    <section className="space-y-2">
      <div className="flex items-baseline gap-2">
        <h2 className="text-base font-bold">Covered-call yield finder</h2>
        <span className="text-xs text-zinc-500">
          if you hold {symbol.toUpperCase()}: monthly premium per strike
        </span>
      </div>
      <div className="card overflow-x-auto">
        {cc.isFetching && !cc.data ? (
          <div className="p-4 text-sm text-zinc-500 flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : cc.error ? (
          <div className="p-4 text-sm text-bear-500">{(cc.error as Error).message}</div>
        ) : cc.data && cc.data.rows.length === 0 ? (
          <div className="p-4 text-sm text-zinc-500">
            No OTM calls within 15% of spot for this expiry.
          </div>
        ) : cc.data ? (
          <table className="w-full text-xs">
            <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 uppercase tracking-wider text-[10px]">
              <tr>
                <th className="text-right px-3 py-2">Strike</th>
                <th className="text-right px-3 py-2">vs spot</th>
                <th className="text-right px-3 py-2">Premium</th>
                <th className="text-right px-3 py-2">Yield</th>
                <th className="text-right px-3 py-2">Annualised</th>
                <th className="text-right px-3 py-2" title="Rough probability of being assigned at expiry">
                  Δ (assign %)
                </th>
                <th className="text-right px-3 py-2">IV</th>
                <th className="text-right px-3 py-2">OI</th>
              </tr>
            </thead>
            <tbody>
              {cc.data.rows.map((r) => (
                <tr
                  key={r.strike}
                  className="border-t border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-900/40"
                >
                  <td className="px-3 py-1.5 text-right font-mono font-semibold">{r.strike}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-500">
                    +{r.moneyness_pct.toFixed(1)}%
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums font-mono">{r.premium.toFixed(2)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums font-semibold text-bull-600">
                    {r.yield_pct.toFixed(2)}%
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-bull-500">
                    {r.annualized_pct.toFixed(0)}%
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {r.delta != null ? `${(r.delta * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-500">
                    {r.iv != null ? `${(r.iv * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-zinc-500">
                    {r.open_interest != null ? Math.round(r.open_interest).toLocaleString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {cc.data && (
          <div className="px-4 py-2 text-[11px] text-zinc-400 border-t border-zinc-200 dark:border-zinc-800">
            {cc.data.note}
          </div>
        )}
      </div>
    </section>
  );
}

function groupByStrike(rows: OptionRow[]) {
  const map = new Map<number, { strike: number; call?: OptionRow; put?: OptionRow }>();
  for (const r of rows) {
    const g = map.get(r.strike) ?? { strike: r.strike };
    if (r.right === "call") g.call = r;
    else g.put = r;
    map.set(r.strike, g);
  }
  return Array.from(map.values()).sort((a, b) => a.strike - b.strike);
}

function CallCell({
  row,
  field,
  align,
  pct,
}: {
  row: OptionRow | undefined;
  field: keyof OptionRow;
  align: "left" | "right";
  pct?: boolean;
}) {
  return (
    <td className={`px-2 py-1 font-mono text-${align}`}>
      {formatCell(row, field, pct)}
    </td>
  );
}
function PutCell({
  row,
  field,
  pct,
}: {
  row: OptionRow | undefined;
  field: keyof OptionRow;
  pct?: boolean;
}) {
  return <td className="px-2 py-1 font-mono text-left">{formatCell(row, field, pct)}</td>;
}

function formatCell(row: OptionRow | undefined, field: keyof OptionRow, pct?: boolean): string {
  if (!row) return "—";
  const v = row[field] as number | null;
  if (v == null) return "—";
  if (pct) return `${(v * 100).toFixed(1)}%`;
  if (field === "delta" || field === "gamma" || field === "theta" || field === "vega") {
    return v.toFixed(3);
  }
  if (field === "open_interest" || field === "volume") {
    return Math.round(v).toLocaleString();
  }
  return v.toFixed(2);
}

function BidAsk({ row }: { row: OptionRow | undefined }) {
  if (!row) return <>—</>;
  const b = row.bid != null ? row.bid.toFixed(2) : "—";
  const a = row.ask != null ? row.ask.toFixed(2) : "—";
  return <span className="font-mono text-[11px]">{b} / {a}</span>;
}

// ---- Payoff calculator ----

interface LegInput {
  id: number;
  qty: string;
  right: "call" | "put";
  strike: string;
  premium: string;
}

interface TemplateLegSpec {
  qty: number;
  right: "call" | "put";
  strikeOffset: number; // strike = spot + offset
  premium: number;
}

export interface TemplateLegs {
  name: string;
  legs: TemplateLegSpec[];
  spotHint?: number;
}

const TEMPLATES: { label: string; build: (spot: number) => TemplateLegs }[] = [
  {
    label: "Long call",
    build: (s) => ({ name: "Long call", legs: [{ qty: 1, right: "call", strikeOffset: 0, premium: 3 }] }),
  },
  {
    label: "Long put",
    build: (s) => ({ name: "Long put", legs: [{ qty: 1, right: "put", strikeOffset: 0, premium: 3 }] }),
  },
  {
    label: "Bull call spread",
    build: (s) => ({
      name: "Bull call spread",
      legs: [
        { qty: 1, right: "call", strikeOffset: 0, premium: 3 },
        { qty: -1, right: "call", strikeOffset: Math.max(1, s * 0.05), premium: 1.5 },
      ],
    }),
  },
  {
    label: "Bear put spread",
    build: (s) => ({
      name: "Bear put spread",
      legs: [
        { qty: 1, right: "put", strikeOffset: 0, premium: 3 },
        { qty: -1, right: "put", strikeOffset: -Math.max(1, s * 0.05), premium: 1.5 },
      ],
    }),
  },
  {
    label: "Long straddle",
    build: (s) => ({
      name: "Long straddle",
      legs: [
        { qty: 1, right: "call", strikeOffset: 0, premium: 3 },
        { qty: 1, right: "put", strikeOffset: 0, premium: 3 },
      ],
    }),
  },
  {
    label: "Long strangle",
    build: (s) => ({
      name: "Long strangle",
      legs: [
        { qty: 1, right: "call", strikeOffset: Math.max(1, s * 0.05), premium: 2 },
        { qty: 1, right: "put", strikeOffset: -Math.max(1, s * 0.05), premium: 2 },
      ],
    }),
  },
  {
    label: "Iron condor",
    build: (s) => ({
      name: "Iron condor",
      legs: [
        { qty: 1, right: "put", strikeOffset: -Math.max(2, s * 0.1), premium: 1 },
        { qty: -1, right: "put", strikeOffset: -Math.max(1, s * 0.05), premium: 2 },
        { qty: -1, right: "call", strikeOffset: Math.max(1, s * 0.05), premium: 2 },
        { qty: 1, right: "call", strikeOffset: Math.max(2, s * 0.1), premium: 1 },
      ],
    }),
  },
  {
    label: "Covered call",
    build: (s) => ({
      name: "Covered call (short call only — pair with held stock)",
      legs: [{ qty: -1, right: "call", strikeOffset: Math.max(1, s * 0.05), premium: 2 }],
    }),
  },
  {
    label: "Protective put",
    build: (s) => ({
      name: "Protective put (long put only — pair with held stock)",
      legs: [{ qty: 1, right: "put", strikeOffset: -Math.max(1, s * 0.05), premium: 3 }],
    }),
  },
];

let _nextId = 1;

function PayoffSection({
  initialLegs,
  onTemplate,
}: {
  initialLegs?: TemplateLegs | null;
  onTemplate?: (t: TemplateLegs | null) => void;
}) {
  const [spot, setSpot] = useState("100");
  const [lotSize, setLotSize] = useState("1");
  const [legs, setLegs] = useState<LegInput[]>([
    { id: _nextId++, qty: "1", right: "call", strike: "100", premium: "2.5" },
  ]);

  // T+0 overlay inputs. Off by default so the page stays "pure math at
  // expiry" until the user opts in.
  const [t0On, setT0On] = useState(false);
  const [daysToExpiry, setDaysToExpiry] = useState("30");
  const [ivPct, setIvPct] = useState("25");
  const [rPct, setRPct] = useState("7");

  // When a template is selected upstream, materialise it into the legs.
  useEffect(() => {
    if (!initialLegs) return;
    const s = parseFloat(spot) || 100;
    setLegs(
      initialLegs.legs.map((t) => ({
        id: _nextId++,
        qty: String(t.qty),
        right: t.right,
        strike: String(Math.round((s + t.strikeOffset) * 100) / 100),
        premium: String(t.premium),
      })),
    );
    // Clear so re-clicking the same template still fires.
    onTemplate?.(null);
  }, [initialLegs, spot, onTemplate]);

  const compute = useMutation({
    mutationFn: () => {
      const body = {
        spot: parseFloat(spot) || 0,
        lot_size: parseInt(lotSize) || 1,
        legs: legs.map<PayoffLeg>((l) => ({
          qty: parseInt(l.qty) || 0,
          right: l.right,
          strike: parseFloat(l.strike) || 0,
          premium: parseFloat(l.premium) || 0,
        })),
      };
      return api.optionPayoff(body);
    },
  });

  const addLeg = () =>
    setLegs((ls) => [
      ...ls,
      { id: _nextId++, qty: "1", right: "call", strike: spot, premium: "0" },
    ]);
  const removeLeg = (id: number) => setLegs((ls) => ls.filter((l) => l.id !== id));
  const updateLeg = (id: number, patch: Partial<LegInput>) =>
    setLegs((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)));

  return (
    <section className="space-y-3">
      <div className="flex items-baseline gap-2">
        <Calculator size={16} className="text-zinc-500" />
        <h2 className="text-base font-bold">Payoff calculator</h2>
        <span className="text-xs text-zinc-500 ml-auto">
          Piecewise payoff at expiry · no Black-Scholes extrapolation
        </span>
      </div>

      <div className="card p-4 space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Spot</label>
            <input
              className="input"
              type="number"
              step="any"
              value={spot}
              onChange={(e) => setSpot(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1 block">Lot size</label>
            <input
              className="input"
              type="number"
              value={lotSize}
              onChange={(e) => setLotSize(e.target.value)}
            />
          </div>
          <div className="col-span-2 md:col-span-3">
            <div className="flex items-center gap-2 mb-1">
              <label className="text-xs text-zinc-500 flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={t0On}
                  onChange={(e) => setT0On(e.target.checked)}
                  className="accent-blue-500"
                />
                T+0 overlay
              </label>
              <span className="text-[10px] text-zinc-400">
                Black-Scholes P/L now, alongside the at-expiry curve
              </span>
            </div>
            {t0On && (
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-[10px] text-zinc-500 mb-0.5 block">Days to expiry</label>
                  <input
                    className="input text-sm"
                    type="number"
                    min={0}
                    value={daysToExpiry}
                    onChange={(e) => setDaysToExpiry(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-[10px] text-zinc-500 mb-0.5 block">IV %</label>
                  <input
                    className="input text-sm"
                    type="number"
                    min={0}
                    step="any"
                    value={ivPct}
                    onChange={(e) => setIvPct(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-[10px] text-zinc-500 mb-0.5 block">Rate %</label>
                  <input
                    className="input text-sm"
                    type="number"
                    step="any"
                    value={rPct}
                    onChange={(e) => setRPct(e.target.value)}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center gap-2 mb-2">
            <Sparkles size={12} className="text-zinc-500" />
            <span className="text-[11px] text-zinc-500 uppercase tracking-wider">
              Strategy templates
            </span>
            <span className="text-[10px] text-zinc-400">
              click to fill legs · edit strikes/premiums after
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {TEMPLATES.map((t) => (
              <button
                key={t.label}
                type="button"
                className="pill text-[11px] bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                onClick={() => onTemplate?.(t.build(parseFloat(spot) || 100))}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          {legs.map((l) => (
            <div key={l.id} className="grid grid-cols-12 gap-2 items-end">
              <div className="col-span-2">
                <label className="text-[11px] text-zinc-500 mb-1 block">Qty (- = short)</label>
                <input
                  className="input"
                  type="number"
                  value={l.qty}
                  onChange={(e) => updateLeg(l.id, { qty: e.target.value })}
                />
              </div>
              <div className="col-span-2">
                <label className="text-[11px] text-zinc-500 mb-1 block">Side</label>
                <select
                  className="input"
                  value={l.right}
                  onChange={(e) => updateLeg(l.id, { right: e.target.value as "call" | "put" })}
                >
                  <option value="call">Call</option>
                  <option value="put">Put</option>
                </select>
              </div>
              <div className="col-span-3">
                <label className="text-[11px] text-zinc-500 mb-1 block">Strike</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  value={l.strike}
                  onChange={(e) => updateLeg(l.id, { strike: e.target.value })}
                />
              </div>
              <div className="col-span-3">
                <label className="text-[11px] text-zinc-500 mb-1 block">Premium / share</label>
                <input
                  className="input"
                  type="number"
                  step="any"
                  value={l.premium}
                  onChange={(e) => updateLeg(l.id, { premium: e.target.value })}
                />
              </div>
              <div className="col-span-2">
                <button
                  type="button"
                  className="btn-ghost text-bear-500"
                  onClick={() => removeLeg(l.id)}
                  disabled={legs.length === 1}
                  aria-label="Remove leg"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button type="button" className="btn-ghost text-xs" onClick={addLeg}>
            <Plus size={14} /> Add leg
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => compute.mutate()}
            disabled={compute.isPending}
          >
            {compute.isPending ? "Computing…" : "Compute payoff"}
          </button>
        </div>

        {compute.error && (
          <div className="text-sm text-bear-500">{(compute.error as Error).message}</div>
        )}

        {compute.data && (
          <PayoffResult
            data={compute.data}
            spot={parseFloat(spot) || 0}
            t0Curve={
              t0On
                ? computeT0Curve({
                    curveXs: compute.data.curve.map((p) => p.s),
                    legs: legs,
                    lotSize: parseInt(lotSize) || 1,
                    costBasis: compute.data.cost_basis,
                    days: parseFloat(daysToExpiry) || 0,
                    ivDecimal: (parseFloat(ivPct) || 0) / 100,
                    rDecimal: (parseFloat(rPct) || 0) / 100,
                  })
                : undefined
            }
          />
        )}
      </div>
    </section>
  );
}

function PayoffResult({
  data,
  spot,
  t0Curve,
}: {
  data: import("../types").PayoffOut;
  spot: number;
  t0Curve?: { s: number; pnl_now: number }[];
}) {
  // Merge expiry + T+0 curves on the same x-axis when overlay is on.
  const merged = useMemo(() => {
    if (!t0Curve) return data.curve.map((p) => ({ s: p.s, pnl: p.pnl, pnl_now: null }));
    const t0Map = new Map(t0Curve.map((p) => [p.s, p.pnl_now]));
    return data.curve.map((p) => ({
      s: p.s,
      pnl: p.pnl,
      pnl_now: t0Map.get(p.s) ?? null,
    }));
  }, [data.curve, t0Curve]);

  return (
    <div className="space-y-3 pt-3 border-t border-zinc-200 dark:border-zinc-800">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <Stat
          label="Max gain (expiry)"
          v={data.max_gain}
          tone={data.max_gain > 0 ? "bull" : "neutral"}
        />
        <Stat
          label="Max loss (expiry)"
          v={data.max_loss}
          tone={data.max_loss < 0 ? "bear" : "neutral"}
        />
        <Stat
          label="Cost basis"
          v={data.cost_basis}
          subtitle={data.cost_basis > 0 ? "debit" : data.cost_basis < 0 ? "credit" : ""}
          tone="neutral"
        />
        <Stat
          label="Break-even(s)"
          v={null}
          subtitle={data.break_evens.length ? data.break_evens.map((b) => b.toFixed(2)).join(", ") : "—"}
          tone="neutral"
        />
      </div>

      <div className="h-72 w-full">
        <ResponsiveContainer>
          <LineChart data={merged} margin={{ left: 10, right: 10, top: 10, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(120,120,120,0.2)" />
            <XAxis
              dataKey="s"
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => v.toFixed(0)}
              label={{ value: "Underlying", position: "insideBottom", offset: -5, fontSize: 11 }}
            />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{ fontSize: 12 }}
              formatter={(v: number) => v.toFixed(2)}
              labelFormatter={(s: number) => `S = ${s.toFixed(2)}`}
            />
            {t0Curve && <Legend wrapperStyle={{ fontSize: 11 }} />}
            <ReferenceLine y={0} stroke="rgba(120,120,120,0.6)" />
            {spot > 0 && (
              <ReferenceLine
                x={spot}
                stroke="rgba(245,158,11,0.6)"
                strokeDasharray="3 3"
                label={{ value: "spot", fontSize: 10, fill: "rgb(245,158,11)" }}
              />
            )}
            {data.break_evens.map((b, i) => (
              <ReferenceLine
                key={`be-${i}`}
                x={b}
                stroke="rgba(120,120,120,0.4)"
                strokeDasharray="2 2"
              />
            ))}
            <Line
              type="monotone"
              dataKey="pnl"
              name="At expiry"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
            />
            {t0Curve && (
              <Line
                type="monotone"
                dataKey="pnl_now"
                name="Today (Black-Scholes)"
                stroke="#f59e0b"
                strokeWidth={2}
                strokeDasharray="4 2"
                dot={false}
                connectNulls
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function computeT0Curve({
  curveXs,
  legs,
  lotSize,
  costBasis,
  days,
  ivDecimal,
  rDecimal,
}: {
  curveXs: number[];
  legs: LegInput[];
  lotSize: number;
  costBasis: number;
  days: number;
  ivDecimal: number;
  rDecimal: number;
}): { s: number; pnl_now: number }[] {
  if (days <= 0 || ivDecimal <= 0) {
    // At T=0 the T+0 curve equals the at-expiry curve — return identity.
    // bsPrice handles this fallback, but skip the work.
    return [];
  }
  const T = days / 365;
  const parsedLegs = legs
    .map((l) => ({
      qty: parseInt(l.qty) || 0,
      right: l.right,
      strike: parseFloat(l.strike) || 0,
    }))
    .filter((l) => l.qty !== 0 && l.strike > 0);

  return curveXs.map((S) => {
    let value = 0;
    for (const leg of parsedLegs) {
      value += leg.qty * bsPrice(S, leg.strike, T, rDecimal, ivDecimal, leg.right);
    }
    const valueScaled = value * lotSize;
    return { s: S, pnl_now: Math.round((valueScaled - costBasis) * 100) / 100 };
  });
}

function Stat({
  label,
  v,
  subtitle,
  tone,
  suffix,
}: {
  label: string;
  v: number | null;
  subtitle?: string;
  tone: "bull" | "bear" | "neutral";
  suffix?: string;
}) {
  const cls =
    tone === "bull"
      ? "text-bull-500"
      : tone === "bear"
      ? "text-bear-500"
      : "text-zinc-700 dark:text-zinc-300";
  return (
    <div className="rounded-md border border-zinc-200 dark:border-zinc-800 p-3">
      <div className="text-[11px] text-zinc-500 uppercase tracking-wider">{label}</div>
      {v != null && (
        <div className={`text-lg font-mono font-semibold ${cls}`}>
          {v.toFixed(2)}
          {suffix && <span className="text-xs text-zinc-500 ml-0.5">{suffix}</span>}
        </div>
      )}
      {subtitle && <div className="text-xs text-zinc-500 mt-0.5">{subtitle}</div>}
    </div>
  );
}
