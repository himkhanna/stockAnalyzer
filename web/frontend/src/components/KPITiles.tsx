import clsx from "clsx";
import { ArrowDown, ArrowUp, TrendingDown, TrendingUp } from "lucide-react";
import type { CurrencyBucket, SignalLabel } from "../types";
import { SIGNAL_STYLES, fmtCurrency, fmtPct, SIGNAL_ORDER } from "../lib/format";
import { SignalPill } from "./SignalPill";

interface Props {
  buckets: CurrencyBucket[];
  signalCounts: Record<string, number>;
  overweight: number;
  winners: number;
  losers: number;
}

export function KPITiles({ buckets, signalCounts, overweight, winners, losers }: Props) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
      {buckets.map((b) => (
        <BucketTile key={b.currency} b={b} />
      ))}
      <SignalsTile counts={signalCounts} />
      <PositionsTile overweight={overweight} winners={winners} losers={losers} />
    </div>
  );
}

function BucketTile({ b }: { b: CurrencyBucket }) {
  const up = b.pnl > 0;
  const flat = b.pnl === 0;
  return (
    <div className="card p-4 animate-fade-in">
      <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold">
        {b.currency_symbol} portfolio
      </div>
      <div className="mt-1 text-2xl font-bold tracking-tight">
        {fmtCurrency(b.market_value, b.currency_symbol, 0)}
      </div>
      <div
        className={clsx(
          "mt-0.5 flex items-center gap-1 text-sm font-semibold",
          flat ? "text-zinc-500" : up ? "text-bull-500" : "text-bear-500",
        )}
      >
        {!flat &&
          (up ? <ArrowUp size={14} strokeWidth={2.5} /> : <ArrowDown size={14} strokeWidth={2.5} />)}
        <span>
          {fmtCurrency(Math.abs(b.pnl), b.currency_symbol, 0)} ({fmtPct(b.pnl_pct)})
        </span>
      </div>
      <div className="mt-1 text-xs text-zinc-500">
        {b.n_positions} positions · cost {fmtCurrency(b.cost_total, b.currency_symbol, 0)}
      </div>
    </div>
  );
}

function SignalsTile({ counts }: { counts: Record<string, number> }) {
  const pills = SIGNAL_ORDER.filter((s) => (counts[s] ?? 0) > 0);
  return (
    <div className="card p-4 animate-fade-in">
      <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold">
        signals
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {pills.length ? (
          pills.map((s) => (
            <span
              key={s}
              className={clsx(
                "pill text-[11px]",
                SIGNAL_STYLES[s as SignalLabel].bg,
                SIGNAL_STYLES[s as SignalLabel].fg,
              )}
            >
              <span aria-hidden>{SIGNAL_STYLES[s as SignalLabel].glyph}</span>
              <span>{counts[s]}</span>
            </span>
          ))
        ) : (
          <span className="text-xs text-zinc-500">no signals</span>
        )}
      </div>
      <div className="mt-2 text-xs text-zinc-500">across all holdings</div>
    </div>
  );
}

function PositionsTile({
  overweight,
  winners,
  losers,
}: {
  overweight: number;
  winners: number;
  losers: number;
}) {
  return (
    <div className="card p-4 animate-fade-in">
      <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold">
        positions
      </div>
      <div className="mt-2 flex items-center gap-3 text-sm font-semibold">
        <span className="flex items-center gap-1 text-bull-500">
          <TrendingUp size={14} strokeWidth={2.5} /> {winners} winners
        </span>
        <span className="flex items-center gap-1 text-bear-500">
          <TrendingDown size={14} strokeWidth={2.5} /> {losers} losers
        </span>
      </div>
      <div className="mt-2 text-xs text-zinc-500">
        {overweight} overweight (&gt;15%)
      </div>
    </div>
  );
}
