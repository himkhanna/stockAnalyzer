import clsx from "clsx";
import { Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { TickerCombo } from "../components/TickerCombo";
import type { Holding, HoldingIn, ImportResult } from "../types";

export function PortfolioPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["holdings"], queryFn: api.listHoldings });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["holdings"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };

  return (
    <div className="space-y-8 pb-12">
      <ImportSection onDone={invalidateAll} />
      <HoldingsTable
        holdings={q.data ?? []}
        loading={q.isLoading}
        onChange={invalidateAll}
      />
      <AddHoldingForm onAdded={invalidateAll} />
    </div>
  );
}

function ImportSection({ onDone }: { onDone: () => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [replace, setReplace] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const m = useMutation({
    mutationFn: () => api.importCsv(file!, replace),
    onSuccess: (data) => {
      setResult(data);
      if (data.imported > 0) onDone();
    },
  });

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-base font-bold">Import CSV</h2>
        <span className="text-xs text-zinc-500">
          ICICI Direct or canonical format
        </span>
      </div>
      <div className="card p-6 space-y-4">
        <div
          className={clsx(
            "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
            file
              ? "border-bull-500 bg-bull-50 dark:bg-bull-900/10"
              : "border-zinc-300 dark:border-zinc-700 hover:border-zinc-400 dark:hover:border-zinc-600",
          )}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f && f.name.endsWith(".csv")) setFile(f);
          }}
        >
          <Upload className="mx-auto text-zinc-400 mb-2" size={28} />
          <div className="text-sm font-medium">
            {file ? file.name : "Click or drop a CSV here"}
          </div>
          <div className="text-xs text-zinc-500 mt-1">
            ICICI Direct PortFolioEqtSummary export, or{" "}
            <code>ticker, market, shares, cost_basis, date</code>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={replace}
              onChange={(e) => setReplace(e.target.checked)}
            />
            Replace existing holdings
          </label>
          <button
            className="btn-primary ml-auto"
            disabled={!file || m.isPending}
            onClick={() => m.mutate()}
          >
            {m.isPending ? "Importing…" : "Import"}
          </button>
        </div>

        {m.error && (
          <div className="text-sm text-bear-500">
            {(m.error as Error).message}
          </div>
        )}

        {result && (
          <div className="space-y-3 animate-fade-in">
            {result.imported > 0 && (
              <div className="text-sm text-bull-600 dark:text-bull-500">
                Imported {result.imported} holding{result.imported !== 1 && "s"}.
              </div>
            )}
            {result.errors.length > 0 && (
              <>
                <div className="text-sm font-semibold text-amber-700 dark:text-amber-400">
                  {result.errors.length} row{result.errors.length !== 1 && "s"} had problems:
                </div>
                <div className="overflow-x-auto rounded-md border border-zinc-200 dark:border-zinc-800">
                  <table className="w-full text-xs">
                    <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-500">
                      <tr>
                        <th className="text-left px-3 py-2">reason</th>
                        <th className="text-left px-3 py-2">isin</th>
                        <th className="text-left px-3 py-2">name</th>
                        <th className="text-left px-3 py-2">broker</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.errors.map((e, i) => (
                        <tr
                          key={i}
                          className="border-t border-zinc-200 dark:border-zinc-800"
                        >
                          <td className="px-3 py-2">{e.reason}</td>
                          <td className="px-3 py-2 font-mono">{e.isin}</td>
                          <td className="px-3 py-2">{e.name}</td>
                          <td className="px-3 py-2 font-mono">
                            {e.broker_symbol}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="text-xs text-zinc-500">
                  Add entries to <code>.ticker_overrides.json</code> in the
                  project root (<code>{"{\"ISIN\": \"NSE_SYMBOL\"}"}</code>) and re-import.
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function HoldingsTable({
  holdings,
  loading,
  onChange,
}: {
  holdings: Holding[];
  loading: boolean;
  onChange: () => void;
}) {
  const m = useMutation({
    mutationFn: ({ symbol, market }: { symbol: string; market: string }) =>
      api.removeHolding(symbol, market),
    onSuccess: onChange,
  });

  if (loading)
    return <div className="text-sm text-zinc-500">Loading holdings…</div>;
  if (holdings.length === 0)
    return (
      <EmptyState title="No holdings yet">
        Import a CSV above or add one manually below.
      </EmptyState>
    );

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-base font-bold">Current holdings</h2>
        <span className="text-xs text-zinc-500">
          {holdings.length} holding{holdings.length !== 1 && "s"}
        </span>
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 dark:bg-zinc-900/50 text-zinc-500 text-xs uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-2.5 font-semibold">Ticker</th>
              <th className="text-left px-4 py-2.5 font-semibold">Market</th>
              <th className="text-right px-4 py-2.5 font-semibold">Shares</th>
              <th className="text-right px-4 py-2.5 font-semibold">Cost basis</th>
              <th className="text-left px-4 py-2.5 font-semibold">Currency</th>
              <th className="text-left px-4 py-2.5 font-semibold">Added</th>
              <th className="px-4 py-2.5"></th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => (
              <tr
                key={`${h.ticker}.${h.market}`}
                className="border-t border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-900/50"
              >
                <td className="px-4 py-2.5 font-semibold">{h.ticker}</td>
                <td className="px-4 py-2.5 text-xs text-zinc-500 uppercase">
                  {h.market}
                </td>
                <td className="px-4 py-2.5 text-right font-mono">{h.shares}</td>
                <td className="px-4 py-2.5 text-right font-mono">
                  {h.cost_basis.toFixed(2)}
                </td>
                <td className="px-4 py-2.5 text-zinc-500">{h.currency}</td>
                <td className="px-4 py-2.5 text-zinc-500 text-xs">
                  {h.date_added}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <button
                    className="text-zinc-400 hover:text-bear-500 p-1"
                    onClick={() =>
                      m.mutate({ symbol: h.ticker, market: h.market })
                    }
                    aria-label={`Remove ${h.ticker}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AddHoldingForm({ onAdded }: { onAdded: () => void }) {
  const [form, setForm] = useState<HoldingIn>({
    ticker: "",
    market: "US",
    shares: 0,
    cost_basis: 0,
  });
  const m = useMutation({
    mutationFn: () => api.addHolding(form),
    onSuccess: () => {
      onAdded();
      setForm({ ticker: "", market: "US", shares: 0, cost_basis: 0 });
    },
  });
  return (
    <section>
      <h2 className="text-base font-bold mb-3">Add a holding manually</h2>
      <form
        className="card p-4 grid grid-cols-1 md:grid-cols-5 gap-3 items-end"
        onSubmit={(e) => {
          e.preventDefault();
          if (form.ticker && form.shares > 0) m.mutate();
        }}
      >
        <Field label="Ticker or company">
          <TickerCombo
            value={form.ticker}
            onChange={(v) => setForm((f) => ({ ...f, ticker: v }))}
            onPick={(hit) =>
              setForm((f) => ({ ...f, ticker: hit.symbol, market: hit.market }))
            }
            placeholder="AAPL or Reliance Industries"
          />
        </Field>
        <Field label="Market">
          <select
            className="input"
            value={form.market}
            onChange={(e) => setForm({ ...form, market: e.target.value })}
          >
            <option value="US">US</option>
            <option value="NSE">NSE (India)</option>
            <option value="BSE">BSE (India)</option>
            <option value="DFM">DFM (Dubai)</option>
            <option value="ADX">ADX (Abu Dhabi)</option>
          </select>
        </Field>
        <Field label="Shares">
          <input
            className="input"
            type="number"
            min={0}
            step="any"
            value={form.shares}
            onChange={(e) =>
              setForm({ ...form, shares: parseFloat(e.target.value) || 0 })
            }
          />
        </Field>
        <Field label="Cost basis">
          <input
            className="input"
            type="number"
            min={0}
            step="any"
            value={form.cost_basis}
            onChange={(e) =>
              setForm({ ...form, cost_basis: parseFloat(e.target.value) || 0 })
            }
          />
        </Field>
        <button
          type="submit"
          className="btn-primary"
          disabled={m.isPending || !form.ticker || form.shares <= 0}
        >
          {m.isPending ? "Adding…" : "Add / update"}
        </button>
        {m.error && (
          <div className="md:col-span-5 text-sm text-bear-500">
            {(m.error as Error).message}
          </div>
        )}
      </form>
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-zinc-500">{label}</span>
      {children}
    </label>
  );
}
