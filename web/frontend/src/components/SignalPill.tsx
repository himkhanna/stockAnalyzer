import clsx from "clsx";
import { SIGNAL_STYLES } from "../lib/format";
import type { SignalLabel } from "../types";

interface Props {
  label?: SignalLabel | null;
  score?: number | null;
  compact?: boolean;
}

export function SignalPill({ label, score, compact = false }: Props) {
  if (!label) return null;
  const s = SIGNAL_STYLES[label];
  return (
    <span
      className={clsx(
        "pill",
        s.bg,
        s.fg,
        compact ? "text-[10px] px-2" : "text-xs",
      )}
    >
      <span aria-hidden>{s.glyph}</span>
      <span>{label}</span>
      {score != null && !compact && (
        <span className="opacity-80 font-normal">
          ({score > 0 ? "+" : ""}
          {score.toFixed(1)})
        </span>
      )}
    </span>
  );
}
