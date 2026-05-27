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

import { fmtCurrency, fmtPct, signalRank, SIGNAL_STYLES } from "../lib/format";
import type { SortCol, SortState } from "./FilterBar";
import type { CardRow, LiveQuote } from "../types";
import { SignalPill } from "./SignalPill";
import { Sparkline } from "./Sparkline";
import { StockCard } from "./StockCard";

interface Props {
  rows: CardRow[];
  liveByKey: Record<string, LiveQuote | undefined>;
  onOpenDigest: (row: CardRow) => void;
  sort: SortState;
  onSort: (s: SortState) => void;
}

const _SORT_OPTIONS: { col: SortCol; label: string }[] = [
  { col: "ticker", label: "Ticker" },
  { col: "price", label: "Price" },
  { col: "day", label: "Day %" },
  { col: "signal", label: "Signal" },
  { col: "rsi", label: "RSI" },
  { col: "weight", label: "Weight" },
  { col: "pnl", label: "P/L %" },
];

/**
 * Dense one-row-per-holding list. Click a row to expand the existing
 * StockCard inline. CLAUDE.md: a 15-stock portfolio should be scannable
 * in ~30 seconds.
 *
 * Layout: desktop renders a wide table; phone (< md) renders one card
 * per row with the same sort + expand behaviour, since the table just
 * doesn't fit on a 360px-wide screen.
 */
export function HoldingsTable({ rows, liveByKey, onOpenDigest, sort, onSort }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Click a header: if it's already the sorted column, flip direction.
  // Otherwise, switch to it with a sensible default direction per column.
  const clickHeader = (col: SortCol) => {
    if (sort.col === col) {
      onSort({ col, dir: sort.dir === "asc" ? "desc" : "asc" });
    } else {
      const defaultDir: Record<SortCol, "asc" | "desc"> = {
        ticker: "asc",
        price: "desc",
        day: "desc",
        signal: "desc",
        rsi: "desc",
        weight: "desc",
        pnl: "desc",
      };
      onSort({ col, dir: defaultDir[col] });
    }
  };

  return (
    <>
      {/* Mobile: card-per-row */}
      <div className="md:hidden space-y-2">
        <div className="card p-2 flex items-center gap-2 text-xs">
          <span className="text-zinc-500">Sort</span>
          <select
            className="input text-xs flex-1"
            value={`${sort.col}:${sort.dir}`}
            onChange={(e) => {
              const [col, dir] = e.target.value.split(":") as [SortCol, "asc" | "desc"];
              onSort({ col, dir });
            }}
          >
            {_SORT_OPTIONS.map((opt) => (
              <optgroup key={opt.col} label={opt.label}>
                <option value={`${opt.col}:desc`}>{opt.label} ↓</option>
                <option value={`${opt.col}:asc`}>{opt.label} ↑</option>
              </optgroup>
            ))}
          </select>
        </div>
        {rows.map((row) => {
          const key = `${row.symbol}.${row.market}`;
          return (
            <MobileHoldingCard
              key={key}
              row={row}
              live={liveByKey[key]}
              expanded={expanded.has(key)}
              onToggle={() => toggle(key)}
              onOpenDigest={onOpenDigest}
            />
          );
        })}
      </div>

      {/* Desktop: dense table */}
      <div className="hidden md:block card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 uppercase tracking-wider text-[10px]">
            <tr>
              <th className="w-6"></th>
              <SortableTh col="ticker" sort={sort} onClick={clickHeader} align="left">Ticker</SortableTh>
              <SortableTh col="price" sort={sort} onClick={clickHeader} align="right">Price</SortableTh>
              <SortableTh col="day" sort={sort} onClick={clickHeader} align="right">Day</SortableTh>
              <th className="text-center px-2 py-2">Trend</th>
              <SortableTh col="signal" sort={sort} onClick={clickHeader} align="left">Signal</SortableTh>
              <SortableTh col="rsi" sort={sort} onClick={clickHeader} align="right">RSI</SortableTh>
              <SortableTh col="weight" sort={sort} onClick={clickHeader} align="right">Wt</SortableTh>
              <SortableTh col="pnl" sort={sort} onClick={clickHeader} align="right">P/L</SortableTh>
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
    </>
  );
}

function MobileHoldingCard({
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
      <div className="card p-3 border-l-4 border-l-bear-500">
        <div className="font-semibold">{row.symbol}</div>
        <div className="text-xs text-bear-600 mt-1">{row.error}</div>
      </div>
    );
  }

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
    <div
      className={clsx(
        "card overflow-hidden cursor-pointer",
        needsAttention && "border-l-4 border-l-bear-500",
      )}
      onClick={onToggle}
    >
      <div className="p-3 space-y-2">
        {/* Top row: ticker + market + signal + chevron */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-bold">{row.symbol}</span>
            <span className="text-[10px] text-zinc-500 uppercase tracking-wider">
              {row.market}
            </span>
            {needsAttention && (
              <AlertTriangle size={12} className="text-bear-500 shrink-0" />
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <SignalPill label={row.score_label} score={row.score_value} compact />
            {expanded ? <ChevronDown size={14} className="text-zinc-400" /> : <ChevronRight size={14} className="text-zinc-400" />}
          </div>
        </div>

        {/* Big row: price + day change */}
        <div className="flex items-baseline justify-between">
          <div className="flex items-center gap-1.5 tabular-nums">
            {liveDot && (
              <Circle
                size={6}
                fill="currentColor"
                strokeWidth={0}
                className={liveDot.color}
                aria-label={liveDot.title}
              />
            )}
            <span className="text-lg font-semibold">
              {fmtCurrency(price, row.currency_symbol)}
            </span>
          </div>
          <span className={clsx("flex items-center gap-0.5 text-sm font-medium tabular-nums", chgColor)}>
            <ChgIcon size={14} strokeWidth={3} />
            {fmtPct(changePct, 2)}
          </span>
        </div>

        {/* Sparkline */}
        <Sparkline closes={row.recent_closes} color={lineColor} height={28} />

        {/* Mini stats grid */}
        <div className="grid grid-cols-3 gap-2 text-xs">
          <Stat label="RSI" value={row.rsi != null ? row.rsi.toFixed(0) : "—"} />
          <Stat label="Wt" value={row.weight_pct != null ? `${row.weight_pct.toFixed(0)}%` : "—"} />
          <Stat
            label="P/L"
            value={
              row.pnl_pct != null ? (
                <span className={row.pnl_pct >= 0 ? "text-bull-500" : "text-bear-500"}>
                  {fmtPct(row.pnl_pct, 1)}
                </span>
              ) : (
                "—"
              )
            }
          />
        </div>
      </div>

      {expanded && (
        <div className="p-3 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/30">
          <StockCard row={row} onOpenDigest={onOpenDigest} />
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wider">{label}</span>
      <span className="tabular-nums font-medium">{value}</span>
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

function SortableTh({
  col,
  sort,
  onClick,
  align,
  children,
}: {
  col: SortCol;
  sort: SortState;
  onClick: (c: SortCol) => void;
  align: "left" | "right" | "center";
  children: React.ReactNode;
}) {
  const active = sort.col === col;
  const arrow = active ? (sort.dir === "asc" ? "↑" : "↓") : "";
  return (
    <th
      className={clsx(
        "px-2 py-2 cursor-pointer select-none hover:text-zinc-700 dark:hover:text-zinc-300 transition-colors",
        align === "left" && "text-left",
        align === "right" && "text-right",
        align === "center" && "text-center",
        active && "text-zinc-900 dark:text-zinc-100",
      )}
      onClick={() => onClick(col)}
    >
      <span>{children}</span>
      {arrow && <span className="ml-1">{arrow}</span>}
    </th>
  );
}

/**
 * Comparator factory used by the dashboard to order rows for the table.
 * Uses live overlay for price/day when present so re-sorts pick up
 * fresh data without re-fetching the dashboard.
 */
export function makeRowSorter(
  sort: SortState,
  liveByKey: Record<string, LiveQuote | undefined>,
) {
  const sign = sort.dir === "asc" ? 1 : -1;
  return (a: CardRow, b: CardRow): number => {
    const ka = `${a.symbol}.${a.market}`;
    const kb = `${b.symbol}.${b.market}`;
    const la = liveByKey[ka];
    const lb = liveByKey[kb];
    switch (sort.col) {
      case "ticker":
        return sign * a.symbol.localeCompare(b.symbol);
      case "price":
        return sign * ((la?.price ?? a.price ?? 0) - (lb?.price ?? b.price ?? 0));
      case "day":
        return sign * ((la?.change_pct ?? a.change_pct ?? 0) - (lb?.change_pct ?? b.change_pct ?? 0));
      case "signal":
        // signalRank: 0=Strong Sell ... 4=Strong Buy. asc = bearish first.
        return sign * (signalRank(a.score_label) - signalRank(b.score_label));
      case "rsi":
        return sign * ((a.rsi ?? -1) - (b.rsi ?? -1));
      case "weight":
        return sign * ((a.weight_pct ?? -1) - (b.weight_pct ?? -1));
      case "pnl":
        return sign * ((a.pnl_pct ?? -Infinity) - (b.pnl_pct ?? -Infinity));
    }
  };
}
