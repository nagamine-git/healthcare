import { useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { api } from "../lib/api";
import type { SleepInterventionOutcome, SleepInterventionResult } from "../lib/api";

/**
 * 就寝前介入の n-of-1 効果分析。各介入が睡眠の質を有意に改善するかを
 * 「着けた夜 vs 外した夜」の並べ替え検定 + BH-FDR で判定 (手法は睡眠ドライバーと共通)。
 * ハイブリッド運用: 交絡して分離できない時は「今夜の検証」を提案する。
 */

const TIER_OP: Record<string, string> = {
  strong: "opacity-100", suggestive: "opacity-90", trend: "opacity-70", weak: "opacity-45",
};
const TIER_LABEL: Record<string, string> = {
  strong: "強い", suggestive: "示唆", trend: "傾向", weak: "弱い",
};
const VERDICT: Record<string, { label: string; cls: string }> = {
  improves: { label: "改善", cls: "bg-prog-500/20 text-prog-300" },
  worsens: { label: "悪化", cls: "bg-risk/20 text-risk" },
  no_effect: { label: "効果なし", cls: "bg-panel text-ink-dim" },
  insufficient: { label: "データ不足", cls: "bg-panel text-ink-faint" },
};

function Secondary({ o }: { o: SleepInterventionOutcome }) {
  const good = o.direction === "改善";
  return (
    <div className={`flex items-baseline gap-2 text-[11px] ${TIER_OP[o.tier]}`}>
      <span className="min-w-0 flex-1 truncate text-ink-dim">{o.outcome_label}</span>
      <span className={`shrink-0 font-semibold ${good ? "text-prog-300" : "text-risk"}`}>
        {good ? "↑改善" : "↓悪化"}
      </span>
      <span className="shrink-0 text-[9px] text-ink-faint">{TIER_LABEL[o.tier]}</span>
    </div>
  );
}

function Row({ iv }: { iv: SleepInterventionResult }) {
  const v = VERDICT[iv.verdict] ?? VERDICT.insufficient;
  const p = iv.primary;
  // 主指標(睡眠スコア)以外で trend 以上のものを副表示
  const secondary = iv.outcomes.filter((o) => o.outcome !== "sleep_score" && o.tier !== "weak");
  return (
    <div className="space-y-1 rounded-lg bg-void/30 p-2.5">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-ink">{iv.label}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${v.cls}`}>{v.label}</span>
        <span className="ml-auto text-[10px] text-ink-faint">
          着けた{iv.n_did}夜 / 外した{iv.n_didnt}夜
        </span>
      </div>
      {p ? (
        <div className="text-[11px] text-ink-dim">
          睡眠スコア{" "}
          <span className={p.diff > 0 ? "font-semibold text-prog-300" : "font-semibold text-risk"}>
            {p.diff > 0 ? "+" : ""}{p.diff}点
          </span>{" "}
          <span className="text-ink-faint">
            (p={p.p} · {TIER_LABEL[p.tier]})
          </span>
        </div>
      ) : (
        <div className="text-[11px] text-ink-faint">
          着けた/外した夜が各3夜たまると判定できます。
        </div>
      )}
      {secondary.length > 0 && (
        <div className="space-y-0.5 border-t border-hairline pt-1">
          {secondary.map((o, i) => <Secondary key={i} o={o} />)}
        </div>
      )}
    </div>
  );
}

export function SleepInterventionPanel() {
  const q = useQuery({ queryKey: ["sleep-interventions"], queryFn: api.sleepInterventions });
  if (q.isLoading || !q.data) return null;
  const s = q.data;

  if (s.status === "accumulating") {
    return (
      <section className="rounded-xl bg-hull/40 p-4">
        <div className="flex items-center gap-1.5">
          <FlaskConical size={14} className="text-indigo-300" />
          <span className="text-xs uppercase tracking-wider text-ink-dim">介入の効果検証</span>
        </div>
        <p className="mt-1 text-[11px] text-ink-faint">
          分析開始まであと{s.remaining}夜（現在{s.n_nights}夜記録）。毎晩の記録が貯まると、
          各介入が睡眠スコアを有意に上げるか検定します。
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-2.5 rounded-xl bg-hull/40 p-4">
      <div className="flex items-center gap-1.5">
        <FlaskConical size={14} className="text-indigo-300" />
        <span className="text-xs uppercase tracking-wider text-ink-dim">介入の効果検証</span>
        <span className="ml-auto text-[10px] text-ink-faint">
          n={s.n_nights}夜 · 確度
          {s.reliability === "high" ? "高" : s.reliability === "medium" ? "中" : "低"}
        </span>
      </div>

      {s.suggestion && (
        <div className="space-y-0.5 rounded-xl bg-indigo-500/10 p-2.5">
          <div className="text-[10px] font-semibold text-indigo-200">今夜の検証</div>
          <div className="text-[12px] text-ink">{s.suggestion.text}</div>
          <div className="text-[10px] text-ink-faint">{s.suggestion.reason}</div>
        </div>
      )}

      <div className="space-y-1.5">
        {s.interventions.map((iv) => <Row key={iv.key} iv={iv} />)}
      </div>

      <p className="text-[9px] text-ink-faint">
        「着けた夜」と「外した夜」の睡眠スコア等を並べ替え検定＋FDR補正で比較。単一被験者(n-of-1)のため
        判定には各条件で複数夜が必要です。
      </p>
    </section>
  );
}
