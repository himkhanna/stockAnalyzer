import clsx from "clsx";
import { ArrowDown, ArrowUp } from "lucide-react";
import type { CurrencyBucket, SignalLabel } from "../types";
import { SIGNAL_ORDER, SIGNAL_STYLES, fmtCurrency, fmtPct } from "../lib/format";

interface Props {
  buckets: CurrencyBucket[];
  signalCounts: Record<string, number>;
  overweight: number;
}

/**
 * One-line summary that replaces the old grid of KPI tiles. Keeps the
 * same information dense in a single horizontal strip so the holdings
 * list is the first thing you actually see.
 */
export function KPIStrip({ buckets, signalCounts, overweight }: Props) {
  return (
    <div className="card px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
      {buckets.map((b) => {
        const up = b.pnl > 0;
        const flat = b.pnl === 0;
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
              >
                {up ? <ArrowUp size={11} strokeWidth={3} /> : <ArrowDown size={11} strokeWidth={3} />}
                {fmtPct(b.pnl_pct)}
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
    </div>
  );
}
