/**
 * ファーストビューの「今の要点」。総合スコア + 最優先の一言 + 主要サブスコア。
 * 認知負荷を下げるため、スクロール前にこの1枚で全体像を掴ませる。
 */

function scoreColor(v: number | null): string {
  if (v == null) return "#64748b";
  if (v >= 75) return "#34d399";
  if (v >= 50) return "#fbbf24";
  return "#fb7185";
}

type Sub = { label: string; value: number | null };

export function TodaySummary({ total, headline, subs }: {
  total: number | null;
  headline?: string;
  subs: Sub[];
}) {
  return (
    <div className="rounded-2xl border border-slate-800/80 bg-gradient-to-br from-slate-900/90 to-slate-900/40 p-4">
      <div className="flex items-center gap-4">
        <div className="shrink-0 text-center">
          <div className="text-[34px] font-bold leading-none tabular-nums" style={{ color: scoreColor(total) }}>
            {total != null ? Math.round(total) : "--"}
          </div>
          <div className="mt-0.5 text-[9px] uppercase tracking-wider text-slate-500">総合</div>
        </div>
        <div className="min-w-0 flex-1">
          {headline && (
            <div className="text-[13px] font-medium leading-snug text-slate-100">{headline}</div>
          )}
          <div className="mt-2 grid grid-cols-3 gap-2">
            {subs.map((s) => (
              <div key={s.label}>
                <div className="flex items-baseline justify-between">
                  <span className="text-[9px] text-slate-500">{s.label}</span>
                  <span className="text-[11px] font-semibold tabular-nums" style={{ color: scoreColor(s.value) }}>
                    {s.value != null ? Math.round(s.value) : "--"}
                  </span>
                </div>
                <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-slate-800">
                  <div className="h-full rounded-full" style={{ width: `${Math.max(s.value ?? 0, 2)}%`, background: scoreColor(s.value) }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
