import { useQuery } from "@tanstack/react-query";
import { FlaskConical, Moon } from "lucide-react";
import { api } from "../lib/api";
import type {
  SleepDriverFactor,
  SleepInterventionOutcome,
  SleepInterventionResult,
} from "../lib/api";
import { askAi } from "../lib/askAi";
import { LoadingState } from "./ui/cockpit";

/**
 * 就寝前介入 (耳栓/口テープ/呼吸法等、着脱できる二値の習慣) と睡眠ドライバー
 * (活動量・カフェイン timing 等、連続量の生活要因) を統合したランキング。
 *
 * 両者は同じ統計エンジン (並べ替え検定 + BH-FDR、backend/app/scoring/migraine_stats.py の
 * permutation_test/benjamini_hochberg) を使っており、tier (strong/suggestive/trend/weak/
 * preliminary) と q 値の意味が完全に共通。介入=二値の着脱、ドライバー=連続量の高低群、という
 * 入力の違いだけなので、tier→q→p の同じキーで安全に混ぜてランク付けできる
 * (各モジュール内部の既存ソートと同一キー)。
 */

type Row = {
  kind: "intervention" | "driver";
  name: string;
  outcome_label: string;
  direction: "改善" | "悪化";
  diff: number;
  p: number;
  q: number | null;
  tier: "strong" | "suggestive" | "trend" | "weak" | "preliminary";
  nLabel: string;
};

const TIER_RANK: Record<string, number> = { strong: 3, suggestive: 2, trend: 1 };
// tier=強い/示唆 は opacity-100/90 だとほぼ見分けがつかなかった (特に濃い色のテキストは
// 90%でも実質フルに見える)ので、効果が薄いものほど文字も明確に薄くなるよう差を広げる。
const TIER_OP: Record<string, string> = {
  strong: "opacity-100", suggestive: "opacity-75", trend: "opacity-55",
  weak: "opacity-35", preliminary: "opacity-45",
};
// 行名 (介入/ドライバー名) のベース色もtierで変える。opacity だけだと濃い文字色に対しては
// 効きが弱いため、ベース自体を下位tierほど暗い ink トーンにして「薄さ」を強調する。
const TIER_NAME_COLOR: Record<string, string> = {
  strong: "text-ink", suggestive: "text-ink", trend: "text-ink-dim",
  weak: "text-ink-faint", preliminary: "text-ink-dim",
};
const TIER_LABEL: Record<string, string> = {
  strong: "強い", suggestive: "示唆", trend: "傾向", weak: "弱い", preliminary: "暫定",
};

function confKey(r: Row): [number, number, number] {
  return [-(TIER_RANK[r.tier] ?? 0), r.q ?? 1, r.p ?? 1];
}

function interventionRows(ivs: SleepInterventionResult[]): Row[] {
  const rows: Row[] = [];
  for (const iv of ivs) {
    for (const o of iv.outcomes as SleepInterventionOutcome[]) {
      if (o.tier === "weak") continue;
      rows.push({
        kind: "intervention", name: iv.label, outcome_label: o.outcome_label,
        direction: o.direction, diff: o.diff, p: o.p, q: o.q, tier: o.tier,
        nLabel: o.tier === "preliminary"
          ? `着${o.n_did ?? "?"}/外${o.n_didnt ?? "?"}夜`
          : `着${iv.n_did}/外${iv.n_didnt}夜`,
      });
    }
  }
  return rows;
}

function driverRows(factors: SleepDriverFactor[]): Row[] {
  return factors
    .filter((f) => f.tier !== "weak")
    .map((f) => ({
      kind: "driver", name: f.label, outcome_label: f.outcome_label,
      direction: f.direction, diff: f.diff, p: f.p, q: f.q, tier: f.tier,
      nLabel: `n${f.n}`,
    }));
}

function RowView({ r }: { r: Row }) {
  const good = r.direction === "改善";
  const Icon = r.kind === "intervention" ? FlaskConical : Moon;
  return (
    <div className={`flex items-baseline gap-2 rounded-lg bg-void/30 px-2.5 py-2 text-[11px] ${TIER_OP[r.tier]}`}>
      <Icon size={11} className="shrink-0 translate-y-0.5 text-ink-faint" />
      <span className="min-w-0 flex-1 truncate text-ink-dim">
        <span className={TIER_NAME_COLOR[r.tier]}>{r.name}</span>
        <span className="text-ink-faint"> → {r.outcome_label}</span>
      </span>
      <span className={`shrink-0 font-semibold ${good ? "text-prog-300" : "text-risk"}`}>
        {good ? "↑改善" : "↓悪化"}
      </span>
      <span className="shrink-0 text-[9px] text-ink-faint">{TIER_LABEL[r.tier]} {r.nLabel}</span>
    </div>
  );
}

export function SleepEffectivenessPanel() {
  const ivQ = useQuery({ queryKey: ["sleep-interventions"], queryFn: api.sleepInterventions });
  const drQ = useQuery({ queryKey: ["sleep-drivers"], queryFn: api.sleepDrivers });
  if (ivQ.isLoading || drQ.isLoading) return <LoadingState height="h-40" />;
  if (!ivQ.data && !drQ.data) return null;

  const iv = ivQ.data;
  const dr = drQ.data;
  const ivReady = iv && iv.status !== "accumulating";
  const drReady = dr && dr.status !== "accumulating";

  if (!ivReady && !drReady) {
    const remaining = Math.max(iv?.remaining ?? 0, dr?.remaining ?? 0);
    const nights = Math.max(iv?.n_nights ?? 0, dr?.n_nights ?? 0);
    return (
      <section className="space-y-2.5 rounded-xl bg-hull/40 p-4">
        <div className="flex items-center gap-1.5">
          <FlaskConical size={14} className="text-indigo-300" />
          <span className="text-xs uppercase tracking-wider text-ink-dim">睡眠に効く要因</span>
        </div>
        <p className="text-[11px] text-ink-faint">
          分析開始まであと{remaining}夜（現在{nights}夜記録）。介入(耳栓/口テープ/呼吸法等)と
          生活要因(活動量/カフェイン等)の両方を、記録が貯まり次第まとめて検定します。
        </p>
        {iv?.suggestion && (
          <div className="space-y-0.5 rounded-xl bg-indigo-500/10 p-2.5">
            <div className="text-[10px] font-semibold text-indigo-200">今夜何で寝るか</div>
            <div className="text-[12px] text-ink">{iv.suggestion.text}</div>
            <div className="text-[10px] text-ink-faint">{iv.suggestion.reason}</div>
          </div>
        )}
      </section>
    );
  }

  const rows = [
    ...(ivReady ? interventionRows(iv!.interventions) : []),
    ...(drReady ? driverRows([...dr!.quality, ...dr!.next_day]) : []),
  ].sort((a, b) => {
    const ka = confKey(a), kb = confKey(b);
    return ka[0] - kb[0] || ka[1] - kb[1] || ka[2] - kb[2];
  });
  const shown = rows.slice(0, 12);
  const anyStrong = rows.some((r) => r.tier === "strong" || r.tier === "suggestive");
  const nights = Math.max(iv?.n_nights ?? 0, dr?.n_nights ?? 0);
  const reliability = iv?.reliability ?? dr?.reliability;

  return (
    <section className="space-y-2.5 rounded-xl bg-hull/40 p-4">
      <div className="flex items-center gap-1.5">
        <FlaskConical size={14} className="text-indigo-300" />
        <span className="text-xs uppercase tracking-wider text-ink-dim">睡眠に効く要因</span>
        <span className="ml-auto flex items-center gap-2 text-[10px] text-ink-faint">
          {ivReady && (
            <button
              onClick={() =>
                askAi(
                  `就寝前介入: ${iv!.interventions
                    .map((r) => `${r.label}=${r.verdict}(着${r.n_did}/外${r.n_didnt}夜)`)
                    .join(", ")}。睡眠ドライバー: ${rows
                    .filter((r) => r.kind === "driver")
                    .slice(0, 6)
                    .map((r) => `${r.name}→${r.outcome_label}=${r.direction}(${r.tier})`)
                    .join(", ")}。この結果をどう解釈して、次に何を試すべき?`,
                )
              }
              className="underline hover:text-ink-dim"
            >
              AIに聞く
            </button>
          )}
          <span>n={nights}夜 · 確度{reliability === "high" ? "高" : reliability === "medium" ? "中" : "低"}</span>
        </span>
      </div>

      {/* 今夜やること: 介入の1手 (着脱で試せる) + ドライバー由来の具体アクション (最大3件) */}
      {(iv?.suggestion || (dr?.recommendations?.length ?? 0) > 0) && (
        <div className="space-y-1.5 rounded-xl bg-indigo-500/10 p-2.5">
          <div className="text-[10px] font-semibold text-indigo-200">今夜やること</div>
          {iv?.suggestion && (
            <div className="space-y-0.5">
              <div className="text-[12px] text-ink">{iv.suggestion.text}</div>
              <div className="text-[10px] text-ink-faint">{iv.suggestion.reason}</div>
            </div>
          )}
          {dr?.recommendations?.map((r, i) => (
            <div key={i} className="flex items-baseline gap-1.5 text-[12px] text-ink">
              <span className="text-indigo-300">✓</span>
              <span className="min-w-0 flex-1">{r.text}<span className="ml-1 text-[9px] text-ink-faint">（{r.basis}）</span></span>
            </div>
          ))}
        </div>
      )}

      {!anyStrong && rows.length > 0 && (
        <p className="text-[10px] text-act-300/80">まだ確かな要因は出ていません（傾向どまり）。下記は弱い示唆として薄く表示。</p>
      )}

      {shown.length > 0 ? (
        <div className="space-y-1">{shown.map((r, i) => <RowView key={i} r={r} />)}</div>
      ) : (
        <p className="text-[11px] text-ink-faint">有意な傾向はまだありません。記録が貯まると見えてきます。</p>
      )}

      <p className="text-[9px] text-ink-faint">
        介入(耳栓・アイマスク・鼻呼吸・口テープ・呼吸法・瞑想=着脱の二値)とドライバー(活動量・
        カフェイン/飲酒のタイミング・運動等=連続量の高低)を同じ検定(並べ替え+FDR補正)で評価し、
        確度(tier)→有意性(q値)の順にまとめてランク付け。単一被験者(n-of-1)のため判定には
        各条件で複数夜が必要です。
      </p>
    </section>
  );
}
