import clsx from "clsx";
import { ArrowDown, ArrowUp, Circle } from "lucide-react";
import type { SignalLabel } from "../types";
import { SIGNAL_ORDER, SIGNAL_STYLES, fmtCurrency, fmtPct } from "../lib/format";
import { LastRefreshed } from "./LastRefreshed";

/**
 * Bucket shape used by the home page strip. Differs from the server's
 * CurrencyBucket by adding `today_pnl` (computed client-side from the
 * live-quote overlay) and making it nullable when no live data exists.
 */
export interface LiveBucket {
  currency: string;
  currency_symbol: string;
  market_value: number;
  cost_total: number;
  pnl: number;
  pnl_pct: number;
  today_pnl: number | null;
  today_pnl_pct: number | null;
  n_positions: number;
  // How many of n_positions actually contributed to today_pnl (had
  // either a live quote with previous_close, or a cached change_pct).
  n_today_covered: number;
}

interface Props {
  buckets: LiveBucket[];
  signalCounts: Record<string, number>;
  overweight: number;
  isLive: boolean;
  liveAsOf?: string;
}

export function KPIStrip({ buckets, signalCounts, overweight, isLive, liveAsOf }: Props) {
  return (
    <div className="card px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
      {buckets.map((b) => {
        const up = b.pnl > 0;
        const flat = b.pnl === 0;
        const todayUp = b.today_pnl != null && b.today_pnl > 0;
        const todayFlat = b.today_pnl == null || b.today_pnl === 0;
        return (
          <div key={b.currency} className="flex items-baseline gap-2">
            <span className="text-zinc-500 text-xs uppercase tracking-wider">
              {b.currency_symbol}
            </span>
            <span className="font-semibold tabular-nums">
              {fmtCurrency(b.market_value, b.currency_symbol, 0)}
            </span>
            {!flat && (
              <span
                className={clsx(
                  "flex items-center gap-0.5 text-xs font-medium tabular-nums",
                  up ? "text-bull-500" : "text-bear-500",
                )}
                title="Total unrealised P/L"
              >
                {up ? <ArrowUp size={11} strokeWidth={3} /> : <ArrowDown size={11} strokeWidth={3} />}
                {fmtPct(b.pnl_pct)}
              </span>
            )}
            {b.today_pnl != null && (
              <span
                className={clsx(
                  "flex items-center gap-0.5 text-xs tabular-nums px-1.5 py-0.5 rounded",
                  todayFlat
                    ? "bg-zinc-100 dark:bg-zinc-800 text-zinc-500"
                    : todayUp
                    ? "bg-bull-50 text-bull-600 dark:bg-bull-900/30 dark:text-bull-300"
                    : "bg-bear-50 text-bear-600 dark:bg-bear-900/30 dark:text-bear-300",
                )}
                title={
                  b.n_today_covered < b.n_positions
                    ? `Today's P/L from ${b.n_today_covered}/${b.n_positions} positions (others missing price/prev-close data)`
                    : "Today's P/L since previous close (all positions covered)"
                }
              >
                today {todayUp ? "+" : ""}
                {fmtCurrency(b.today_pnl, b.currency_symbol, 0)}
                {b.today_pnl_pct != null && (
                  <span className="opacity-70">
                    {" "}({fmtPct(b.today_pnl_pct)})
                  </span>
                )}
                {b.n_today_covered < b.n_positions && (
                  <span className="opacity-60 ml-0.5">
                    · {b.n_today_covered}/{b.n_positions}
                  </span>
                )}
              </span>
            )}
            <span className="text-zinc-400 text-xs">· {b.n_positions} pos</span>
          </div>
        );
      })}

      <div className="flex items-center gap-1.5">
        {SIGNAL_ORDER.filter((s) => (signalCounts[s] ?? 0) > 0).map((s) => (
          <span
            key={s}
            title={s}
            className={clsx(
              "pill text-[10px]",
              SIGNAL_STYLES[s as SignalLabel].bg,
              SIGNAL_STYLES[s as SignalLabel].fg,
            )}
          >
            <span aria-hidden>{SIGNAL_STYLES[s as SignalLabel].glyph}</span>
            <span>{signalCounts[s]}</span>
          </span>
        ))}
      </div>

      {overweight > 0 && (
        <div className="text-xs text-amber-700 dark:text-amber-400">
          {overweight} overweight
        </div>
      )}

      {isLive && (
        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-1 text-[11px] text-bull-500">
            <Circle size={6} fill="currentColor" strokeWidth={0} />
            <span>live</span>
          </div>
          <LastRefreshed at={liveAsOf} label="quote" compact />
        </div>
      )}
    </div>
  );
}
