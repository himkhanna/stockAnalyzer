import clsx from "clsx";
import { ArrowDown, ArrowUp, FileText, Loader2 } from "lucide-react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { SIGNAL_STYLES, fmtCurrency, fmtPct } from "../lib/format";
import type { CardRow } from "../types";
import { SignalPill } from "./SignalPill";
import { Sparkline } from "./Sparkline";

interface Props {
  row: CardRow;
  attention?: boolean;
  onOpenDigest?: (row: CardRow) => void;
}

export function StockCard({ row, attention = false, onOpenDigest }: Props) {
  const qc = useQueryClient();
  const [genErr, setGenErr] = useState<string | null>(null);
  const generate = useMutation({
    mutationFn: () => api.generateDigest(row.symbol, row.market),
    onSuccess: () => {
      setGenErr(null);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      onOpenDigest?.(row);
    },
    onError: (e: Error) => setGenErr(e.message),
  });

  if (row.error) {
    return (
      <div className="card card-hover p-4 animate-fade-in">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold">{row.symbol}</span>
          <span className="text-xs text-zinc-500 uppercase">{row.market}</span>
        </div>
        <div className="mt-2 text-sm text-bear-600">{row.error}</div>
      </div>
    );
  }

  const sym = row.currency_symbol;
  const chg = row.change_pct ?? 0;
  const chgColor =
    chg > 0 ? "text-bull-500" : chg < 0 ? "text-bear-500" : "text-zinc-500";
  const ChgIcon = chg > 0 ? ArrowUp : ArrowDown;
  const lineColor = row.score_label
    ? SIGNAL_STYLES[row.score_label].line
    : "#737373";

  return (
    <div
      className={clsx(
        "card card-hover p-4 flex flex-col gap-2 animate-fade-in min-h-[200px]",
        attention && "border-l-4 border-l-bear-500",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="font-bold text-base truncate">{row.symbol}</span>
          <span className="text-[11px] text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
            {row.market}
          </span>
        </div>
        <SignalPill label={row.score_label} score={row.score_value} />
      </div>

      <div className="flex items-end justify-between gap-2">
        <div className="text-2xl font-semibold tracking-tight">
          {fmtCurrency(row.price, sym)}
        </div>
        {row.change_pct != null && (
          <div className={clsx("flex items-center gap-0.5 text-sm font-medium", chgColor)}>
            <ChgIcon size={14} strokeWidth={2.5} />
            <span>{fmtPct(row.change_pct)}</span>
          </div>
        )}
      </div>

      <Sparkline closes={row.recent_closes} color={lineColor} height={36} />

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-600 dark:text-zinc-400">
        {row.rsi != null && <span>RSI {row.rsi.toFixed(0)}</span>}
        {row.trend && <span className="text-zinc-400">·</span>}
        {row.trend && <span>{row.trend}</span>}
        <span className="text-zinc-400">·</span>
        <span>
          news {row.sentiment_total} ({row.sentiment_label ?? "—"})
        </span>
        {row.stale && (
          <span className="tag bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
            stale
          </span>
        )}
        {row.overweight && (
          <span className="tag bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
            overweight
          </span>
        )}
        {row.pnl_pct != null && row.pnl_pct < -10 && (
          <span className="tag bg-bear-50 text-bear-600 dark:bg-bear-900/40 dark:text-bear-300">
            −10%+
          </span>
        )}
      </div>

      {row.shares != null && row.cost_basis != null && row.pnl != null && (
        <div className="pt-2 border-t border-dashed border-zinc-200 dark:border-zinc-800 text-xs">
          <div className="text-zinc-600 dark:text-zinc-400">
            {row.shares}{" sh @ "}
            {fmtCurrency(row.cost_basis, sym)}{" → "}
            <span
              className={clsx(
                "font-semibold",
                row.pnl >= 0 ? "text-bull-500" : "text-bear-500",
              )}
            >
              {fmtCurrency(row.pnl, sym)} ({fmtPct(row.pnl_pct)})
            </span>
            {row.weight_pct != null && (
              <>
                {" · "}
                <span className="font-semibold">
                  {row.weight_pct.toFixed(1)}%
                </span>{" "}
                of {row.currency}
              </>
            )}
          </div>
        </div>
      )}

      {row.setup.valid && row.setup.target != null && (
        <div className="text-[11px] font-mono text-zinc-600 dark:text-zinc-400">
          📐 entry {fmtCurrency(row.setup.entry, sym)} · stop{" "}
          {fmtCurrency(row.setup.stop, sym)} · target{" "}
          {fmtCurrency(row.setup.target, sym)}
          {row.setup.risk_reward != null && (
            <> · RR {row.setup.risk_reward.toFixed(1)}:1</>
          )}
        </div>
      )}

      <div className="mt-auto pt-2 flex items-center gap-2">
        {row.has_digest ? (
          <button
            className="btn-ghost text-xs flex-1"
            onClick={() => onOpenDigest?.(row)}
          >
            <FileText size={14} />
            View digest
          </button>
        ) : (
          <button
            className="btn-ghost text-xs flex-1"
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
          >
            {generate.isPending ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Generating…
              </>
            ) : (
              <>
                <FileText size={14} />
                Generate digest
              </>
            )}
          </button>
        )}
      </div>
      {genErr && (
        <div className="text-[11px] text-bear-500">{genErr}</div>
      )}
    </div>
  );
}
