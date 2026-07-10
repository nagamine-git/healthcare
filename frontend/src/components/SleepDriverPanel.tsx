import { useQuery } from "@tanstack/react-query";
import { Moon } from "lucide-react";
import { api } from "../lib/api";
import type { SleepDriverFactor } from "../lib/api";
import { LoadingState } from "./ui/cockpit";

/**
 * 個人「睡眠ドライバー分析」。何が睡眠の質・翌日パフォーマンスを上げ下げするかを
 * 並べ替え検定+BH-FDR で出す。確度(tier)で濃淡、件数が少なければ薄く・控えめに。
 */

// 確度 → 不透明度 (薄さ)
const TIER_OP: Record<string, string> = {
  strong: "opacity-100", suggestive: "opacity-90", trend: "opacity-70",
  weak: "opacity-45", preliminary: "opacity-60",
};
const TIER_LABEL: Record<string, string> = {
  strong: "強い", suggestive: "示唆", trend: "傾向", weak: "弱い", preliminary: "暫定",
};

function Factor({ f }: { f: SleepDriverFactor }) {
  const good = f.direction === "改善";
  return (
    <div className={`flex items-baseline gap-2 text-[11px] ${TIER_OP[f.tier]}`}>
      <span className="min-w-0 flex-1 truncate text-ink-dim">
        {f.label} <span className="text-ink-faint">→ {f.outcome_label}</span>
      </span>
      <span className={`shrink-0 font-semibold ${good ? "text-prog-300" : "text-risk"}`}>
        {good ? "↑改善" : "↓悪化"}
      </span>
      <span className="shrink-0 text-[9px] text-ink-faint">{TIER_LABEL[f.tier]} n{f.n}</span>
    </div>
  );
}

export function SleepDriverPanel() {
  const q = useQuery({ queryKey: ["sleep-drivers"], queryFn: api.sleepDrivers });
  if (q.isLoading) return <LoadingState height="h-40" />;
  if (!q.data) return null;
  const s = q.data;
  if (s.status === "accumulating") {
    return (
      <section className="rounded-xl bg-hull/40 p-4">
        <div className="flex items-center gap-1.5">
          <Moon size={14} className="text-indigo-300" />
          <span className="text-xs uppercase tracking-wider text-ink-dim">睡眠ドライバー分析</span>
        </div>
        <p className="mt-1 text-[11px] text-ink-faint">分析開始まであと{s.remaining}夜（現在{s.n_nights}夜）。</p>
      </section>
    );
  }
  // trend 以上だけ前面に (weak は数が多いので畳む)
  const pick = (arr: SleepDriverFactor[]) => arr.filter((f) => f.tier !== "weak").slice(0, 6);
  const quality = pick(s.quality);
  const nextDay = pick(s.next_day);
  const anyStrong = [...s.quality, ...s.next_day].some((f) => f.tier === "strong" || f.tier === "suggestive");

  return (
    <section className="space-y-2.5 rounded-xl bg-hull/40 p-4">
      <div className="flex items-center gap-1.5">
        <Moon size={14} className="text-indigo-300" />
        <span className="text-xs uppercase tracking-wider text-ink-dim">睡眠ドライバー分析</span>
        <span className="ml-auto text-[10px] text-ink-faint">
          n={s.n_nights}夜 · 確度{s.reliability === "high" ? "高" : s.reliability === "medium" ? "中" : "低"}
        </span>
      </div>

      {/* 今夜やること (具体アクション) */}
      {(s.recommendations?.length ?? 0) > 0 && (
        <div className="space-y-1 rounded-xl bg-indigo-500/10 p-2.5">
          <div className="text-[10px] font-semibold text-indigo-200">今夜やること</div>
          {s.recommendations!.map((r, i) => (
            <div key={i} className="flex items-baseline gap-1.5 text-[12px] text-ink">
              <span className="text-indigo-300">✓</span>
              <span className="min-w-0 flex-1">{r.text}<span className="ml-1 text-[9px] text-ink-faint">（{r.basis}）</span></span>
            </div>
          ))}
        </div>
      )}

      {!anyStrong && (
        <p className="text-[10px] text-act-300/80">まだ確かな要因は出ていません（傾向どまり）。下記は弱い示唆として薄く表示。</p>
      )}

      {quality.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold text-ink-dim">睡眠の質を左右する要因</div>
          {quality.map((f, i) => <Factor key={i} f={f} />)}
        </div>
      )}
      {nextDay.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold text-ink-dim">翌日パフォーマンスを左右する要因</div>
          {nextDay.map((f, i) => <Factor key={i} f={f} />)}
        </div>
      )}
      {quality.length === 0 && nextDay.length === 0 && (
        <p className="text-[11px] text-ink-faint">有意な傾向はまだありません。記録が貯まると見えてきます。</p>
      )}
      <p className="text-[9px] text-ink-faint">
        就寝の規則性・カフェイン/飲酒のタイミング・運動・活動量などを、効率/深睡眠/翌朝の回復と統計検定（並べ替え+FDR）。
      </p>
    </section>
  );
}
