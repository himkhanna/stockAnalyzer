import clsx from "clsx";
import { Search, X } from "lucide-react";
import { SIGNAL_ORDER, SIGNAL_STYLES } from "../lib/format";
import type { SignalLabel } from "../types";

export type PositionFilter = "all" | "overweight" | "winners" | "losers";
export type SortKey =
  | "signal-sell"
  | "signal-buy"
  | "ticker"
  | "weight-desc"
  | "pnl-worst"
  | "pnl-best";

export interface FilterState {
  search: string;
  signals: SignalLabel[];
  markets: string[];
  position: PositionFilter;
  sort: SortKey;
}

interface Props {
  state: FilterState;
  onChange: (next: FilterState) => void;
  total: number;
  shown: number;
}

const MARKETS = ["US", "NSE", "BSE", "DFM", "ADX"];

export function FilterBar({ state, onChange, total, shown }: Props) {
  const toggleSignal = (s: SignalLabel) =>
    onChange({
      ...state,
      signals: state.signals.includes(s)
        ? state.signals.filter((x) => x !== s)
        : [...state.signals, s],
    });
  const toggleMarket = (m: string) =>
    onChange({
      ...state,
      markets: state.markets.includes(m)
        ? state.markets.filter((x) => x !== m)
        : [...state.markets, m],
    });
  const hasFilters =
    state.search ||
    state.signals.length ||
    state.markets.length ||
    state.position !== "all";

  return (
    <div className="card p-3 flex flex-col gap-3 animate-fade-in">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400"
          />
          <input
            className="input pl-9"
            placeholder="Search ticker…"
            value={state.search}
            onChange={(e) =>
              onChange({ ...state, search: e.target.value.toUpperCase() })
            }
          />
        </div>

        <select
          className="input w-auto"
          value={state.position}
          onChange={(e) =>
            onChange({ ...state, position: e.target.value as PositionFilter })
          }
        >
          <option value="all">All positions</option>
          <option value="overweight">Overweight only</option>
          <option value="winners">Winners</option>
          <option value="losers">Losers</option>
        </select>

        <select
          className="input w-auto"
          value={state.sort}
          onChange={(e) =>
            onChange({ ...state, sort: e.target.value as SortKey })
          }
        >
          <option value="signal-sell">Sort: Sell first</option>
          <option value="signal-buy">Sort: Buy first</option>
          <option value="ticker">Sort: Ticker A→Z</option>
          <option value="weight-desc">Sort: Weight (largest)</option>
          <option value="pnl-worst">Sort: P&L % (worst)</option>
          <option value="pnl-best">Sort: P&L % (best)</option>
        </select>

        <div className="ml-auto text-xs text-zinc-500">
          {shown} / {total}
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {SIGNAL_ORDER.map((s) => {
          const active = state.signals.includes(s);
          const style = SIGNAL_STYLES[s];
          return (
            <button
              key={s}
              onClick={() => toggleSignal(s)}
              className={clsx(
                "pill text-[11px] cursor-pointer transition-all",
                active
                  ? clsx(style.bg, style.fg, "ring-2 ring-offset-1", style.ring)
                  : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700",
              )}
            >
              <span aria-hidden>{style.glyph}</span> {s}
            </button>
          );
        })}
        <div className="w-px self-stretch bg-zinc-200 dark:bg-zinc-700 mx-1" />
        {MARKETS.map((m) => {
          const active = state.markets.includes(m);
          return (
            <button
              key={m}
              onClick={() => toggleMarket(m)}
              className={clsx(
                "pill text-[11px] cursor-pointer transition-all",
                active
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700",
              )}
            >
              {m}
            </button>
          );
        })}
        {hasFilters && (
          <button
            onClick={() =>
              onChange({
                search: "",
                signals: [],
                markets: [],
                position: "all",
                sort: state.sort,
              })
            }
            className="pill text-[11px] bg-zinc-100 dark:bg-zinc-800 text-zinc-500 hover:bg-zinc-200 dark:hover:bg-zinc-700 cursor-pointer"
          >
            <X size={11} /> Clear
          </button>
        )}
      </div>
    </div>
  );
}
