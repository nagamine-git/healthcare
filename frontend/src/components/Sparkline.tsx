import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip } from "recharts";
import type { TimeseriesPoint, TrendMetric } from "../lib/api";
import { TrendBadge } from "./TrendBadge";

type Props = {
  label: string;
  data: TimeseriesPoint[];
  formatter?: (v: number) => string;
  color?: string;
  trend?: TrendMetric;
};

export function Sparkline({ label, data, formatter, color = "#34d399", trend }: Props) {
  const filtered = data.filter((p) => p.value != null);
  return (
    <div className="rounded-2xl bg-slate-900/70 p-4">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-xs uppercase tracking-wider text-slate-400">
          {label}
        </span>
        {trend ? (
          <TrendBadge direction={trend.direction} achievementChange={trend.achievement_prev_day_change} />
        ) : (
          <span className="text-xs text-slate-500">
            {filtered.length > 0 ? `${filtered.length} 日` : ""}
          </span>
        )}
      </div>
      <div className="h-24">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={filtered}>
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "1px solid #334155",
                fontSize: 12,
              }}
              labelFormatter={(v) => v}
              formatter={(v: number) => (formatter ? formatter(v) : v.toFixed(1))}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
