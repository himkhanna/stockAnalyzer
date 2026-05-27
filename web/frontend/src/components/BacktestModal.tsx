import { Loader2, ShieldCheck, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { fmtPct } from "../lib/format";

interface Props {
  symbol: string;
  market: string;
  onClose: () => void;
}

export function BacktestModal({ symbol, market, onClose }: Props) {
  const q = useQuery({
    queryKey: ["backtest", symbol, market],
    queryFn: () => api.runBacktest(symbol, market),
    // Backtest is deterministic on the same period, so cache aggressively.
    staleTime: 5 * 60_000,
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-xl w-full max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex items-baseline gap-3">
            <ShieldCheck size={18} className="text-zinc-500" />
            <h2 className="text-lg font-bold">Backtest</h2>
            <span className="text-sm font-mono text-zinc-500">
              {symbol} · {market}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-zinc-100 dark:hover:bg-zinc-800"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto">
          {q.isLoading && (
            <div className="flex items-center gap-2 text-sm text-zinc-500">
              <Loader2 size={14} className="animate-spin" /> Running backtest…
            </div>
          )}
          {q.error && (
            <div className="text-sm text-bear-500">
              {(q.error as Error).message}
            </div>
          )}
          {q.data && <BacktestBody bt={q.data} />}
        </div>
      </div>
    </div>
  );
}

function BacktestBody({ bt }: { bt: import("../types").Backtest }) {
  const edgeColor =
    bt.edge_pct > 0
      ? "text-bull-500"
      : bt.edge_pct < 0
      ? "text-bear-500"
      : "text-zinc-500";
  return (
    <div className="space-y-5">
      <div className="text-xs text-zinc-500">
        {bt.start_date} → {bt.end_date} · {bt.bars} bars · technicals-only
        (no historical sentiment)
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Stat label="Strategy return" value={fmtPct(bt.strategy_return_pct)}
              tone={bt.strategy_return_pct >= 0 ? "bull" : "bear"} />
        <Stat label="Buy-and-hold" value={fmtPct(bt.buy_and_hold_return_pct)}
              tone={bt.buy_and_hold_return_pct >= 0 ? "bull" : "bear"} />
        <Stat
          label="Edge vs hold"
          value={fmtPct(bt.edge_pct)}
          subtitle={bt.beat_hold ? "beat hold" : "underperformed hold"}
          tone={bt.beat_hold ? "bull" : "bear"}
        />
        <Stat
          label="Max drawdown"
          value={fmtPct(-Math.abs(bt.max_drawdown_pct))}
          tone="bear"
        />
      </div>

      <div className="card p-4 space-y-2 text-sm">
        <Row k="Trades" v={`${bt.n_trades} round-trip${bt.n_trades === 1 ? "" : "s"}`} />
        <Row
          k="Win rate"
          v={bt.win_rate_pct != null ? `${bt.win_rate_pct.toFixed(0)}%` : "n/a"}
        />
        <Row
          k="Average hold"
          v={
            bt.avg_holding_days != null
              ? `${bt.avg_holding_days.toFixed(1)} days`
              : "n/a"
          }
        />
        <Row k="In market" v={`${bt.in_market_pct.toFixed(0)}% of bars`} />
        <Row
          k="Transaction cost"
          v={`${bt.transaction_cost_pct}% per side`}
        />
        <Row
          k="Score thresholds"
          v={`enter ≥ ${bt.score_threshold_enter.toFixed(1)}, exit ≤ ${bt.score_threshold_exit.toFixed(1)}`}
        />
      </div>

      <div className="text-xs leading-relaxed text-zinc-500 border-l-2 border-zinc-300 dark:border-zinc-700 pl-3">
        <span className={`font-semibold ${edgeColor}`}>Honesty check:</span>{" "}
        {bt.sentiment_used
          ? "Sentiment was included in scoring during the backtest."
          : "Sentiment was treated as neutral throughout — historical news isn't available for personal use, so this measures the technical rules only."}{" "}
        Matching buy-and-hold is a common and honest outcome; we report it as-is rather than tuning until it looks good.
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  subtitle,
  tone,
}: {
  label: string;
  value: string;
  subtitle?: string;
  tone: "bull" | "bear" | "neutral";
}) {
  const cls =
    tone === "bull"
      ? "text-bull-500"
      : tone === "bear"
      ? "text-bear-500"
      : "text-zinc-500";
  return (
    <div className="card p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1">
        {label}
      </div>
      <div className={`text-xl font-mono font-semibold ${cls}`}>{value}</div>
      {subtitle && <div className="text-xs text-zinc-500 mt-1">{subtitle}</div>}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-zinc-500">{k}</span>
      <span className="font-mono">{v}</span>
    </div>
  );
}
