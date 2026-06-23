import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Users } from "lucide-react";
import { useState } from "react";
import { Area, AreaChart, ReferenceArea, ReferenceLine, ResponsiveContainer, XAxis } from "recharts";
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
  const showVo2Help = m.key === "vo2max" && m.value == null;

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
                {/* 目標範囲 (帯) — low<high のとき */}
                {m.target_low != null && m.target_high != null && m.target_high > m.target_low && (
                  <ReferenceArea
                    x1={m.target_low}
                    x2={m.target_high}
                    fill="#fbbf24"
                    fillOpacity={0.15}
                    stroke="#fbbf24"
                    strokeOpacity={0.4}
                    label={{ value: "目標", fontSize: 9, fill: "#fbbf24", position: "insideTop" }}
                  />
                )}
                {/* 目標が点 (FFMI など low==high) のとき */}
                {m.target_low != null && m.target_high === m.target_low && (
                  <ReferenceLine
                    x={m.target_low}
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
          <div className="mt-1 flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5">
            {m.percentile != null ? (
              <span className="text-[11px] text-slate-400">
                同年代・同性で{" "}
                <span className="font-semibold tabular-nums text-sky-300">
                  {Math.round(m.percentile)}
                </span>
                <span className="text-slate-500"> パーセンタイル (下位からの位置)</span>
              </span>
            ) : (
              <span className="text-[11px] text-slate-600">
                生年月日・性別・身長を設定すると現在地 (percentile) が出ます。
              </span>
            )}
            {m.target_low != null && (
              <span className="text-[11px] text-amber-300/80">
                <span className="text-slate-500">目標 </span>
                <span className="tabular-nums">
                  {m.target_high != null && m.target_high > m.target_low
                    ? `${m.target_low}–${m.target_high}`
                    : m.target_low}
                </span>
                {m.unit && <span className="text-slate-500">{m.unit}</span>}
              </span>
            )}
          </div>
        </>
      )}
      {showVo2Help && <Vo2MaxHelp />}
    </div>
  );
}

/** VO2max が未取得のときの取得方法ヘルプ (Garmin Instinct 3 前提)。 */
function Vo2MaxHelp() {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 border-t border-slate-800/50 pt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-[11px] text-sky-300/80 hover:text-sky-300"
      >
        VO2maxの取得方法
        <ChevronDown size={13} className={open ? "rotate-180 transition" : "transition"} />
      </button>
      {open && (
        <div className="mt-1.5 space-y-1 text-[11px] leading-relaxed text-slate-400">
          <p>
            Garmin (Instinct 3) は<strong className="text-slate-300">屋外ランニング</strong>から推定します。
            GPSオンで、<strong className="text-slate-300">最大心拍の70%以上を10分以上</strong>継続するのが条件 (週1回が目安)。
          </p>
          <p>
            サイクリングでも出ますが<strong className="text-slate-300">パワーメーター必須</strong> (高強度20分以上)。
          </p>
          <p className="text-slate-500">
            筋トレ・ラッキング・ボクシング・屋内ランは対象外 (VO2maxは生成されません)。
            ウォーキングは直近30日にランの推定が無いときだけ代替で出ることがあります。
          </p>
          <p className="text-slate-500">
            → 一度<strong className="text-slate-300">屋外ランを1本</strong>走れば値が入り、ここに分布が出ます。
          </p>
        </div>
      )}
    </div>
  );
}
