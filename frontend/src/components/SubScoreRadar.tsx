import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

type Sub = {
  label: string;
  value: number | null;
  reason?: string;
};

type Props = {
  subs: Sub[];
  total: number | null;
};

function totalLabel(score: number | null): string {
  if (score == null) return "計算中";
  if (score >= 80) return "コンディション良好";
  if (score >= 65) return "おおむね順調";
  if (score >= 50) return "やや疲労気味";
  return "回復を優先";
}

function totalColor(score: number | null): string {
  if (score == null) return "text-slate-500";
  if (score >= 80) return "text-emerald-400";
  if (score >= 65) return "text-amber-300";
  if (score >= 50) return "text-orange-400";
  return "text-rose-400";
}

export function SubScoreRadar({ subs, total }: Props) {
  const measured = subs.filter((s) => s.value != null);
  const learning = subs.filter((s) => s.value == null);

  const data = measured.map((s) => ({
    axis: s.label,
    score: s.value as number,
  }));

  const canDrawRadar = data.length >= 3;

  return (
    <div className="rounded-2xl bg-slate-900/70 p-4 sm:p-6">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-3">
          <h3 className="text-sm uppercase tracking-widest text-slate-400">
            総合スコア
          </h3>
          <span className={`text-3xl font-light tabular-nums ${totalColor(total)}`}>
            {total != null ? Math.round(total) : "--"}
          </span>
          <span className="text-xs text-slate-400">
            {totalLabel(total)}
          </span>
        </div>
        <span className="text-[10px] text-slate-500">
          各軸 0–100 (28日ベースライン基準)
        </span>
      </div>

      <div className="h-72 sm:h-80">
        {canDrawRadar ? (
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={data} outerRadius="78%">
              <PolarGrid stroke="#1e293b" />
              <PolarAngleAxis
                dataKey="axis"
                tick={{ fill: "#cbd5e1", fontSize: 12 }}
              />
              <PolarRadiusAxis
                angle={90}
                domain={[0, 100]}
                tick={{ fill: "#475569", fontSize: 10 }}
                stroke="#334155"
                tickCount={5}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1e293b",
                  border: "1px solid #334155",
                  fontSize: 12,
                }}
                formatter={(v: number) => [Math.round(v).toString(), "score"]}
              />
              <Radar
                dataKey="score"
                stroke="#34d399"
                fill="#34d399"
                fillOpacity={0.35}
                isAnimationActive={false}
              />
            </RadarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">
            計測可能な軸が 3 つ以上揃うとレーダーが表示されます
          </div>
        )}
      </div>

      {learning.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2 border-t border-slate-800 pt-3">
          {learning.map((s) => (
            <span
              key={s.label}
              className="inline-flex items-center gap-1 rounded-full bg-slate-800/70 px-3 py-1 text-xs text-slate-400"
              title={s.reason}
            >
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400/70" />
              {s.label}: {s.reason ?? "—"}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
