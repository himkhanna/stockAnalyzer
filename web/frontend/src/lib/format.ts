import type { SignalLabel } from "../types";

export function fmtCurrency(
  v: number | null | undefined,
  symbol: string,
  digits = 2,
): string {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1_00_000 && digits === 0) {
    // Indian readable big-number formatting kept simple.
  }
  return `${sign}${symbol}${abs.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

export const SIGNAL_ORDER: SignalLabel[] = [
  "Strong Sell",
  "Sell",
  "Hold",
  "Buy",
  "Strong Buy",
];

export function signalRank(s: SignalLabel | null | undefined): number {
  if (!s) return 99;
  const i = SIGNAL_ORDER.indexOf(s);
  return i === -1 ? 99 : i;
}

export interface SignalStyle {
  bg: string;
  fg: string;
  ring: string;
  line: string;
  glyph: string;
}

export const SIGNAL_STYLES: Record<SignalLabel, SignalStyle> = {
  "Strong Sell": {
    bg: "bg-bear-900",
    fg: "text-white",
    ring: "ring-bear-900/30",
    line: "#7f1d1d",
    glyph: "🔻",
  },
  Sell: {
    bg: "bg-bear-500",
    fg: "text-white",
    ring: "ring-bear-500/30",
    line: "#dc2626",
    glyph: "⬇",
  },
  Hold: {
    bg: "bg-zinc-500",
    fg: "text-white",
    ring: "ring-zinc-500/30",
    line: "#737373",
    glyph: "—",
  },
  Buy: {
    bg: "bg-bull-500",
    fg: "text-white",
    ring: "ring-bull-500/30",
    line: "#16a34a",
    glyph: "⬆",
  },
  "Strong Buy": {
    bg: "bg-bull-600",
    fg: "text-white",
    ring: "ring-bull-600/30",
    line: "#15803d",
    glyph: "🚀",
  },
};
