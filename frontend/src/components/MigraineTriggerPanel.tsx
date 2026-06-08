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
            <span className="text-slate-300">要因の統計判定は保留中。</span>
            有意差を誠実に出すには、あと <b className="text-sky-300">{data.remaining}</b> 件の頭痛記録が必要です
            (最低 {data.min_episodes} 件)。気圧・カフェイン離脱・睡眠不足・HRV 低下・飲酒を追跡しています。
          </span>
        </div>
      )}

      {data.status === "no_significant_factor" && (
        <div className="rounded-lg bg-slate-900/70 p-2.5 text-[11px] text-slate-400">
          測定した要因のうち、頭痛と<span className="text-slate-300">統計的に有意な関連</span>を持つものは
          現時点でありません。<span className="text-slate-500">
            (= 既知の要因では説明しきれない。引き続き記録で精度が上がります)
          </span>
        </div>
      )}

      {data.status === "has_factors" && (
        <div className="space-y-1.5">
          <div className="text-[11px] text-slate-400">統計的に有意な要因 (多重比較補正済み):</div>
          {data.factors.map((f) => (
            <div key={f.key} className="rounded-lg bg-rose-500/10 p-2.5 ring-1 ring-rose-500/30">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-rose-200">
                  {f.label} <span className="text-[10px] text-rose-300/80">{f.direction}</span>
                </span>
                <span className="text-[10px] tabular-nums text-slate-400">p={f.p} · q={f.q}</span>
              </div>
              <div className="mt-0.5 text-[10px] text-slate-400">
                頭痛時の平均 {f.case_mean} vs 平常時 {f.control_mean}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
