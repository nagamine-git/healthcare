import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

export type Sub = {
  label: string;
  value: number | null;
  /** 各サブスコアの理論的な「理想値」(=目標到達時に取り得る最大点)。
   *  例: weight=80, body_fat=90, training_load=85, それ以外=100 */
  ideal: number;
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

/** 達成率 (現状/理想) → HSL 色。
 *  100% → emerald (140°), 50% → amber (50°), 0% → rose (5°)
 *  グラデーション補間で「ちょっと未達は控えめに赤」を実現する。 */
function gradientHsl(ratio: number): string {
  const r = Math.max(0, Math.min(1, ratio));
  // hue: 0%→5(rose), 50%→50(amber), 100%→140(emerald)
  // 二段の linear interpolation で滑らかに
  let hue: number;
  if (r < 0.5) {
    hue = 5 + (50 - 5) * (r / 0.5);
  } else {
    hue = 50 + (140 - 50) * ((r - 0.5) / 0.5);
  }
  const sat = 65 + 10 * r; // 高い方が彩度↑
  const lit = 50 + 5 * r;
  return `hsl(${Math.round(hue)} ${Math.round(sat)}% ${Math.round(lit)}%)`;
}

function totalColor(score: number | null): string {
  if (score == null) return "#94a3b8";
  return gradientHsl(score / 100);
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
          <h3 className="text-sm tracking-wider text-slate-300">総合スコア</h3>
          <span
            className="text-3xl font-light tabular-nums"
            style={{ color: totalColor(total) }}
          >
            {total != null ? Math.round(total) : "--"}
          </span>
          <span className="text-xs text-slate-400">{totalLabel(total)}</span>
        </div>
        <span className="text-[10px] text-slate-500">
          各軸 0–100 (28日ベースライン基準)
        </span>
      </div>

      <div className="h-64 sm:h-72">
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
                fillOpacity={0.25}
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

      {/* ギャップパネル: 各軸の現状/理想/差分 をグラデーションバーで */}
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 sm:gap-x-4">
        {subs.map((s) => (
          <GapRow key={s.label} sub={s} />
        ))}
      </div>

      {/* 学習中バッジ */}
      {learning.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-800 pt-3">
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

function GapRow({ sub }: { sub: Sub }) {
  const { label, value, ideal } = sub;
  const ratio = value == null ? 0 : Math.max(0, Math.min(1, value / ideal));
  const color = value == null ? "#475569" : gradientHsl(ratio);
  const gap = value == null ? null : Math.round(ideal - value);
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-slate-300">{label}</span>
        <span className="tabular-nums text-slate-400">
          {value == null ? (
            <span className="text-amber-400/70">--</span>
          ) : (
            <>
              <span style={{ color }}>{Math.round(value)}</span>
              <span className="text-slate-600"> / </span>
              <span className="text-slate-500">{ideal}</span>
              {gap != null && gap > 0 && (
                <span className="ml-1 text-[10px] text-slate-500">(−{gap})</span>
              )}
            </>
          )}
        </span>
      </div>
      <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${Math.round(ratio * 100)}%`,
            background: color,
          }}
        />
        {/* 理想ラインの目印 */}
        <div className="absolute right-0 top-0 h-full w-px bg-slate-600" />
      </div>
    </div>
  );
}
