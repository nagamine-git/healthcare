import { useQuery } from "@tanstack/react-query";
import { BedDouble, CheckCircle2, CircleAlert } from "lucide-react";
import { api } from "../lib/api";
import type { SleepQualityComponent, SleepQualityImprovement } from "../lib/api";

/**
 * 「昨夜の睡眠の質」の評価 + 具体的な改善点。睡眠タブの先頭に置く。
 *
 * 睡眠タブの他のカード (WindDownCard 等) はすべて「今夜どうするか」だが、
 * これだけが「昨夜どうだったか」を振り返る。深睡眠/REM/効率/中途覚醒を
 * 個別に見せることで、「6.2h」という合計時間だけでは分からない
 * 「どの成分が崩れているか」を一目で伝える。
 *
 * データが無い(available:false)/ロード中は何も出さない (捏造しない、静かに黙る)。
 */
const VERDICT_TONE: Record<string, { icon: typeof CheckCircle2; text: string; ring: string }> = {
  good: { icon: CheckCircle2, text: "text-prog-300", ring: "border-prog/30 bg-prog/[0.06]" },
  mixed: { icon: BedDouble, text: "text-info", ring: "border-info/30 bg-info/[0.06]" },
  poor: { icon: CircleAlert, text: "text-risk", ring: "border-risk/30 bg-risk/[0.06]" },
};

const STATUS_LABEL: Record<string, string> = { good: "良好", low: "低い", high: "多い" };
const STATUS_TONE: Record<string, string> = {
  good: "text-prog-300", low: "text-risk", high: "text-risk",
};

function fmtMin(min: number | null): string | null {
  if (min == null) return null;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h${m.toString().padStart(2, "0")}m` : `${m}分`;
}

function ComponentRow({ c }: { c: SleepQualityComponent }) {
  const value = c.pct != null ? `${c.pct.toFixed(1)}%` : fmtMin(c.minutes) ?? "-";
  return (
    <div className="flex items-center gap-2 rounded-lg bg-void/30 px-2.5 py-2 text-[11px]">
      <span className="min-w-0 flex-1 truncate text-ink-dim">{c.label}</span>
      {c.minutes != null && c.pct != null && (
        <span className="shrink-0 text-ink-faint">{fmtMin(c.minutes)}</span>
      )}
      <span className="shrink-0 font-semibold tabular-nums text-ink">{value}</span>
      <span className={`shrink-0 w-9 text-right text-[10px] font-semibold ${STATUS_TONE[c.status] ?? "text-ink-faint"}`}>
        {STATUS_LABEL[c.status] ?? c.status}
      </span>
      <span className="shrink-0 text-[9px] text-ink-faint">目安{c.reference}</span>
    </div>
  );
}

function ImprovementRow({ imp }: { imp: SleepQualityImprovement }) {
  const personal = imp.basis === "personal";
  return (
    <div className="space-y-0.5 rounded-lg bg-indigo-500/10 p-2.5">
      <div className="flex items-center gap-1.5">
        {personal && (
          <span className="rounded bg-indigo-400/20 px-1.5 py-0.5 text-[9px] font-semibold text-indigo-200">
            あなたのデータでは
          </span>
        )}
        <span className="text-[12px] text-ink">{imp.text}</span>
      </div>
      <div className="text-[10px] text-ink-faint">{imp.why}</div>
    </div>
  );
}

export function LastNightPanel() {
  const q = useQuery({ queryKey: ["last-night"], queryFn: api.lastNight, staleTime: 60_000 });
  const d = q.data;
  if (!d || !d.available || !d.components || d.components.length === 0) return null;

  const tone = VERDICT_TONE[d.verdict ?? "mixed"] ?? VERDICT_TONE.mixed;
  const Icon = tone.icon;

  return (
    <section className={`space-y-2.5 rounded-card border p-4 ${tone.ring}`}>
      <div className="flex items-center gap-2">
        <Icon size={16} strokeWidth={2.2} className={tone.text} />
        <span className={`text-[13px] font-semibold ${tone.text}`}>昨夜の睡眠</span>
        {d.sleep_score != null && (
          <span className="ml-auto text-[11px] text-ink-faint">スコア {Math.round(d.sleep_score)}</span>
        )}
      </div>
      <p className="text-[12px] leading-relaxed text-ink-dim">{d.headline}</p>

      <div className="space-y-1">
        {d.components.map((c) => (
          <ComponentRow key={c.key} c={c} />
        ))}
      </div>

      {d.improvements && d.improvements.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold text-indigo-200">改善点</div>
          {d.improvements.map((imp, i) => (
            <ImprovementRow key={i} imp={imp} />
          ))}
        </div>
      )}
    </section>
  );
}
