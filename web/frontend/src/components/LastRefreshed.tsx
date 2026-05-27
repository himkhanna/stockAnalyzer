import { useEffect, useState } from "react";
import { Clock } from "lucide-react";

interface Props {
  /** ISO 8601 timestamp string, or HH:MM / "YYYY-MM-DD HH:MM" form. */
  at: string | undefined | null;
  /** Optional label prefix, e.g. "scanned", "loaded", "live". */
  label?: string;
  /** Tick the "x ago" every second (default true). Set false for static stamps. */
  live?: boolean;
  /** Compact form omits the absolute time, only shows "x ago". */
  compact?: boolean;
}

/**
 * Small badge that shows when data was last refreshed, plus a live
 * "x seconds ago" counter that ticks every second so the user can tell
 * at a glance whether the page is keeping up.
 */
export function LastRefreshed({ at, label, live = true, compact = false }: Props) {
  const ts = at ? parseTs(at) : null;
  const [, force] = useState(0);

  useEffect(() => {
    if (!live || !ts) return;
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [live, ts]);

  if (!ts) return null;
  const ago = humanAgo(ts);
  const localTime = formatLocal(ts);

  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] text-zinc-500"
      title={ts.toLocaleString()}
    >
      <Clock size={10} className="text-zinc-400" />
      {label && <span>{label}</span>}
      {!compact && <span className="tabular-nums">{localTime}</span>}
      <span className="tabular-nums">· {ago}</span>
    </span>
  );
}

function parseTs(s: string): Date | null {
  // ISO 8601, or "YYYY-MM-DD HH:MM" (server's loaded_at format).
  // Date() handles both via fallback parsing.
  const d = new Date(s);
  if (isNaN(d.getTime())) {
    // Try "YYYY-MM-DD HH:MM" → ISO
    const m = s.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})(:\d{2})?$/);
    if (m) {
      const d2 = new Date(`${m[1]}T${m[2]}${m[3] ?? ":00"}`);
      return isNaN(d2.getTime()) ? null : d2;
    }
    return null;
  }
  return d;
}

function formatLocal(d: Date): string {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function humanAgo(d: Date): string {
  const sec = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}
