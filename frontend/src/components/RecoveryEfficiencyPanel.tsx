import { useQuery } from "@tanstack/react-query";
import { Clock, Gauge, TrendingDown, TrendingUp, Zap } from "lucide-react";
import { api } from "../lib/api";
import type { SleepDriverFactor, SleepEfficiencyBin } from "../lib/api";
import { askAi } from "../lib/askAi";
import { LoadingState } from "./ui/cockpit";

/**
 * 「時間あたりの回復効率」。本人データ(n=86夜)では睡眠時間と翌朝の回復(BB)はほぼ無相関
 * (r≈+0.02) な一方、睡眠効率との相関ははるかに強い(r≈+0.28)。時間を伸ばすより
 * 効率・深睡眠を上げる方が効く、という傾向を見せ、「同じ時間からより多く回復する」ための
 * 材料を出す。睡眠タブでは「昨夜どうだったか」の LastNightPanel の直後に置く。
 *
 * ⚠️ 安全性の線 (最優先): ここは「短く寝る」ことを勧める場所では絶対にない。
 * 起床時BB・主観活力は翌日の準備状態を表す短期指標であり、慢性的な短時間睡眠の
 * 心血管・代謝・認知への長期リスクはこの分析には原理的に映らない。飽和点・相関は
 * すべて「同じ時間からどう引き出すか」の文脈でだけ見せ、睡眠時間を削る方向の
 * 助言(profile.sleep_need_min を下げる等)は一切出さない。バックエンド
 * (`scoring/sleep_efficiency.py`)が返す `caveat` は必ずそのまま表示する。
 */

const TIER_LABEL: Record<string, string> = {
  strong: "強い", suggestive: "示唆", trend: "傾向", weak: "弱い", preliminary: "暫定",
};

function DriverRow({ f }: { f: SleepDriverFactor }) {
  const good = f.direction === "改善";
  return (
    <div className="flex items-baseline gap-2 rounded-lg bg-void/30 px-2.5 py-2 text-[11px]">
      {good
        ? <TrendingUp size={11} className="shrink-0 translate-y-0.5 text-prog-300" />
        : <TrendingDown size={11} className="shrink-0 translate-y-0.5 text-risk" />}
      <span className="min-w-0 flex-1 truncate text-ink-dim">
        {f.label}
        <span className="text-ink-faint"> → {f.outcome_label}</span>
      </span>
      <span className={`shrink-0 font-semibold tabular-nums ${good ? "text-prog-300" : "text-risk"}`}>
        {f.diff > 0 ? "+" : ""}{f.diff}
      </span>
      <span className="shrink-0 text-[9px] text-ink-faint">{TIER_LABEL[f.tier] ?? f.tier} n{f.n}</span>
    </div>
  );
}

/** 睡眠時間ビン別の翌朝BB。薄い(reliable=false)ビンはバーもラベルも薄く出し、
 * 「データ不足」であることを一目で分かるようにする(そこから結論を出させないため)。 */
function BinRow({ b, maxBb }: { b: SleepEfficiencyBin; maxBb: number }) {
  const pct = b.avg_bb != null && maxBb > 0 ? Math.max(4, Math.round((b.avg_bb / maxBb) * 100)) : 0;
  return (
    <div className={`space-y-1 ${b.reliable ? "" : "opacity-45"}`}>
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="w-16 shrink-0 tabular-nums text-ink-dim">{b.label}</span>
        <span className="flex-1" />
        <span className="shrink-0 tabular-nums text-ink">
          {b.avg_bb != null ? `BB ${b.avg_bb}` : "データなし"}
        </span>
        <span className="w-16 shrink-0 text-right text-[9px] text-ink-faint">
          {b.reliable ? `n${b.n}` : `n${b.n}・データ不足`}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-void/40">
        <div
          className={`h-full rounded-full ${b.reliable ? "bg-indigo-400/70" : "bg-ink-faint/40"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** 相関の強さ比較 (時間 vs 効率 vs 深睡眠)。バーの長さは |r|、色は方向。 */
function CorrRow({ label, r, n }: { label: string; r: number | null; n: number }) {
  const pct = r != null ? Math.min(100, Math.round(Math.abs(r) * 100)) : 0;
  const positive = (r ?? 0) >= 0;
  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="w-16 shrink-0 text-ink-dim">{label}</span>
        <span className="flex-1" />
        <span className="shrink-0 tabular-nums font-semibold text-ink">
          {r != null ? `r=${r > 0 ? "+" : ""}${r.toFixed(2)}` : "n不足"}
        </span>
        <span className="w-10 shrink-0 text-right text-[9px] text-ink-faint">n{n}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-void/40">
        <div
          className={`h-full rounded-full ${positive ? "bg-prog-300/70" : "bg-risk/60"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function RecoveryEfficiencyPanel() {
  const q = useQuery({ queryKey: ["sleep-efficiency"], queryFn: api.sleepEfficiency, staleTime: 60_000 });
  const d = q.data;
  if (q.isLoading) return <LoadingState height="h-40" />;
  if (!d) return null;

  // sleep_drivers.analyze() の powered 判定 (_MIN_PAIRS) と揃え、それ未満は蓄積中扱いにする。
  const MIN_NIGHTS = 8;
  if (d.n_nights < MIN_NIGHTS) {
    return (
      <section className="space-y-2 rounded-xl bg-hull/40 p-4">
        <div className="flex items-center gap-1.5">
          <Zap size={14} className="text-indigo-300" />
          <span className="text-xs uppercase tracking-wider text-ink-dim">時間あたりの回復効率</span>
        </div>
        <p className="text-[11px] text-ink-faint">
          分析にはあと{MIN_NIGHTS - d.n_nights}夜ほど記録が必要です(現在{d.n_nights}夜)。
        </p>
      </section>
    );
  }

  const bins = d.saturation.bins;
  const maxBb = Math.max(0, ...bins.map((b) => b.avg_bb ?? 0));
  const peak = d.saturation.peak;
  const ph = d.per_hour;

  return (
    <section className="space-y-2.5 rounded-xl bg-hull/40 p-4">
      <div className="flex items-center gap-1.5">
        <Zap size={14} className="text-indigo-300" />
        <span className="text-xs uppercase tracking-wider text-ink-dim">時間あたりの回復効率</span>
        <button
          onClick={() =>
            askAi(
              `時間あたりの回復効率: 睡眠時間とBBの相関r=${d.correlations.duration.r}, ` +
              `睡眠効率とBBの相関r=${d.correlations.efficiency.r}, ` +
              `深睡眠とBBの相関r=${d.correlations.deep_min.r}。` +
              `${peak ? `翌朝BBは約${peak.hours}時間のビンでピーク(平均BB${peak.avg_bb})。` : "頭打ちの点はまだ判定できていません。"}` +
              `同じ時間で質を上げる要因: ${d.drivers.map((f) => `${f.label}→${f.outcome_label}=${f.direction}(${f.tier})`).join(", ") || "まだなし"}。` +
              "睡眠時間を削らずに、同じ睡眠時間でより多く回復するには具体的に何を変えるべき?",
            )
          }
          className="ml-auto text-[10px] text-ink-faint underline hover:text-ink-dim"
        >
          AIに聞く
        </button>
      </div>

      {/* 飽和点のヘッドライン。必ず「翌日の回復指標での飽和」であることを明記する */}
      {peak ? (
        <div className="space-y-1 rounded-xl bg-indigo-500/10 p-2.5">
          <div className="flex items-center gap-1.5 text-[12px] text-ink">
            <Clock size={12} className="shrink-0 text-indigo-300" />
            あなたの回復は約{peak.hours}時間で頭打ちになっています
            {!peak.observed_within_range && "(参考: データが薄いため確定はできません)"}
          </div>
          <p className="text-[10px] leading-relaxed text-ink-faint">
            これは翌日の回復指標(起床時ボディバッテリー)での頭打ちであり、長期的な健康影響とは別問題です。
            睡眠時間を削ることを勧めるものではありません。
          </p>
        </div>
      ) : (
        <p className="text-[11px] text-ink-faint">まだ頭打ちの点を判定できるだけのデータがありません。</p>
      )}

      {/* 時間帯別ビン (簡易グラフ)。データが薄いビンは opacity を下げ、n を「データ不足」付きで出す。 */}
      <div className="space-y-1.5">
        <div className="text-[10px] font-semibold text-ink-dim">睡眠時間ビン別の翌朝の回復(BB)</div>
        <div className="space-y-2">
          {bins.map((b) => <BinRow key={b.label} b={b} maxBb={maxBb} />)}
        </div>
      </div>

      {/* 時間より効率: 相関の比較 + 上位/下位夜の効率差 */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Gauge size={11} className="text-indigo-300" />
          <span className="text-[10px] font-semibold text-ink-dim">時間より効率</span>
        </div>
        <div className="space-y-2 rounded-lg bg-void/20 p-2.5">
          <CorrRow label="睡眠時間" r={d.correlations.duration.r} n={d.correlations.duration.n} />
          <CorrRow label="睡眠効率" r={d.correlations.efficiency.r} n={d.correlations.efficiency.n} />
          <CorrRow label="深睡眠" r={d.correlations.deep_min.r} n={d.correlations.deep_min.n} />
        </div>
        {ph.n > 0 && ph.top_avg_efficiency != null && ph.bottom_avg_efficiency != null && (
          <p className="text-[10px] text-ink-faint">
            時間対効果が良かった上位夜(平均効率{ph.top_avg_efficiency}%)は、
            悪かった夜(平均効率{ph.bottom_avg_efficiency}%)より効率が高い傾向。
            {ph.top_avg_deep_min != null && ph.bottom_avg_deep_min != null &&
              ` 深睡眠も${ph.top_avg_deep_min}分 対 ${ph.bottom_avg_deep_min}分。`}
          </p>
        )}
      </div>

      {/* 行動: 効率・深睡眠を上げる要因のみ (時間を削る方向の助言は出さない) */}
      {d.drivers.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold text-indigo-200">同じ時間で質を上げるには</div>
          {d.drivers.map((f, i) => <DriverRow key={i} f={f} />)}
        </div>
      )}

      <div className="space-y-0.5 border-t border-hairline/50 pt-2">
        {d.caveat.map((c, i) => (
          <p key={i} className="text-[9px] leading-relaxed text-ink-faint">{c}</p>
        ))}
      </div>
    </section>
  );
}
