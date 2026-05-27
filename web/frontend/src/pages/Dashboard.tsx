import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { DigestModal } from "../components/DigestModal";
import { EmptyState } from "../components/EmptyState";
import { FilterBar, type FilterState } from "../components/FilterBar";
import { HoldingsTable, makeRowSorter } from "../components/HoldingsTable";
import { KPIStrip, type LiveBucket } from "../components/KPIStrip";
import type { CardRow, LiveQuote } from "../types";

interface Props {
  onLoadedAt: (s: string) => void;
}

export function Dashboard({ onLoadedAt }: Props) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.getDashboard(),
  });

  // Live quote overlay. We start polling at 30s and only keep polling if
  // the server reports any market open. When the holdings list is empty,
  // skip the call entirely.
  const live = useQuery({
    queryKey: ["live-quotes"],
    queryFn: api.liveQuotes,
    enabled: !!q.data && (q.data.rows?.length ?? 0) > 0,
    refetchInterval: (query) =>
      query.state.data?.any_market_open ? 30_000 : false,
    refetchOnWindowFocus: true,
    refetchIntervalInBackground: false,
    staleTime: 15_000,
  });

  const liveByKey = useMemo<Record<string, LiveQuote | undefined>>(() => {
    const map: Record<string, LiveQuote | undefined> = {};
    for (const q of live.data?.quotes ?? []) {
      map[`${q.symbol}.${q.market}`] = q;
    }
    return map;
  }, [live.data]);

  const [openDigest, setOpenDigest] = useState<{ symbol: string; market: string } | null>(null);
  const [filters, setFilters] = useState<FilterState>({
    search: "",
    signals: [],
    markets: [],
    position: "all",
    sort: { col: "signal", dir: "asc" }, // bearish first by default
  });

  // Push the load time up to the TopBar.
  if (q.data?.loaded_at) {
    queueMicrotask(() => onLoadedAt(q.data!.loaded_at));
  }

  const rows = q.data?.rows ?? [];

  // Recompute per-currency buckets from rows + live overlay. This is what
  // makes the portfolio-value tile actually move when prices update.
  const liveBuckets = useMemo<LiveBucket[]>(
    () => computeLiveBuckets(rows, liveByKey),
    [rows, liveByKey],
  );

  const filtered = useMemo(() => {
    let xs = rows.slice();
    if (filters.signals.length) {
      xs = xs.filter((r) => r.score_label && filters.signals.includes(r.score_label));
    }
    if (filters.markets.length) {
      xs = xs.filter((r) => filters.markets.includes(r.market));
    }
    if (filters.position === "overweight") xs = xs.filter((r) => r.overweight);
    if (filters.position === "winners")
      xs = xs.filter((r) => r.pnl != null && r.pnl > 0);
    if (filters.position === "losers")
      xs = xs.filter((r) => r.pnl != null && r.pnl < 0);
    if (filters.search) xs = xs.filter((r) => r.symbol.includes(filters.search));
    xs.sort(makeRowSorter(filters.sort, liveByKey));
    return xs;
  }, [rows, filters, liveByKey]);

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 text-zinc-500 py-12 justify-center">
        <Loader2 className="animate-spin" size={16} /> Loading portfolio…
      </div>
    );
  }
  if (q.error) {
    const msg = (q.error as Error).message;
    const [head, ...rest] = msg.split("\n");
    return (
      <EmptyState title="Could not load portfolio">
        <div>{head}</div>
        {rest.length > 0 && (
          <pre className="mt-2 text-xs bg-zinc-100 dark:bg-zinc-800 rounded px-3 py-2 inline-block text-left whitespace-pre-wrap">
            {rest.join("\n")}
          </pre>
        )}
      </EmptyState>
    );
  }
  if (!q.data || rows.length === 0) {
    return (
      <EmptyState title="No holdings yet">
        Use the <strong>Portfolio</strong> tab to import a CSV or add holdings,
        or try <strong>Lookup</strong> to analyse any ticker.
      </EmptyState>
    );
  }

  return (
    <div className="space-y-4 pb-12">
      <KPIStrip
        buckets={liveBuckets}
        signalCounts={q.data.signal_counts}
        overweight={q.data.overweight_count}
        isLive={!!live.data?.any_market_open && Object.keys(liveByKey).length > 0}
      />

      <FilterBar
        state={filters}
        onChange={setFilters}
        total={rows.length}
        shown={filtered.length}
      />

      {filtered.length === 0 ? (
        <EmptyState title="No holdings match the filters">
          Clear or adjust the filters above.
        </EmptyState>
      ) : (
        <HoldingsTable
          rows={filtered}
          liveByKey={liveByKey}
          onOpenDigest={(row) => setOpenDigest({ symbol: row.symbol, market: row.market })}
          sort={filters.sort}
          onSort={(s) => setFilters({ ...filters, sort: s })}
        />
      )}

      {live.data?.any_market_open && (
        <div className="text-[11px] text-zinc-400 text-right">
          live quotes · refreshing every 30s
          {live.isFetching && (
            <Loader2 size={10} className="inline ml-1 animate-spin" />
          )}
        </div>
      )}

      {openDigest && (
        <DigestModal
          symbol={openDigest.symbol}
          market={openDigest.market}
          onClose={() => {
            setOpenDigest(null);
            qc.invalidateQueries({ queryKey: ["digest"] });
          }}
        />
      )}
    </div>
  );
}

interface BucketAcc {
  currency: string;
  currency_symbol: string;
  market_value: number;
  cost_total: number;
  pnl: number;
  today_pnl: number;
  n_positions: number;
  _hasToday: boolean;
}

function computeLiveBuckets(
  rows: CardRow[],
  liveByKey: Record<string, LiveQuote | undefined>,
): LiveBucket[] {
  const byCurrency = new Map<string, BucketAcc>();
  for (const r of rows) {
    if (!r.shares || r.shares <= 0 || r.cost_basis == null) continue;
    const live = liveByKey[`${r.symbol}.${r.market}`];
    const price = live?.price ?? r.price ?? 0;
    if (!price) continue;
    const market_value = price * r.shares;
    const cost_total = r.cost_basis * r.shares;
    const pnl = market_value - cost_total;
    // "Today" only when we actually have a live quote with a change.
    const today_pnl = live && live.change != null ? live.change * r.shares : 0;
    const has_today = live != null && live.change != null;

    const bucket: BucketAcc = byCurrency.get(r.currency) ?? {
      currency: r.currency,
      currency_symbol: r.currency_symbol,
      market_value: 0,
      cost_total: 0,
      pnl: 0,
      today_pnl: 0,
      n_positions: 0,
      _hasToday: false,
    };
    bucket.market_value += market_value;
    bucket.cost_total += cost_total;
    bucket.pnl += pnl;
    bucket.today_pnl += today_pnl;
    bucket.n_positions += 1;
    bucket._hasToday = bucket._hasToday || has_today;
    byCurrency.set(r.currency, bucket);
  }

  const out: LiveBucket[] = [];
  for (const b of byCurrency.values()) {
    const pnl_pct = b.cost_total > 0 ? (b.pnl / b.cost_total) * 100 : 0;
    // today_pnl_pct = today_pnl / yesterday_value, where yesterday_value ≈ today's value - today_pnl
    const denom = b.market_value - b.today_pnl;
    const today_pnl_pct = b._hasToday && denom > 0 ? (b.today_pnl / denom) * 100 : 0;
    out.push({
      currency: b.currency,
      currency_symbol: b.currency_symbol,
      market_value: b.market_value,
      cost_total: b.cost_total,
      pnl: b.pnl,
      pnl_pct,
      today_pnl: b._hasToday ? b.today_pnl : null,
      today_pnl_pct: b._hasToday ? today_pnl_pct : null,
      n_positions: b.n_positions,
    });
  }
  return out;
}
