import { useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { Area, AreaChart, ReferenceLine, ResponsiveContainer, XAxis } from "recharts";
import { api, type PhysiqueDistributionMetric } from "../lib/api";
import { bellCurve } from "../lib/stats";

/**
 * 体型の母集団分布。BMI / 体脂肪率 / FFMI について、日本人 同年代・同性の分布
 * (ベルカーブ) に自分の現在値を重ね、percentile で「現在地」を示す。
 * BMI は公的統計、体脂肪率/FFMI は文献の目安 (出典バッジで明示)。
 * 設計: docs/superpowers/specs/2026-06-23-fitness-history-and-body-distribution-design.md
 */
export function DistributionPanel() {
  const q = useQuery({ queryKey: ["physique-distribution"], queryFn: api.physiqueDistribution });
  const data = q.data;
  if (!data) return null;

  return (
    <section className="space-y-3 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 p-4 sm:p-5 ring-1 ring-slate-800">
      <div className="flex items-center gap-2">
        <Users size={16} className="text-sky-300" />
        <h3 className="text-sm tracking-wide text-slate-100">母集団での現在地</h3>
      </div>
      <p className="text-[11px] leading-relaxed text-slate-500">
        日本人 同年代・同性の分布に対する自分の位置。BMI に加え、筋肉質さ (FFMI) と
        最強の予後指標である心肺フィットネス (VO2max) も。
        {!data.evaluable && " 設定で生年月日・性別・身長を入れると percentile が出ます。"}
      </p>
      <div className="space-y-3">
        {data.metrics.map((m) => (
          <MetricChart key={m.key} m={m} />
        ))}
      </div>
    </section>
  );
}

function MetricChart({ m }: { m: PhysiqueDistributionMetric }) {
  const hasDist = m.value != null && m.mean != null && m.sd != null;

  return (
    <div className="rounded-xl bg-slate-950/40 p-3 ring-1 ring-slate-800/60">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-100">{m.label}</span>
          <span className="rounded-full bg-slate-800/80 px-2 py-0.5 text-[10px] text-slate-400">
            {m.source}
          </span>
        </div>
        {m.value != null ? (
          <span className="text-lg font-semibold tabular-nums text-slate-100">
            {m.value}
            <span className="ml-0.5 text-xs font-normal text-slate-400">{m.unit}</span>
          </span>
        ) : (
          <span className="text-[11px] text-slate-500">記録待ち</span>
        )}
      </div>

      {hasDist && (
        <>
          <div className="mt-2 h-20 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={bellCurve(m.mean!, m.sd!)} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
                <defs>
                  <linearGradient id={`fill-${m.key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#38bdf8" stopOpacity={0.03} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="x"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tick={{ fontSize: 9, fill: "#64748b" }}
                  tickFormatter={(v: number) => v.toFixed(0)}
                  interval="preserveStartEnd"
                />
                <Area
                  type="monotone"
                  dataKey="y"
                  stroke="#38bdf8"
                  strokeWidth={1}
                  fill={`url(#fill-${m.key})`}
                  isAnimationActive={false}
                />
                {/* 母集団平均 */}
                <ReferenceLine x={m.mean!} stroke="#475569" strokeDasharray="2 2" />
                {/* 目標 */}
                {m.target != null && (
                  <ReferenceLine
                    x={m.target}
                    stroke="#fbbf24"
                    strokeDasharray="4 2"
                    label={{ value: "目標", fontSize: 9, fill: "#fbbf24", position: "insideTopRight" }}
                  />
                )}
                {/* 現在値 */}
                <ReferenceLine x={m.value!} stroke="#38bdf8" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          {m.percentile != null ? (
            <div className="mt-1 text-[11px] text-slate-400">
              同年代・同性で{" "}
              <span className="font-semibold tabular-nums text-sky-300">
                {Math.round(m.percentile)}
              </span>
              <span className="text-slate-500"> パーセンタイル (下位からの位置)</span>
            </div>
          ) : (
            <div className="mt-1 text-[11px] text-slate-600">
              生年月日・性別・身長を設定すると現在地 (percentile) が出ます。
            </div>
          )}
        </>
      )}
    </div>
  );
}
