import clsx from "clsx";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Circle,
} from "lucide-react";
import { useState } from "react";

import { fmtCurrency, fmtPct, SIGNAL_STYLES } from "../lib/format";
import type { CardRow, LiveQuote } from "../types";
import { SignalPill } from "./SignalPill";
import { Sparkline } from "./Sparkline";
import { StockCard } from "./StockCard";

interface Props {
  rows: CardRow[];
  liveByKey: Record<string, LiveQuote | undefined>;
  onOpenDigest: (row: CardRow) => void;
}

/**
 * Dense one-row-per-holding list. Click a row to expand the existing
 * StockCard inline. CLAUDE.md: a 15-stock portfolio should be scannable
 * in ~30 seconds.
 */
export function HoldingsTable({ rows, liveByKey, onOpenDigest }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 uppercase tracking-wider text-[10px]">
          <tr>
            <th className="w-6"></th>
            <th className="text-left px-3 py-2">Ticker</th>
            <th className="text-right px-2 py-2">Price</th>
            <th className="text-right px-2 py-2">Day</th>
            <th className="text-center px-2 py-2">Trend</th>
            <th className="text-left px-2 py-2">Signal</th>
            <th className="text-right px-2 py-2">RSI</th>
            <th className="text-right px-2 py-2">Wt</th>
            <th className="text-right px-2 py-2">P/L</th>
            <th className="w-6"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = `${row.symbol}.${row.market}`;
            const isOpen = expanded.has(key);
            const live = liveByKey[key];
            return (
              <HoldingRow
                key={key}
                row={row}
                live={live}
                expanded={isOpen}
                onToggle={() => toggle(key)}
                onOpenDigest={onOpenDigest}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HoldingRow({
  row,
  live,
  expanded,
  onToggle,
  onOpenDigest,
}: {
  row: CardRow;
  live: LiveQuote | undefined;
  expanded: boolean;
  onToggle: () => void;
  onOpenDigest: (row: CardRow) => void;
}) {
  if (row.error) {
    return (
      <tr className="border-t border-zinc-200 dark:border-zinc-800">
        <td></td>
        <td className="px-3 py-2 font-semibold">{row.symbol}</td>
        <td colSpan={8} className="px-2 py-2 text-bear-600 text-xs">
          {row.error}
        </td>
      </tr>
    );
  }

  // Live overlay wins over the cached dashboard price when present.
  const price = live?.price ?? row.price;
  const changePct = live?.change_pct ?? row.change_pct ?? 0;
  const chgColor =
    changePct > 0 ? "text-bull-500" : changePct < 0 ? "text-bear-500" : "text-zinc-500";
  const ChgIcon = changePct > 0 ? ArrowUp : ArrowDown;
  const lineColor = row.score_label ? SIGNAL_STYLES[row.score_label].line : "#737373";
  const needsAttention =
    row.score_label === "Strong Sell" || row.score_label === "Sell" || row.overweight;

  const liveDot =
    live && live.market_open
      ? { color: "text-bull-500", title: "Live · market open" }
      : live
      ? { color: "text-zinc-400", title: "Last close · market closed" }
      : null;

  return (
    <>
      <tr
        onClick={onToggle}
        className={clsx(
          "border-t border-zinc-200 dark:border-zinc-800 cursor-pointer",
          "hover:bg-zinc-50 dark:hover:bg-zinc-900/40",
          needsAttention && "bg-bear-50/30 dark:bg-bear-900/5",
        )}
      >
        <td className="text-zinc-400 pl-2">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </td>
        <td className="px-3 py-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-semibold tabular-nums">{row.symbol}</span>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wider">
              {row.market}
            </span>
            {needsAttention && (
              <AlertTriangle size={12} className="text-bear-500 shrink-0" />
            )}
          </div>
        </td>
        <td className="px-2 py-2 text-right">
          <div className="flex items-center justify-end gap-1.5 tabular-nums">
            {liveDot && (
              <Circle
                size={6}
                fill="currentColor"
                strokeWidth={0}
                className={liveDot.color}
                aria-label={liveDot.title}
              />
            )}
            <span className="font-medium">{fmtCurrency(price, row.currency_symbol)}</span>
          </div>
        </td>
        <td className="px-2 py-2 text-right">
          <span className={clsx("flex items-center justify-end gap-0.5 text-xs font-medium tabular-nums", chgColor)}>
            <ChgIcon size={11} strokeWidth={3} />
            {fmtPct(changePct, 2)}
          </span>
        </td>
        <td className="px-2 py-1 w-20">
          <Sparkline closes={row.recent_closes} color={lineColor} height={22} />
        </td>
        <td className="px-2 py-2">
          <SignalPill label={row.score_label} score={row.score_value} compact />
        </td>
        <td className="px-2 py-2 text-right text-xs tabular-nums text-zinc-600 dark:text-zinc-400">
          {row.rsi != null ? row.rsi.toFixed(0) : "—"}
        </td>
        <td className="px-2 py-2 text-right text-xs tabular-nums">
          {row.weight_pct != null ? `${row.weight_pct.toFixed(0)}%` : "—"}
        </td>
        <td className="px-2 py-2 text-right text-xs tabular-nums">
          {row.pnl_pct != null ? (
            <span className={row.pnl_pct >= 0 ? "text-bull-500" : "text-bear-500"}>
              {fmtPct(row.pnl_pct, 1)}
            </span>
          ) : (
            "—"
          )}
        </td>
        <td></td>
      </tr>
      {expanded && (
        <tr className="border-t border-zinc-200 dark:border-zinc-800">
          <td colSpan={10} className="p-3 bg-zinc-50 dark:bg-zinc-900/30">
            <StockCard row={row} onOpenDigest={onOpenDigest} />
          </td>
        </tr>
      )}
    </>
  );
}
