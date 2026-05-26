import { AlertTriangle, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { DigestModal } from "../components/DigestModal";
import { EmptyState } from "../components/EmptyState";
import { FilterBar, type FilterState, type SortKey } from "../components/FilterBar";
import { KPITiles } from "../components/KPITiles";
import { StockCard } from "../components/StockCard";
import { signalRank } from "../lib/format";
import type { CardRow, SignalLabel } from "../types";

const SELL_SIGNALS = new Set<SignalLabel>(["Strong Sell", "Sell"]);

interface Props {
  onLoadedAt: (s: string) => void;
}

export function Dashboard({ onLoadedAt }: Props) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.getDashboard(),
  });

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

  const attention = useMemo(() => {
    const out: CardRow[] = [];
    const seen = new Set<string>();
    const k = (r: CardRow) => `${r.symbol}.${r.market}`;
    for (const r of rows) {
      if (r.error) continue;
      if (r.score_label && SELL_SIGNALS.has(r.score_label) && !seen.has(k(r))) {
        seen.add(k(r));
        out.push(r);
      }
    }
    for (const r of rows) {
      if (r.error) continue;
      if (r.overweight && !seen.has(k(r))) {
        seen.add(k(r));
        out.push(r);
      }
    }
    return out.slice(0, 6);
  }, [rows]);

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
    return (
      <EmptyState title="Could not load portfolio">
        {(q.error as Error).message}
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
    <div className="space-y-6 pb-12">
      <KPITiles
        buckets={q.data.buckets}
        signalCounts={q.data.signal_counts}
        overweight={q.data.overweight_count}
        winners={q.data.winners_count}
        losers={q.data.losers_count}
      />

      {attention.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-bold flex items-center gap-2">
              <AlertTriangle size={16} className="text-bear-500" />
              Needs attention
            </h2>
            <span className="text-xs text-zinc-500">
              {attention.length} holding{attention.length !== 1 && "s"} — sells &amp; overweight first
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {attention.map((r) => (
              <StockCard
                key={`attn-${r.symbol}-${r.market}`}
                row={r}
                attention
                onOpenDigest={(row) => setOpenDigest({ symbol: row.symbol, market: row.market })}
              />
            ))}
          </div>
        </section>
      )}

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-bold">All holdings</h2>
          <span className="text-xs text-zinc-500">filters apply instantly · no refetch</span>
        </div>
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
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {filtered.map((r) => (
              <StockCard
                key={`grid-${r.symbol}-${r.market}`}
                row={r}
                onOpenDigest={(row) => setOpenDigest({ symbol: row.symbol, market: row.market })}
              />
            ))}
          </div>
        )}
      </section>

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
