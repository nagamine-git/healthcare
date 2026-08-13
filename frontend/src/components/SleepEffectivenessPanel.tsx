import { useQuery } from "@tanstack/react-query";
import { FlaskConical, HelpCircle, Moon, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "../lib/api";
import type {
  SleepDriverFactor,
  SleepInterventionOutcome,
  SleepInterventionResult,
  WorthVerifyingItem,
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
const TIER_LABEL: Record<string, string> = {
  strong: "強い", suggestive: "示唆", trend: "傾向", weak: "弱い", preliminary: "暫定",
};
// 行名 (介入/ドライバー名) のベース色もtierで変える。opacity だけだと濃い文字色に対しては
// 効きが弱いため、ベース自体を下位tierほど暗い ink トーンにして「薄さ」を強調する。
const TIER_NAME_COLOR: Record<string, string> = {
  strong: "text-ink", suggestive: "text-ink", trend: "text-ink-dim",
  weak: "text-ink-faint", preliminary: "text-ink-dim",
};

/**
 * 確度 → 不透明度を **連続値** で出す (tier 単位の固定5段階だと同じ tier 内の差が潰れるため)。
 * 基準は有意性そのもの: powered なら q 値、未補正 (preliminary) なら p 値を 1段階割り引く。
 * q=0 (完全に有意) → 1.0、q>=0.5 → 下限 0.3 に向けて滑らかに落ちる。
 */
function opacityFor(r: Row): number {
  const sig = r.q ?? Math.min(1, (r.p ?? 1) * 1.5); // preliminary は p を割り引いて弱める
  const t = Math.min(1, Math.max(0, sig / 0.5));    // 0 (強い) 〜 1 (弱い)
  return Math.round((1 - t * 0.7) * 100) / 100;     // 1.0 → 0.3
}

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

/** 布団 (one-vs-rest) を既存の Row に流し込む。tier/q/p のキーが同じなので安全に混ざる */
function beddingRows(b: import("../lib/api").BeddingAnalysis | undefined): Row[] {
  if (!b) return [];
  const rows: Row[] = [];
  for (const bed of b.beddings) {
    for (const o of bed.outcomes) {
      if (o.tier === "weak") continue;
      rows.push({
        kind: "intervention", name: `布団: ${bed.name}`, outcome_label: o.outcome_label,
        direction: (o.diff ?? 0) >= 0 ? "改善" : "悪化",
        diff: o.diff ?? 0, p: o.p, q: o.q, tier: o.tier,
        nLabel: `この布団${o.n_with}/他${o.n_without}夜`,
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

/**
 * 「確かめる価値があるもの」の1行。既存 RowView (確定/示唆の要因) より視覚的に控えめにする:
 * - opacity を固定で下げ、確定行のように q 値で明るくなることはない
 * - 効果量 (diff) の数値は出さない。方向 (改善/悪化) だけ見せ、「大きさ」を煽らない
 * - なぜ検証対象なのか (reason: 着脱夜数 + 少数例の注意) を必ず1行添える
 */
function WorthVerifyingRow({ item }: { item: WorthVerifyingItem }) {
  const good = item.direction === "改善";
  return (
    <div className="space-y-0.5 rounded-lg bg-void/20 px-2.5 py-2 text-[11px] opacity-70">
      <div className="flex items-baseline gap-2">
        <HelpCircle size={11} className="shrink-0 translate-y-0.5 text-ink-faint" />
        <span className="min-w-0 flex-1 truncate text-ink-faint">
          {item.label}
          <span className="text-ink-faint/70"> → {item.outcome_label}</span>
        </span>
        <span className={`shrink-0 text-[9px] font-medium ${good ? "text-prog-300/70" : "text-risk/70"}`}>
          {good ? "改善方向" : "悪化方向"}
        </span>
        <span className="shrink-0 text-[9px] text-ink-faint">
          着{item.n_did}/外{item.n_didnt}夜
        </span>
      </div>
      <p className="pl-[19px] text-[9px] leading-snug text-ink-faint">{item.reason}</p>
    </div>
  );
}

function RowView({ r }: { r: Row }) {
  const good = r.direction === "改善";
  const Icon = r.kind === "intervention" ? FlaskConical : Moon;
  return (
    <div
      className="flex items-baseline gap-2 rounded-lg bg-void/30 px-2.5 py-2 text-[11px]"
      style={{ opacity: opacityFor(r) }}
    >
      <Icon size={11} className="shrink-0 translate-y-0.5 text-ink-faint" />
      <span className="min-w-0 flex-1 truncate text-ink-dim">
        <span className={TIER_NAME_COLOR[r.tier]}>{r.name}</span>
        <span className="text-ink-faint"> → {r.outcome_label}</span>
      </span>
      {/* 方向はセクション見出しで既知なので、ここは効果量 (差分) を出す方が情報量が高い */}
      <span className={`shrink-0 font-semibold tabular-nums ${good ? "text-prog-300" : "text-risk"}`}>
        {r.diff > 0 ? "+" : ""}{r.diff}
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
    ...(ivReady ? beddingRows(iv!.bedding) : []),
    ...(drReady ? driverRows([...dr!.quality, ...dr!.next_day]) : []),
  ].sort((a, b) => {
    const ka = confKey(a), kb = confKey(b);
    return ka[0] - kb[0] || ka[1] - kb[1] || ka[2] - kb[2];
  });
  // 「効くもの」と「妨げるもの」は行動の意味が逆 (増やす vs 減らす) なので分けて見せる。
  // 各セクション内は既存の確度順 (rows のソート順) を保つ。
  const helps = rows.filter((r) => r.direction === "改善").slice(0, 8);
  const hurts = rows.filter((r) => r.direction === "悪化").slice(0, 8);
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

      {helps.length === 0 && hurts.length === 0 && (
        <p className="text-[11px] text-ink-faint">有意な傾向はまだありません。記録が貯まると見えてきます。</p>
      )}
      {helps.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <TrendingUp size={11} className="text-prog-300" />
            <span className="text-[10px] font-semibold text-prog-300">睡眠を良くするもの</span>
          </div>
          {helps.map((r, i) => <RowView key={i} r={r} />)}
        </div>
      )}
      {hurts.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <TrendingDown size={11} className="text-risk" />
            <span className="text-[10px] font-semibold text-risk">睡眠を妨げるもの</span>
          </div>
          {hurts.map((r, i) => <RowView key={i} r={r} />)}
        </div>
      )}

      {/* 確かめる価値があるもの: 有意性 (tier) には効果の大きさとサンプル数が混ざっており、
          「効果大×データ薄」(取りに行く価値あり) と「効果小×データ厚」(調べても無駄) が
          同じ tier に潰れてしまう。ここは前者だけを抜き出した検証候補 (上位3件)。
          strong (確定済み) は対象外、標準化効果量とデータの薄さで選定・順位付け
          (詳細は backend/app/scoring/sleep_interventions.py:_worth_verifying)。
          worth_verifying が空なら (=検証候補なし) セクションごと出さない。 */}
      {iv?.worth_verifying && iv.worth_verifying.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <HelpCircle size={11} className="text-ink-faint" />
            <span className="text-[10px] font-semibold text-ink-dim">確かめる価値があるもの</span>
          </div>
          <p className="text-[9px] text-ink-faint">
            少数例では効果が大きく出やすいので、あくまで「もう数夜試して確かめる価値がある」という
            意味です。効果が確定したわけではありません（確定した要因は上のセクションに出ます）。
          </p>
          <div className="space-y-1">
            {iv.worth_verifying.map((item, i) => <WorthVerifyingRow key={i} item={item} />)}
          </div>
        </div>
      )}

      <p className="text-[9px] text-ink-faint">
        介入(耳栓・アイマスク・鼻呼吸・口テープ・呼吸法・瞑想=着脱の二値)とドライバー(活動量・
        カフェイン/飲酒のタイミング・運動等=連続量の高低)を同じ検定(並べ替え+FDR補正)で評価し、
        確度順にランク付け。文字の濃さは有意性(q値)に連動——薄いほど確証が弱い。
        単一被験者(n-of-1)のため判定には各条件で複数夜が必要です。
      </p>
    </section>
  );
}
