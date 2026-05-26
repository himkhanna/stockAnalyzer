import { Search } from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { api } from "../api";
import { DigestBody } from "../components/DigestModal";
import { StockCard } from "../components/StockCard";
import { TickerCombo } from "../components/TickerCombo";
import type { Lookup } from "../types";

export function LookupPage() {
  const [raw, setRaw] = useState("AAPL");
  const [market, setMarket] = useState<string>("");
  const [runLlm, setRunLlm] = useState(false);
  const [result, setResult] = useState<Lookup | null>(null);

  const m = useMutation({
    mutationFn: () =>
      api.lookup(raw, {
        market: market || undefined,
        run_llm: runLlm,
      }),
    onSuccess: (data) => setResult(data),
  });

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold">Look up any ticker</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Same pipeline as your portfolio — works for any US/NSE/BSE ticker, even
          one you don't own.
        </p>
      </div>

      <form
        className="card p-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          m.mutate();
        }}
      >
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-zinc-500 mb-1 block">Ticker or company name</label>
          <TickerCombo
            value={raw}
            onChange={setRaw}
            onPick={(hit) => setMarket(hit.market)}
            placeholder="AAPL or Reliance Industries"
            autoFocus
          />
        </div>
        <div>
          <label className="text-xs text-zinc-500 mb-1 block">Market</label>
          <select
            className="input w-32"
            value={market}
            onChange={(e) => setMarket(e.target.value)}
          >
            <option value="">(auto)</option>
            <option value="US">US</option>
            <option value="NSE">NSE</option>
            <option value="BSE">BSE</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm mb-2">
          <input
            type="checkbox"
            checked={runLlm}
            onChange={(e) => setRunLlm(e.target.checked)}
          />
          LLM synthesis
        </label>
        <button
          type="submit"
          className="btn-primary"
          disabled={m.isPending || !raw.trim()}
        >
          <Search size={14} />
          {m.isPending ? "Analysing…" : "Analyse"}
        </button>
      </form>

      {m.error && (
        <div className="card p-4 text-sm text-bear-500">
          {(m.error as Error).message}
        </div>
      )}

      {result && (
        <div className="space-y-4 animate-fade-in">
          <StockCard row={result.row} />
          {result.markdown && (
            <div className="card p-6">
              <DigestBody markdown={result.markdown} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
