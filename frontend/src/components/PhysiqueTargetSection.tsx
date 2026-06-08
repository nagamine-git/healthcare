import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Target } from "lucide-react";
import { api } from "../lib/api";
import { BodyCompositionMap } from "./BodyCompositionMap";
import { Silhouette } from "./Silhouette";

/**
 * 理想体型: 縦軸=体脂肪率 / 横軸=体重 のコンパクトなグリッドから選び、
 * 各セルから必要な筋肉量 (FFMI) を逆算。実現可能性で濃淡をつけ、
 * 選択中セルの体型を大きなシルエットでプレビューして保存する。
 * 計算式はバックエンド (body_composition.py) と一致。
 */

const BODY_FATS = [8, 10, 12, 14, 16, 18, 20, 22]; // 縦軸

/** (身長, 体脂肪, 体重) から正規化 FFMI を逆算 */
function impliedFfmi(heightCm: number, bodyFat: number, weight: number): number {
  const h = heightCm / 100;
  const lbm = weight * (1 - bodyFat / 100);
  const ffmiRaw = lbm / (h * h);
  return ffmiRaw + 6.1 * (1.8 - h);
}

function bmiOf(heightCm: number, weight: number): number {
  const h = heightCm / 100;
  return weight / (h * h);
}

/** 身長に応じた体重カラム (BMI 17〜25 を 1kg 刻み) */
function weightColumns(heightCm: number): number[] {
  const h = heightCm / 100;
  const lo = Math.round(17.0 * h * h);
  const hi = Math.round(25.5 * h * h);
  const cols: number[] = [];
  for (let w = lo; w <= hi; w += 1) cols.push(w);
  return cols;
}

function feasibility(ffmi: number): "ok" | "stretch" | "unreal" {
  if (ffmi < 15 || ffmi > 25) return "unreal";
  if (ffmi < 16.5 || ffmi > 23) return "stretch";
  return "ok";
}

function note(heightCm: number, bf: number, weight: number, sex: "male" | "female") {
  const bmi = Math.round(bmiOf(heightCm, weight) * 10) / 10;
  const ffmi = impliedFfmi(heightCm, bf, weight);
  const floor = sex === "male" ? 10 : 16;
  if (bmi < 16) return { level: "blocked" as const, text: `BMI ${bmi} は重度の低体重。保存できません` };
  const f = feasibility(ffmi);
  if (bmi < 18.5) return { level: "warn" as const, text: `BMI ${bmi} は低体重域 (18.5未満)` };
  if (bf < floor) return { level: "warn" as const, text: `体脂肪 ${bf}% は健康下限を下回る` };
  if (f === "unreal") return { level: "warn" as const, text: `BMI ${bmi}・この体型は非現実的 (要 大幅増量/減量)` };
  if (f === "stretch") return { level: "ok" as const, text: `BMI ${bmi}・健康域 (やや高い目標)` };
  return { level: "ok" as const, text: `BMI ${bmi}・健康域` };
}

export function PhysiqueTargetSection({
  current,
}: {
  current?: { weight: number; bf: number } | null;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.getProfile });

  const [heightCm, setHeightCm] = useState(170);
  const [sex, setSex] = useState<"male" | "female">("male");
  const [sel, setSel] = useState<{ bf: number; weight: number } | null>(null);

  useEffect(() => {
    if (profile.data) {
      setHeightCm(profile.data.height_cm);
      setSex(profile.data.sex);
      // 既存目標に最も近い (bf, weight) セルへスナップ
      const bf = BODY_FATS.reduce((a, b) =>
        Math.abs(b - profile.data!.target_body_fat_pct) < Math.abs(a - profile.data!.target_body_fat_pct) ? b : a);
      setSel({ bf, weight: Math.round(profile.data.target_weight_kg) });
    }
  }, [profile.data]);

  const columns = useMemo(() => weightColumns(heightCm), [heightCm]);

  const save = useMutation({
    mutationFn: (body: Parameters<typeof api.putProfile>[0]) => api.putProfile(body),
    onSuccess: (data) => {
      qc.setQueryData(["profile"], data);
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["trends"] });
    },
  });

  const n = sel ? note(heightCm, sel.bf, sel.weight, sex) : null;
  const selFfmi = sel ? impliedFfmi(heightCm, sel.bf, sel.weight) : 20;

  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 text-left"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Target size={14} className="text-emerald-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">目標体型</span>
        <span className="ml-auto text-[11px] tabular-nums text-slate-400">
          {profile.data ? `${profile.data.target_weight_kg}kg / ${profile.data.target_body_fat_pct}%` : ""}
        </span>
      </button>

      {open && (
        <>
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-300">
            <label className="flex items-center gap-1.5">
              身長
              <input
                type="number"
                value={heightCm}
                onChange={(e) => setHeightCm(parseFloat(e.target.value) || 0)}
                className="w-16 rounded bg-slate-800 px-2 py-1 tabular-nums"
              />
              cm
            </label>
            <div className="flex rounded-lg bg-slate-800/70 p-0.5">
              {(["male", "female"] as const).map((sx) => (
                <button
                  key={sx}
                  onClick={() => setSex(sx)}
                  className={`rounded-md px-3 py-1 ${sex === sx ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}
                >
                  {sx === "male" ? "男性" : "女性"}
                </button>
              ))}
            </div>
          </div>

          {/* 選択中セルの大きなシルエットプレビュー */}
          {sel && n && (
            <div
              className={`flex items-center gap-3 rounded-lg p-3 ${
                n.level === "blocked"
                  ? "bg-rose-500/10 ring-1 ring-rose-500/40"
                  : n.level === "warn"
                  ? "bg-amber-500/10 ring-1 ring-amber-500/40"
                  : "bg-emerald-500/10 ring-1 ring-emerald-500/30"
              }`}
            >
              <Silhouette bodyFat={sel.bf} ffmi={selFfmi} sex={sex} size={48} active />
              <div className="flex-1">
                <div className="text-sm text-slate-100">
                  目標 <b className="tabular-nums">{sel.weight}kg</b> ・ 体脂肪 {sel.bf}%
                </div>
                <div className="text-[11px] text-slate-300">{n.text}</div>
                <button
                  disabled={n.level === "blocked" || save.isPending}
                  onClick={() =>
                    save.mutate({
                      height_cm: heightCm,
                      sex,
                      target_weight_kg: sel.weight,
                      target_body_fat_pct: sel.bf,
                      ffmi_normalized: Math.round(selFfmi * 10) / 10,
                    })
                  }
                  className="mt-1.5 rounded-full bg-emerald-600/80 px-3 py-1 text-xs text-white hover:bg-emerald-600 disabled:opacity-40"
                >
                  {save.isSuccess ? "保存しました ✓" : "この体型を目標にする"}
                </button>
              </div>
            </div>
          )}

          {/* 体組成マップ: 目的別ゾーンを重ねて現在地と目標を可視化 */}
          <BodyCompositionMap
            heightCm={heightCm}
            sex={sex}
            current={current}
            target={sel ? { weight: sel.weight, bf: sel.bf } : null}
          />

          <div className="text-[10px] text-slate-500">下: 縦=体脂肪率 / 横=体重。薄い色ほど非現実的な組合せ (緑=現実的)</div>

          {/* 体脂肪率 × 体重 のコンパクトグリッド (横スクロール) */}
          <div className="overflow-x-auto">
            <table className="border-separate" style={{ borderSpacing: "2px" }}>
              <thead>
                <tr>
                  <th className="sticky left-0 bg-slate-900/40" />
                  {columns.map((w) => (
                    <th key={w} className="text-[9px] font-normal tabular-nums text-slate-500">{w}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {BODY_FATS.map((bf) => (
                  <tr key={bf}>
                    <td className="sticky left-0 bg-slate-900/40 pr-1 text-right text-[9px] tabular-nums text-slate-400">
                      {bf}%
                    </td>
                    {columns.map((w) => {
                      const f = feasibility(impliedFfmi(heightCm, bf, w));
                      const isSel = sel?.bf === bf && sel?.weight === w;
                      const base =
                        f === "unreal"
                          ? "bg-slate-800/30 text-slate-600"
                          : f === "stretch"
                          ? "bg-slate-700/40 text-slate-400"
                          : "bg-emerald-500/15 text-emerald-200";
                      return (
                        <td key={w}>
                          <button
                            onClick={() => setSel({ bf, weight: w })}
                            className={`h-6 w-7 rounded text-[8px] tabular-nums ${base} ${
                              isSel ? "ring-2 ring-emerald-400" : "hover:brightness-150"
                            }`}
                            aria-label={`体脂肪${bf}% 体重${w}kg`}
                          >
                            {isSel ? "●" : ""}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
