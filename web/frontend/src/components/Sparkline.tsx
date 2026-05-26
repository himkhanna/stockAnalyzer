import { useId } from "react";

interface Props {
  closes: number[];
  color: string;
  height?: number;
}

export function Sparkline({ closes, color, height = 40 }: Props) {
  const id = useId();
  if (!closes || closes.length < 2) {
    return <div style={{ height }} />;
  }
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const rng = hi - lo || 1;
  const W = 100; // viewBox width — actual width is responsive
  const padY = 2;
  const n = closes.length;
  const pts = closes.map((v, i) => {
    const x = (i * (W - 2)) / (n - 1) + 1;
    const y = height - padY - ((v - lo) / rng) * (height - 2 * padY);
    return [x, y] as const;
  });
  const line = pts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const fillPath =
    `M1,${height - padY} ` +
    pts.map(([x, y]) => `L${x.toFixed(2)},${y.toFixed(2)}`).join(" ") +
    ` L${W - 1},${height - padY} Z`;
  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${W} ${height}`}
      preserveAspectRatio="none"
      className="block"
    >
      <defs>
        <linearGradient id={`g-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.18" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={fillPath} fill={`url(#g-${id})`} />
      <polyline
        fill="none"
        stroke={color}
        strokeWidth={1.4}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={line}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
