import { Loader2, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import type { SearchHit } from "../types";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onPick?: (hit: SearchHit) => void;
  placeholder?: string;
  autoFocus?: boolean;
  className?: string;
}

export function TickerCombo({
  value,
  onChange,
  onPick,
  placeholder = "AAPL or Reliance Industries",
  autoFocus,
  className,
}: Props) {
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const lastQueryRef = useRef<string>("");

  // Debounced search. Cancels in-flight requests when the user keeps typing.
  useEffect(() => {
    const q = value.trim();
    if (q.length < 2) {
      setHits([]);
      setLoading(false);
      return;
    }
    lastQueryRef.current = q;
    const ac = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await api.search(q, 10, ac.signal);
        if (lastQueryRef.current === q) {
          setHits(res.hits);
          setHighlight(0);
        }
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (lastQueryRef.current === q) setHits([]);
      } finally {
        if (lastQueryRef.current === q) setLoading(false);
      }
    }, 250);

    return () => {
      ac.abort();
      clearTimeout(timer);
    };
  }, [value]);

  // Close on outside click.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function choose(hit: SearchHit) {
    onChange(hit.symbol);
    onPick?.(hit);
    setOpen(false);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || hits.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(hits[highlight]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const showDropdown = open && (loading || hits.length > 0);

  return (
    <div ref={wrapRef} className={`relative ${className ?? ""}`}>
      <div className="relative">
        <input
          className="input pr-8"
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          placeholder={placeholder}
          autoFocus={autoFocus}
          autoComplete="off"
          spellCheck={false}
        />
        <div className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-400">
          {loading ? <Loader2 className="animate-spin" size={14} /> : <Search size={14} />}
        </div>
      </div>
      {showDropdown && (
        <div className="absolute z-30 mt-1 w-full max-h-80 overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-lg">
          {hits.length === 0 && !loading ? (
            <div className="px-3 py-2 text-xs text-zinc-500">No matches</div>
          ) : (
            hits.map((h, i) => (
              <button
                key={`${h.symbol}-${h.exchange}`}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(h)}
                onMouseEnter={() => setHighlight(i)}
                className={`w-full text-left px-3 py-2 flex items-center justify-between gap-3 text-sm ${
                  i === highlight
                    ? "bg-zinc-100 dark:bg-zinc-800"
                    : "hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                }`}
              >
                <div className="min-w-0">
                  <div className="font-semibold truncate">{h.symbol}</div>
                  <div className="text-xs text-zinc-500 truncate">{h.name}</div>
                </div>
                <span className="shrink-0 text-[11px] font-medium px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
                  {h.market}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
