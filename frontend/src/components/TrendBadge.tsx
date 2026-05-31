import type { TrendDirection } from "../lib/api";

type Props = {
  direction: TrendDirection | null;
  prevDayChange?: number | null;
  unit?: string;
  formatChange?: (v: number) => string;
};

const ARROW: Record<TrendDirection, string> = {
  improving: "↗",
  stable: "→",
  declining: "↘",
};

const LABEL: Record<TrendDirection, string> = {
  improving: "改善",
  stable: "横ばい",
  declining: "低下",
};

// 全指標 higher_is_better=true 前提: improving=緑 / declining=赤 / stable=灰
const COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400",
  stable: "text-slate-400",
  declining: "text-rose-400",
};

export function TrendBadge({ direction, prevDayChange, unit, formatChange }: Props) {
  if (!direction) {
    return <span className="text-xs text-slate-600">—</span>;
  }
  const changeText =
    prevDayChange != null && prevDayChange !== 0
      ? `${prevDayChange > 0 ? "+" : ""}${
          formatChange ? formatChange(prevDayChange) : prevDayChange.toFixed(1)
        }${unit ?? ""}`
      : null;
  return (
    <span className={`flex items-center gap-1 text-xs ${COLOR[direction]}`}>
      <span className="tabular-nums">{changeText}</span>
      <span aria-label={LABEL[direction]}>
        {ARROW[direction]} {LABEL[direction]}
      </span>
    </span>
  );
}
