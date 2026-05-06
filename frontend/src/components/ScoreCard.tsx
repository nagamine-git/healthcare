type Props = {
  total: number | null;
};

function colorFor(score: number | null): string {
  if (score == null) return "stroke-slate-600";
  if (score >= 80) return "stroke-emerald-400";
  if (score >= 65) return "stroke-amber-300";
  if (score >= 50) return "stroke-orange-400";
  return "stroke-rose-400";
}

export function ScoreCard({ total }: Props) {
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  const value = total ?? 0;
  const dash = (value / 100) * circumference;

  return (
    <div className="flex items-center gap-6 rounded-2xl bg-slate-900/70 p-6 shadow-inner">
      <div className="relative h-44 w-44 shrink-0">
        <svg width="176" height="176" viewBox="0 0 176 176" className="-rotate-90">
          <circle cx="88" cy="88" r={radius} className="stroke-slate-800 fill-none" strokeWidth="12" />
          <circle
            cx="88"
            cy="88"
            r={radius}
            className={`fill-none ${colorFor(total)}`}
            strokeWidth="12"
            strokeDasharray={`${dash} ${circumference - dash}`}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-5xl font-light tabular-nums">
            {total != null ? Math.round(total) : "--"}
          </span>
          <span className="text-xs uppercase tracking-widest text-slate-400">
            Today
          </span>
        </div>
      </div>
      <div className="space-y-1">
        <h2 className="text-sm uppercase tracking-widest text-slate-400">
          Composite Score
        </h2>
        <p className="text-slate-200 text-2xl font-light leading-tight">
          {total == null ? "計算中..." : labelFor(total)}
        </p>
        <p className="text-slate-400 text-sm">28日のベースラインに対する総合評価です。</p>
      </div>
    </div>
  );
}

function labelFor(score: number): string {
  if (score >= 80) return "コンディション良好";
  if (score >= 65) return "おおむね順調";
  if (score >= 50) return "やや疲労気味";
  return "回復を優先";
}
