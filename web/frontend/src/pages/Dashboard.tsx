import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { DigestModal } from "../components/DigestModal";
import { EmptyState } from "../components/EmptyState";
import { FilterBar, type FilterState, type SortKey } from "../components/FilterBar";
import { HoldingsTable } from "../components/HoldingsTable";
import { KPIStrip } from "../components/KPIStrip";
import { signalRank } from "../lib/format";
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
    sort: "signal-sell",
  });

  // Push the load time up to the TopBar.
  if (q.data?.loaded_at) {
    queueMicrotask(() => onLoadedAt(q.data!.loaded_at));
  }

  const rows = q.data?.rows ?? [];

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
    xs.sort(makeSorter(filters.sort));
    return xs;
  }, [rows, filters]);

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
        buckets={q.data.buckets}
        signalCounts={q.data.signal_counts}
        overweight={q.data.overweight_count}
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

function makeSorter(key: SortKey) {
  return (a: CardRow, b: CardRow): number => {
    switch (key) {
      case "signal-sell":
        return signalRank(a.score_label) - signalRank(b.score_label);
      case "signal-buy":
        return signalRank(b.score_label) - signalRank(a.score_label);
      case "ticker":
        return a.symbol.localeCompare(b.symbol);
      case "weight-desc":
        return (b.weight_pct ?? 0) - (a.weight_pct ?? 0);
      case "pnl-worst":
        return (a.pnl_pct ?? 0) - (b.pnl_pct ?? 0);
      case "pnl-best":
        return (b.pnl_pct ?? 0) - (a.pnl_pct ?? 0);
    }
  };
}
