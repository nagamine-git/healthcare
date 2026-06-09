import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, ComposedChart, Line, LineChart, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../lib/api";
import type { TrendDirection, TrendMetric, TrendMetricKey } from "../lib/api";
import { MetricTile } from "./MetricTile";

const ORDER: TrendMetricKey[] = [
  "sleep", "hrv", "energy", "readiness", "load",
  "spo2", "respiration", "rhr_night", "sleep_midpoint",
  "weight", "body_fat",
];

const DIR_LABEL: Record<TrendDirection, string> = {
  improving: "改善傾向", stable: "横ばい", declining: "低下傾向",
};
const DIR_COLOR: Record<TrendDirection, string> = {
  improving: "text-emerald-400", stable: "text-slate-400", declining: "text-rose-400",
};
const LINE = "#34d399";
const BAND = "#34d39922";
const REG = "#f59e0b";
const TICK = { fontSize: 10, fill: "#64748b" } as const;

/** 355 → "5時間55分" (睡眠の分表示を読みやすくする) */
function fmtSleepMin(v: number): string {
  const h = Math.floor(v / 60);
  const m = Math.round(v % 60);
  return `${h}時間${m.toString().padStart(2, "0")}分`;
}

/** 3.25 → "3:15" (睡眠中点の時刻表示) */
function fmtClockHour(v: number): string {
  const h = Math.floor(v);
  const m = Math.round((v - h) * 60);
  return `${h}:${m.toString().padStart(2, "0")}`;
}

function fmtCurrent(metricKey: TrendMetricKey, metric: TrendMetric): string {
  if (metric.current_raw == null) return "--";
  if (metricKey === "sleep") return fmtSleepMin(metric.current_raw);
  if (metricKey === "sleep_midpoint") return fmtClockHour(metric.current_raw);
  return `${metric.current_raw}${metric.unit}`;
}

/** Y軸目盛: 睡眠は時間単位、中点は時刻、他は小数1桁まで */
function fmtTick(metricKey: TrendMetricKey, v: number): string {
  if (metricKey === "sleep") return `${Math.round(v / 60)}h`;
  if (metricKey === "sleep_midpoint") return fmtClockHour(v);
  return Number.isInteger(v) ? `${v}` : v.toFixed(1);
}

/** X軸目盛: "2026-05-10" → "5/10" */
function fmtDate(d: string): string {
  const parts = d.split("-");
  return parts.length === 3 ? `${+parts[1]}/${+parts[2]}` : d;
}

/** 28日回帰の傾向と前週比の符号が食い違うとき、傾向ラベルは出さない
 * (「改善傾向・前週比 -20」のような矛盾表示を避ける。数字に語らせる) */
export function resolveDirection(
  dir: TrendDirection | null | undefined,
  wowDelta: number | null | undefined,
): TrendDirection | null {
  if (!dir) return null;
  if (wowDelta == null) return dir;
  if (dir === "improving" && wowDelta < 0) return null;
  if (dir === "declining" && wowDelta > 0) return null;
  return dir;
}

function TrendCard({ metricKey, metric, granularity, hint }: {
  metricKey: TrendMetricKey;
  metric: TrendMetric;
  granularity: "daily" | "weekly";
  hint?: string;
}) {
  const data = metric.raw_series;
  const wow = metric.achievement_week_over_week;
  const dir = resolveDirection(metric.direction, wow?.delta);
  const ideal = metric.ideal;
  // 達成度が十分高い間は「低下傾向」を警告色にしない (理想圏内のゆらぎは騒がない)
  const calm = metric.achievement != null && metric.achievement >= 90;

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

  const regLine = reg ? (
    <Line type="linear" dataKey="reg" stroke={REG} strokeWidth={1.5}
          strokeDasharray="5 4" dot={false} connectNulls />
  ) : null;

  const tooltipStyle = {
    backgroundColor: "#1e293b",
    border: "1px solid #334155",
    fontSize: 12,
  };
  const tooltipFormatter = (v: number | string) => {
    if (typeof v !== "number") return `${v}${metric.unit}`;
    if (metricKey === "sleep") return fmtSleepMin(v);
    if (metricKey === "sleep_midpoint") return fmtClockHour(v);
    return `${v}${metric.unit}`;
  };

  const xAxis = (
    <XAxis dataKey="date" tickFormatter={fmtDate} tick={TICK}
           tickLine={false} axisLine={false} minTickGap={32} interval="preserveStartEnd" />
  );
  const yAxis = (
    <YAxis domain={[lowFn, highFn]} tick={TICK} tickFormatter={(v: number) => fmtTick(metricKey, v)}
           tickLine={false} axisLine={false} width={34} tickCount={4} />
  );

  return (
    <div className="rounded-2xl bg-slate-900/70 p-4">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm text-slate-200">{metric.label}</span>
        <span className="text-2xl font-light tabular-nums text-slate-100">
          {fmtCurrent(metricKey, metric)}
        </span>
      </div>
      {hint ? <div className="mb-1 text-xs text-slate-500">{hint}</div> : null}
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className={dir ? (calm ? "text-slate-400" : DIR_COLOR[dir]) : "text-slate-600"}>
          {dir ? DIR_LABEL[dir] : metric.direction ? "横ばい圏" : "データ不足"}
          {metric.achievement != null ? ` · 達成度 ${Math.round(metric.achievement)}` : ""}
        </span>
        <span className="text-slate-500">
          {wow ? `前週比 ${wow.delta > 0 ? "+" : ""}${wow.delta.toFixed(0)}` : ""}
        </span>
      </div>
      <div className="h-36">
        <ResponsiveContainer width="100%" height="100%">
          {granularity === "weekly" ? (
            <ComposedChart data={merged}>
              {xAxis}
              {yAxis}
              <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
              {idealOverlay}
              <Bar dataKey="value" fill={LINE} radius={[3, 3, 0, 0]} />
              {regLine}
            </ComposedChart>
          ) : (
            <LineChart data={merged}>
              {xAxis}
              {yAxis}
              <Tooltip contentStyle={tooltipStyle} formatter={tooltipFormatter} />
              {idealOverlay}
              <Line type="monotone" dataKey="value" stroke={LINE} strokeWidth={2} dot={false} />
              {regLine}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export type TrendExtra = { label: string; value: string; hint?: string };

export function TrendsSection({ hints, extras }: {
  hints?: Partial<Record<TrendMetricKey, string>>;
  extras?: TrendExtra[];
}) {
  const [granularity, setGranularity] = useState<"daily" | "weekly">("daily");
  const query = useQuery({
    queryKey: ["trends", granularity],
    queryFn: () => api.trends(granularity, granularity === "weekly" ? 84 : 28),
  });

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wider text-slate-400">
          トレンド(理想への接近度)
        </span>
        <div className="flex rounded-lg bg-slate-800/70 p-0.5 text-xs">
          <button onClick={() => setGranularity("daily")}
            className={`rounded-md px-3 py-1 ${granularity === "daily" ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>日次</button>
          <button onClick={() => setGranularity("weekly")}
            className={`rounded-md px-3 py-1 ${granularity === "weekly" ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>週次</button>
        </div>
      </div>
      {query.isLoading ? (
        <div className="text-sm text-slate-400">読み込み中...</div>
      ) : query.isError || !query.data ? (
        <div className="text-sm text-rose-400">トレンド取得に失敗しました</div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ORDER.map((key) => {
            const m = query.data.metrics[key];
            if (!m) return null; // 生理指標はデータが入るまで非表示
            return (
              <TrendCard key={key} metricKey={key} metric={m}
                         granularity={granularity} hint={hints?.[key] ?? m.subtitle ?? undefined} />
            );
          })}
          {extras && extras.length > 0 ? (
            <div className="grid grid-cols-2 gap-3">
              {extras.map((e) => (
                <MetricTile key={e.label} label={e.label} value={e.value} hint={e.hint} />
              ))}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
