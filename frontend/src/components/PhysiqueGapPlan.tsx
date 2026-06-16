import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Clock,
  Dumbbell,
  Flame,
  Target,
  Utensils,
} from "lucide-react";
import { api } from "../lib/api";

/**
 * 理想体型と現在地のギャップを「結局何をすべきか」に翻訳して見せるカード。
 * エネルギー収支から逆算したカロリー/マクロ目標、医学的に正しい優先順位
 * (食事>筋トレ>有酸素 の寄与)、所要期間を提示する。
 */
export function PhysiqueGapPlan() {
  const q = useQuery({ queryKey: ["physique-plan"], queryFn: api.physiquePlan });
  const p = q.data;
  if (!p) return null;
  if (!p.available) {
    return (
      <div className="rounded-2xl bg-slate-900/40 p-4 text-xs text-slate-500">
        ギャップ分析: {p.reason}（体重・体脂肪率を記録すると表示されます）
      </div>
    );
  }

  const dirColor =
    p.direction === "cut" ? "text-amber-300"
    : p.direction === "recomp" ? "text-emerald-300"
    : p.direction === "lean_bulk" ? "text-sky-300"
    : "text-slate-300";

  return (
    <section className="space-y-4 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 p-4 sm:p-5 ring-1 ring-slate-800">
      {/* ヘッダ */}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-center gap-2">
          <Target size={16} className={dirColor} />
          <h3 className="text-sm tracking-wide text-slate-100">ギャップを埋めるには</h3>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <Clock size={12} />
          <span>到達目安 {p.timeline.eta_label}</span>
        </div>
      </div>

      {/* 方針 */}
      <div className={`text-lg font-semibold ${dirColor}`}>{p.direction_label}</div>

      {/* 現在 → 目標 */}
      <div className="flex items-center gap-3 rounded-xl bg-slate-950/40 p-3 text-xs">
        <GapCol label="現在" w={p.current.weight_kg} bf={p.current.body_fat_pct}
          fat={p.current.fat_mass_kg} lean={p.current.lean_mass_kg} />
        <ArrowRight size={18} className="shrink-0 text-slate-600" />
        <GapCol label="目標" w={p.target.weight_kg} bf={p.target.body_fat_pct}
          fat={p.target.fat_mass_kg} lean={p.target.lean_mass_kg} accent />
        <div className="ml-auto hidden text-right text-[11px] tabular-nums text-slate-400 sm:block">
          {p.gap.d_fat_mass_kg != null && (
            <div>脂肪 <b className="text-amber-300">{fmtDelta(p.gap.d_fat_mass_kg)}kg</b></div>
          )}
          {p.gap.d_lean_mass_kg != null && (
            <div>筋 <b className="text-emerald-300">{fmtDelta(p.gap.d_lean_mass_kg)}kg</b></div>
          )}
        </div>
      </div>

      {/* 結局やること = 優先度 */}
      <div className="space-y-2">
        <div className="text-[10px] uppercase tracking-wider text-slate-500">結局やること (効果の優先度)</div>
        {p.levers.map((l) => (
          <div key={l.name} className="space-y-1">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="text-slate-200">{l.name}</span>
              <span className="font-mono tabular-nums text-slate-400">{l.share_pct}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
              <div className="h-full rounded-full bg-gradient-to-r from-emerald-500/70 to-emerald-400"
                style={{ width: `${l.share_pct}%` }} />
            </div>
            <p className="text-[10px] leading-tight text-slate-500">{l.why}</p>
          </div>
        ))}
      </div>

      {/* エネルギー & マクロ */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat icon={<Flame size={12} className="text-orange-300" />} label="1日の目標"
          value={`${p.energy.calorie_target} kcal`}
          hint={`${p.energy.delta_kcal >= 0 ? "+" : ""}${p.energy.delta_kcal} vs 消費 ${p.energy.tdee}`} />
        <Stat label="タンパク質" value={`${p.macros.protein_g} g`}
          hint={`${p.macros.protein_g_per_kg} g/kg`} accent />
        <Stat label="脂質 / 炭水化物" value={`${p.macros.fat_g} / ${p.macros.carb_g} g`}
          hint={`基礎代謝 ${p.energy.bmr}`} />
        <Stat label="消費(TDEE)" value={`${p.energy.tdee} kcal`}
          hint={p.energy.tdee_measured ? "実測ベース" : "推定 (係数1.45)"} />
      </div>

      {/* 食事 vs 運動 の核心 (方向で色を変える) */}
      <div className={`rounded-xl border p-3 ${
        p.direction === "lean_bulk" ? "border-sky-700/30 bg-sky-950/20"
        : p.direction === "maintain" ? "border-slate-700/40 bg-slate-900/40"
        : "border-amber-700/30 bg-amber-950/20"
      }`}>
        <div className={`mb-1 flex items-center gap-1.5 text-[11px] font-medium ${
          p.direction === "lean_bulk" ? "text-sky-200"
          : p.direction === "maintain" ? "text-slate-200" : "text-amber-200"
        }`}>
          <Utensils size={12} /> {p.diet_vs_exercise.headline}
        </div>
        <p className="text-[11px] leading-relaxed text-slate-300/90">{p.diet_vs_exercise.note}</p>
      </div>

      {/* トレーニング処方 */}
      <div className="space-y-1.5 rounded-xl bg-slate-950/40 p-3">
        <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-200">
          <Dumbbell size={12} className="text-emerald-300" /> トレーニング (週 {p.training.resistance_sessions_per_week} 回・筋トレ主)
        </div>
        <p className="text-[10px] leading-tight text-slate-400">{p.training.primary}</p>
        <p className="text-[10px] leading-tight text-slate-400">🥊 {p.training.shadowboxing}</p>
        <p className="text-[10px] leading-tight text-slate-500">⚠ {p.training.interference}</p>
      </div>

      {/* 注記 */}
      {p.notes.length > 0 && (
        <ul className="space-y-0.5">
          {p.notes.map((n, i) => (
            <li key={i} className="text-[10px] leading-tight text-slate-500">· {n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function GapCol({ label, w, bf, fat, lean, accent }: {
  label: string; w: number; bf: number | null; fat: number | null; lean: number | null; accent?: boolean;
}) {
  return (
    <div className="space-y-0.5">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`font-mono text-base tabular-nums ${accent ? "text-emerald-200" : "text-slate-200"}`}>
        {w}<span className="text-[10px] text-slate-500"> kg</span>
      </div>
      {bf != null && <div className="text-[10px] tabular-nums text-slate-400">体脂肪 {bf}%</div>}
      {fat != null && lean != null && (
        <div className="text-[9px] tabular-nums text-slate-500">脂肪{fat} / 筋{lean}kg</div>
      )}
    </div>
  );
}

function Stat({ icon, label, value, hint, accent }: {
  icon?: React.ReactNode; label: string; value: string; hint?: string; accent?: boolean;
}) {
  return (
    <div className={`rounded-xl border px-3 py-2 ${accent ? "border-emerald-700/40 bg-emerald-950/20" : "border-slate-800 bg-slate-900/40"}`}>
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-slate-500">
        {icon}{label}
      </div>
      <div className={`font-mono text-sm tabular-nums ${accent ? "text-emerald-200" : "text-slate-200"}`}>{value}</div>
      {hint && <div className="text-[10px] text-slate-500">{hint}</div>}
    </div>
  );
}

function fmtDelta(v: number): string {
  return `${v > 0 ? "+" : ""}${v}`;
}
