import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api";
import type { TrendDirection, TrendMetric, TrendMetricKey } from "../lib/api";

type Props = {
  onBack?: () => void;
};

const ORDER: TrendMetricKey[] = [
  "total",
  "sleep",
  "hrv",
  "body_battery",
  "load",
  "weight",
  "body_fat",
];

const DIRECTION_LABEL: Record<TrendDirection, string> = {
  improving: "改善傾向",
  stable: "横ばい",
  declining: "低下傾向",
};

const DIRECTION_COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400",
  stable: "text-slate-400",
  declining: "text-rose-400",
};

const LINE_COLOR = "#34d399";

function TrendCard({
  metric,
  granularity,
}: {
  metric: TrendMetric;
  granularity: "daily" | "weekly";
}) {
  const data = metric.series;
  const dir = metric.direction;
  const wow = metric.week_over_week;
  return (
    <div className="rounded-2xl bg-slate-900/70 p-4">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm text-slate-200">{metric.label}</span>
        <span className="text-2xl font-light tabular-nums text-slate-100">
          {metric.current != null ? Math.round(metric.current) : "--"}
        </span>
      </div>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className={dir ? DIRECTION_COLOR[dir] : "text-slate-600"}>
          {dir ? DIRECTION_LABEL[dir] : "データ不足"}
        </span>
        <span className="text-slate-500">
          {metric.prev_day_change != null
            ? `前日比 ${metric.prev_day_change > 0 ? "+" : ""}${metric.prev_day_change.toFixed(1)}`
            : ""}
          {wow ? ` / 前週比 ${wow.delta > 0 ? "+" : ""}${wow.delta.toFixed(1)}` : ""}
        </span>
      </div>
      <div className="h-28">
        <ResponsiveContainer width="100%" height="100%">
          {granularity === "weekly" ? (
            <BarChart data={data}>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", fontSize: 12 }}
                formatter={(v: number) => v.toFixed(1)}
              />
              <Bar dataKey="value" fill={LINE_COLOR} radius={[3, 3, 0, 0]} />
            </BarChart>
          ) : (
            <LineChart data={data}>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", fontSize: 12 }}
                formatter={(v: number) => v.toFixed(1)}
              />
              <Line type="monotone" dataKey="value" stroke={LINE_COLOR} strokeWidth={2} dot={false} />
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function TrendsPage({ onBack }: Props) {
  const [granularity, setGranularity] = useState<"daily" | "weekly">("daily");
  const query = useQuery({
    queryKey: ["trends", granularity],
    queryFn: () => api.trends(granularity, granularity === "weekly" ? 84 : 28),
  });

  return (
    <main className="safe-area-x safe-area-bottom mx-auto max-w-5xl space-y-6 px-4 pb-8 sm:px-8">
      <header className="safe-area-top flex items-center justify-between pb-2 pt-3">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="rounded-lg bg-slate-800/70 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700"
          >
            ← 戻る
          </button>
          <span className="text-sm text-slate-200">トレンド</span>
        </div>
        <div className="flex rounded-lg bg-slate-800/70 p-0.5 text-xs">
          <button
            onClick={() => setGranularity("daily")}
            className={`rounded-md px-3 py-1 ${
              granularity === "daily" ? "bg-slate-600 text-slate-100" : "text-slate-400"
            }`}
          >
            日次
          </button>
          <button
            onClick={() => setGranularity("weekly")}
            className={`rounded-md px-3 py-1 ${
              granularity === "weekly" ? "bg-slate-600 text-slate-100" : "text-slate-400"
            }`}
          >
            週次
          </button>
        </div>
      </header>

      {query.isLoading ? (
        <div className="text-slate-400">読み込み中...</div>
      ) : query.isError || !query.data ? (
        <div className="text-rose-400">取得に失敗しました</div>
      ) : (
        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ORDER.map((key) => (
            <TrendCard key={key} metric={query.data.metrics[key]} granularity={granularity} />
          ))}
        </section>
      )}
    </main>
  );
}
