import { Area, AreaChart, ReferenceArea, ReferenceLine, ResponsiveContainer, XAxis } from "recharts";
import { bellCurve } from "../lib/stats";

/**
 * 母集団分布の釣鐘 (正規 pdf) に、母集団平均・現在値・(任意で)目標範囲/点を重ねる。
 * 体型分布と体力テスト分布の両方で再利用する。
 */
export function BellCurve({
  idKey,
  value,
  mean,
  sd,
  targetLow,
  targetHigh,
}: {
  idKey: string;
  value: number;
  mean: number;
  sd: number;
  targetLow?: number | null;
  targetHigh?: number | null;
}) {
  return (
    <div className="mt-2 h-20 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={bellCurve(mean, sd)} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
          <defs>
            <linearGradient id={`fill-${idKey}`} x1="0" y1="0" x2="0" y2="1">
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
            fill={`url(#fill-${idKey})`}
            isAnimationActive={false}
          />
          {/* 母集団平均 */}
          <ReferenceLine x={mean} stroke="#475569" strokeDasharray="2 2" />
          {/* 目標範囲 (帯) */}
          {targetLow != null && targetHigh != null && targetHigh > targetLow && (
            <ReferenceArea
              x1={targetLow}
              x2={targetHigh}
              fill="#fbbf24"
              fillOpacity={0.15}
              stroke="#fbbf24"
              strokeOpacity={0.4}
              label={{ value: "目標", fontSize: 9, fill: "#fbbf24", position: "insideTop" }}
            />
          )}
          {/* 目標が点 */}
          {targetLow != null && targetHigh === targetLow && (
            <ReferenceLine
              x={targetLow}
              stroke="#fbbf24"
              strokeDasharray="4 2"
              label={{ value: "目標", fontSize: 9, fill: "#fbbf24", position: "insideTopRight" }}
            />
          )}
          {/* 現在値 */}
          <ReferenceLine x={value} stroke="#38bdf8" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
