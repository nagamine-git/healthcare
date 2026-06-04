import type { TrendDirection } from "../lib/api";

type Props = {
  direction: TrendDirection | null;
  achievementChange?: number | null;
};

const ARROW: Record<TrendDirection, string> = { improving: "↗", stable: "→", declining: "↘" };
const LABEL: Record<TrendDirection, string> = { improving: "改善", stable: "横ばい", declining: "低下" };
const COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400",
  stable: "text-slate-400",
  declining: "text-rose-400",
};

export function TrendBadge({ direction, achievementChange }: Props) {
  if (!direction) return <span className="text-xs text-slate-600">—</span>;
  const change =
    achievementChange != null && Math.abs(achievementChange) >= 0.1
      ? `${achievementChange > 0 ? "+" : ""}${achievementChange.toFixed(0)}`
      : null;
  return (
    <span className={`flex items-center gap-1 text-xs ${COLOR[direction]}`}>
      {change ? <span className="tabular-nums">{change}</span> : null}
      <span aria-label={LABEL[direction]}>
        {ARROW[direction]} {LABEL[direction]}
      </span>
    </span>
  );
}
