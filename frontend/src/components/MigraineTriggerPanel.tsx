import { useQuery } from "@tanstack/react-query";
import { Activity, Clock3, Info } from "lucide-react";
import { api } from "../lib/api";
import type { MigraineOnsetProfile } from "../lib/api";

/**
 * 頭痛要因分析パネル。
 * - 発症時刻プロファイル (記述的) は常に表示。
 * - トリガー要因は統計的に有意 (BH 補正後) なものだけ。
 * - サンプルが少ない間は「判定保留」、有意ゼロなら「寄与要因なし」を明示。
 */

function fmtHour(h: number): string {
  const hh = Math.floor(h);
  const mm = Math.round((h - hh) * 60);
  return `${hh}:${mm.toString().padStart(2, "0")}`;
}

function OnsetProfile({ p }: { p: MigraineOnsetProfile }) {
  const max = Math.max(1, ...p.buckets.map((b) => b.count));
  return (
    <div>
      <div className="mb-1 flex items-center gap-1.5 text-[11px] text-slate-400">
        <Clock3 size={12} /> 発症しやすい時間帯
        {p.mean_hour != null && (
          <span className="text-slate-500">
            · 平均 {fmtHour(p.mean_hour)} ごろ
            {p.peak_bucket ? ` (${p.peak_bucket}に集中)` : ""}
          </span>
        )}
      </div>
      <div className="grid grid-cols-4 gap-1">
        {p.buckets.map((b) => (
          <div key={b.label} className="rounded-md bg-slate-900/70 p-1.5 text-center">
            <div className="flex h-8 items-end justify-center">
              <div
                className="w-3 rounded-t bg-amber-500/70"
                style={{ height: `${(b.count / max) * 100}%` }}
              />
            </div>
            <div className="mt-1 text-[9px] leading-tight text-slate-400">{b.label}</div>
            <div className="text-[11px] tabular-nums text-slate-200">{b.count}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MigraineTriggerPanel() {
  const q = useQuery({ queryKey: ["migraine-triggers"], queryFn: api.migraineTriggers });
  const data = q.data;
  if (q.isLoading || !data) return null;
  if (data.episode_count === 0) return null; // 記録ゼロなら出さない

  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center gap-1.5">
        <Activity size={14} className="text-amber-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">頭痛の要因分析</span>
        <span className="text-[10px] text-slate-500">記録 {data.episode_count} 件</span>
      </div>

      <OnsetProfile p={data.onset_profile} />

      {data.status === "accumulating" && (
        <div className="flex items-start gap-1.5 rounded-lg bg-slate-900/70 p-2.5 text-[11px] text-slate-400">
          <Info size={13} className="mt-0.5 shrink-0 text-sky-400" />
          <span>
            <span className="text-slate-300">あと <b className="text-sky-300">{data.remaining}</b> 件で要因分析を開始</span>
            します (最低4件)。気圧・カフェイン離脱・睡眠不足・HRV低下・飲酒を追跡中。
          </span>
        </div>
      )}

      {(data.status === "analyzed" || data.status === "no_data") && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px] text-slate-400">
            <span>要因の関連度 (確からしさ順)</span>
            <ReliabilityBadge r={data.reliability} n={data.episode_count} />
          </div>
          {data.factors.length === 0 && (
            <div className="rounded-lg bg-slate-900/70 p-2.5 text-[11px] text-slate-500">
              比較できるデータがまだありません。記録が増えると関連度が出ます。
            </div>
          )}
          {data.factors.map((f) => (
            <FactorRow key={f.key} f={f} />
          ))}
          <p className="text-[9px] leading-relaxed text-slate-600">
            ◆ 濃い=確からしい / 薄い=傾向どまり。件数が少ないほど全体的に淡く、誤検出しやすい点に注意。
            記録が貯まると「強い示唆」へ格上げされます (多重比較補正 q 値で判定)。
          </p>
        </div>
      )}
    </section>
  );
}

const TIER: Record<string, { label: string; ring: string; bg: string; op: string }> = {
  strong: { label: "強い示唆", ring: "ring-rose-500/50", bg: "bg-rose-500/15", op: "opacity-100" },
  suggestive: { label: "弱い示唆", ring: "ring-amber-500/40", bg: "bg-amber-500/10", op: "opacity-90" },
  trend: { label: "傾向", ring: "ring-slate-600/50", bg: "bg-slate-800/40", op: "opacity-70" },
  weak: { label: "関連薄", ring: "ring-slate-700/40", bg: "bg-slate-900/40", op: "opacity-45" },
};

function FactorRow({ f }: { f: import("../lib/api").MigraineFactor }) {
  const t = TIER[f.tier ?? "weak"] ?? TIER.weak;
  const trigger = f.direction === "誘発";
  return (
    <div className={`rounded-lg p-2.5 ring-1 ${t.ring} ${t.bg} ${t.op}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm text-slate-100">
          {f.label}{" "}
          <span className={`text-[10px] ${trigger ? "text-rose-300/80" : "text-emerald-300/70"}`}>
            {trigger ? "誘発↑" : "抑制?"}
          </span>
        </span>
        <span className="shrink-0 rounded-full bg-slate-900/60 px-1.5 py-0.5 text-[9px] text-slate-300">{t.label}</span>
      </div>
      <div className="mt-0.5 flex items-baseline justify-between text-[10px] text-slate-400">
        <span>頭痛時 {f.case_mean} vs 平常 {f.control_mean}</span>
        <span className="tabular-nums text-slate-500">p={f.p} · q={f.q}{f.n_case != null ? ` · n=${f.n_case}` : ""}</span>
      </div>
    </div>
  );
}

function ReliabilityBadge({ r, n }: { r?: string; n: number }) {
  const map: Record<string, { t: string; c: string }> = {
    very_low: { t: "精度 とても低い", c: "text-slate-500" },
    low: { t: "精度 低い", c: "text-amber-400/80" },
    medium: { t: "精度 中", c: "text-sky-300" },
    high: { t: "精度 高い", c: "text-emerald-300" },
  };
  const m = map[r ?? "very_low"] ?? map.very_low;
  return <span className={`text-[10px] ${m.c}`}>{m.t} (n={n})</span>;
}
