type Sub = {
  label: string;
  value: number | null;
};

type Props = {
  subs: Sub[];
};

function barColor(score: number | null): string {
  if (score == null) return "bg-slate-700";
  if (score >= 80) return "bg-emerald-500";
  if (score >= 65) return "bg-amber-400";
  if (score >= 50) return "bg-orange-500";
  return "bg-rose-500";
}

export function SubScoreBar({ subs }: Props) {
  return (
    <div className="grid grid-cols-1 gap-4 rounded-2xl bg-slate-900/70 p-6 sm:grid-cols-5">
      {subs.map((s) => (
        <div key={s.label} className="space-y-2">
          <div className="flex items-baseline justify-between">
            <span className="text-xs uppercase tracking-wider text-slate-400">
              {s.label}
            </span>
            <span className="text-lg font-light tabular-nums">
              {s.value == null ? "--" : Math.round(s.value)}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className={`h-full ${barColor(s.value)} transition-all`}
              style={{ width: `${(s.value ?? 0).toFixed(0)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
