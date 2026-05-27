import { X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";

interface Props {
  symbol: string;
  market: string;
  onClose: () => void;
}

export function DigestModal({ symbol, market, onClose }: Props) {
  const q = useQuery({
    queryKey: ["digest", symbol, market],
    queryFn: () => api.getDigest(symbol, market),
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-fade-in"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-3xl w-full max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex items-baseline gap-3">
            <h2 className="text-lg font-bold">{symbol}</h2>
            <span className="text-[11px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
              {market}
            </span>
            {q.data?.generated_at && (
              <span className="text-xs text-zinc-500">
                generated {q.data.generated_at}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-zinc-100 dark:hover:bg-zinc-800"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>
        <div className="overflow-y-auto px-6 py-5">
          {q.isLoading && (
            <div className="text-sm text-zinc-500">Loading…</div>
          )}
          {q.error && (
            <div className="text-sm text-bear-500">
              {(q.error as Error).message}
            </div>
          )}
          {q.data && <DigestBody markdown={q.data.markdown} />}
        </div>
      </div>
    </div>
  );
}

export function DigestBody({ markdown }: { markdown: string }) {
  return (
    <div
      className="prose prose-sm dark:prose-invert max-w-none
        prose-headings:font-bold prose-headings:tracking-tight
        prose-h1:hidden
        prose-h2:text-base prose-h2:mt-6 prose-h2:mb-2
        prose-h2:pb-1 prose-h2:border-b prose-h2:border-zinc-200 dark:prose-h2:border-zinc-800
        prose-p:my-2
        prose-table:my-3 prose-table:text-sm
        prose-th:bg-zinc-50 dark:prose-th:bg-zinc-800/50 prose-th:font-semibold
        prose-th:text-left prose-th:px-3 prose-th:py-2
        prose-td:px-3 prose-td:py-2 prose-td:border-t prose-td:border-zinc-200 dark:prose-td:border-zinc-800
        prose-code:before:content-none prose-code:after:content-none
        prose-code:bg-zinc-100 dark:prose-code:bg-zinc-800 prose-code:px-1 prose-code:rounded
        prose-strong:font-semibold
        prose-em:text-zinc-500 prose-em:not-italic
        prose-li:my-0.5"
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  );
}
