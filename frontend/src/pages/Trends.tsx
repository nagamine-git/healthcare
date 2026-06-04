import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, Line, LineChart, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../lib/api";
import type { TrendDirection, TrendMetric, TrendMetricKey } from "../lib/api";

type Props = { onBack?: () => void };

const ORDER: TrendMetricKey[] = ["sleep", "hrv", "energy", "load", "weight", "body_fat"];

const DIR_LABEL: Record<TrendDirection, string> = {
  improving: "改善傾向", stable: "横ばい", declining: "低下傾向",
};
const DIR_COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400", stable: "text-slate-400", declining: "text-rose-400",
};
const LINE = "#34d399";
const BAND = "#34d39922";

function TrendCard({ metric, granularity }: { metric: TrendMetric; granularity: "daily" | "weekly" }) {
  const data = metric.raw_series;
  const dir = metric.direction;
  const wow = metric.achievement_week_over_week;
  const ideal = metric.ideal;

  const reg =
    metric.regression && metric.regression.start.value != null && metric.regression.end.value != null
      ? [
          { date: metric.regression.start.date, value: metric.regression.start.value },
          { date: metric.regression.end.date, value: metric.regression.end.value },
        ]
      : null;
  const merged = data.map((p) => {
    if (!reg) return { ...p } as { date: string; value: number | null; reg?: number };
    if (p.date === reg[0].date) return { ...p, reg: reg[0].value };
    if (p.date === reg[1].date) return { ...p, reg: reg[1].value };
    return { ...p };
  });

  // 理想帯/ラインが範囲外でも見えるよう、Y軸ドメインを理想値込みに広げる。
  const lowFn = (dMin: number) =>
    ideal.type === "band"
      ? Math.min(dMin, ideal.lo)
      : ideal.good_line != null
      ? Math.min(dMin, ideal.good_line)
      : dMin;
  const highFn = (dMax: number) =>
    ideal.type === "band"
      ? Math.max(dMax, ideal.hi)
      : ideal.good_line != null
      ? Math.max(dMax, ideal.good_line)
      : dMax;

  const idealOverlay =
    ideal.type === "band" ? (
      <ReferenceArea y1={ideal.lo} y2={ideal.hi} fill={BAND} stroke="none" />
    ) : ideal.good_line != null ? (
      <ReferenceLine y={ideal.good_line} stroke="#64748b" strokeDasharray="3 3" />
    ) : null;

  const tooltipStyle = {
    backgroundColor: "#1e293b",
    border: "1px solid #334155",
    fontSize: 12,
  };

  return (
    <div className="rounded-2xl bg-slate-900/70 p-4">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm text-slate-200">{metric.label}</span>
        <span className="text-2xl font-light tabular-nums text-slate-100">
          {metric.current_raw != null ? `${metric.current_raw}${metric.unit}` : "--"}
        </span>
      </div>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className={dir ? DIR_COLOR[dir] : "text-slate-600"}>
          {dir ? DIR_LABEL[dir] : "データ不足"}
          {metric.achievement != null ? ` · 達成度 ${Math.round(metric.achievement)}` : ""}
        </span>
        <span className="text-slate-500">
          {wow ? `前週比 ${wow.delta > 0 ? "+" : ""}${wow.delta.toFixed(0)}` : ""}
        </span>
      </div>
      <div className="h-32">
        <ResponsiveContainer width="100%" height="100%">
          {granularity === "weekly" ? (
            <BarChart data={merged}>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={[lowFn, highFn]} />
              <Tooltip contentStyle={tooltipStyle} />
              {idealOverlay}
              <Bar dataKey="value" fill={LINE} radius={[3, 3, 0, 0]} />
            </BarChart>
          ) : (
            <LineChart data={merged}>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={[lowFn, highFn]} />
              <Tooltip contentStyle={tooltipStyle} />
              {idealOverlay}
              <Line type="monotone" dataKey="value" stroke={LINE} strokeWidth={2} dot={false} />
              {reg ? (
                <Line type="linear" dataKey="reg" stroke="#f59e0b" strokeWidth={1.5}
                      strokeDasharray="5 4" dot={false} connectNulls />
              ) : null}
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
          <button onClick={onBack}
            className="rounded-lg bg-slate-800/70 px-2 py-1 text-xs text-slate-300 hover:bg-slate-700">← 戻る</button>
          <span className="text-sm text-slate-200">トレンド(理想への接近度)</span>
        </div>
        <div className="flex rounded-lg bg-slate-800/70 p-0.5 text-xs">
          <button onClick={() => setGranularity("daily")}
            className={`rounded-md px-3 py-1 ${granularity === "daily" ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>日次</button>
          <button onClick={() => setGranularity("weekly")}
            className={`rounded-md px-3 py-1 ${granularity === "weekly" ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>週次</button>
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
