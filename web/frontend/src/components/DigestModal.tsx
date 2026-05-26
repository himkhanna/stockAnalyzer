import { X } from "lucide-react";
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
        <div className="flex items-center justify-between p-4 border-b border-zinc-200 dark:border-zinc-800">
          <h2 className="text-lg font-bold">
            {symbol}
            <span className="text-xs ml-2 text-zinc-500 uppercase tracking-wider">
              {market}
            </span>
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded-md hover:bg-zinc-100 dark:hover:bg-zinc-800"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>
        <div className="overflow-y-auto p-6 prose prose-sm dark:prose-invert max-w-none">
          {q.isLoading && (
            <div className="text-sm text-zinc-500">Loading…</div>
          )}
          {q.error && (
            <div className="text-sm text-bear-500">
              {(q.error as Error).message}
            </div>
          )}
          {q.data && (
            <>
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                {q.data.markdown}
              </pre>
              {q.data.generated_at && (
                <div className="text-xs text-zinc-500 mt-4">
                  generated {q.data.generated_at}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
