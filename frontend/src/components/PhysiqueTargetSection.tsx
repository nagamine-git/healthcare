import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Target } from "lucide-react";
import { api } from "../lib/api";
import { Silhouette } from "./Silhouette";

/**
 * 理想体型シルエットから目標体重を自動計算・保存するセクション。
 * 体型(FFMI) × 体脂肪率 のグリッドから選び、身長と合わせて体重・BMI を即時計算。
 * 計算式はバックエンド (body_composition.py) と一致させる。
 */

const BUILDS = [
  { key: "slim", label: "細身", ffmi: 18 },
  { key: "lean_muscular", label: "細マッチョ", ffmi: 20 },
  { key: "muscular", label: "マッチョ", ffmi: 22 },
];
const BODY_FATS = [10, 12, 15, 18, 22];

function computeTarget(heightCm: number, bodyFat: number, ffmiNorm: number) {
  const h = heightCm / 100;
  const ffmiRaw = ffmiNorm - 6.1 * (1.8 - h);
  const lbm = ffmiRaw * h * h;
  const weight = lbm / (1 - bodyFat / 100);
  const bmi = weight / (h * h);
  return { weight: Math.round(weight * 10) / 10, bmi: Math.round(bmi * 10) / 10 };
}

function bmiNote(bmi: number, bodyFat: number, sex: "male" | "female") {
  const floor = sex === "male" ? 10 : 16;
  if (bmi < 16) return { level: "blocked", text: `BMI ${bmi} は重度の低体重。保存できません` };
  if (bmi < 18.5) return { level: "warn", text: `BMI ${bmi} は低体重域 (18.5未満)` };
  if (bodyFat < floor) return { level: "warn", text: `体脂肪 ${bodyFat}% は健康下限を下回る` };
  return { level: "ok", text: `BMI ${bmi} ・ 健康域` };
}

export function PhysiqueTargetSection() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.getProfile });

  const [heightCm, setHeightCm] = useState(170);
  const [sex, setSex] = useState<"male" | "female">("male");
  const [sel, setSel] = useState<{ ffmi: number; bf: number } | null>(null);

  // プロファイル読み込み時に初期値を反映
  useEffect(() => {
    if (profile.data) {
      setHeightCm(profile.data.height_cm);
      setSex(profile.data.sex);
      if (profile.data.ffmi_normalized) {
        setSel({ ffmi: profile.data.ffmi_normalized, bf: profile.data.target_body_fat_pct });
      }
    }
  }, [profile.data]);

  const save = useMutation({
    mutationFn: (body: Parameters<typeof api.putProfile>[0]) => api.putProfile(body),
    onSuccess: (data) => {
      qc.setQueryData(["profile"], data);
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["trends"] });
    },
  });

  const preview = sel ? computeTarget(heightCm, sel.bf, sel.ffmi) : null;
  const note = preview && sel ? bmiNote(preview.bmi, sel.bf, sex) : null;

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

          <div className="text-[11px] text-slate-400">理想の体型をタップ（マッチョ寄りほど体重は増えます）</div>

          {/* 体型 (列) × 体脂肪 (行) のシルエットグリッド */}
          <div className="overflow-x-auto">
            <div className="grid min-w-[300px] gap-1" style={{ gridTemplateColumns: `auto repeat(${BUILDS.length}, 1fr)` }}>
              <div />
              {BUILDS.map((b) => (
                <div key={b.key} className="text-center text-[10px] text-slate-400">{b.label}</div>
              ))}
              {BODY_FATS.map((bf) => (
                <FatRow
                  key={bf}
                  bf={bf}
                  sex={sex}
                  heightCm={heightCm}
                  selected={sel}
                  onSelect={(ffmi) => setSel({ ffmi, bf })}
                />
              ))}
            </div>
          </div>

          {preview && sel && note && (
            <div
              className={`rounded-lg p-3 ${
                note.level === "blocked"
                  ? "bg-rose-500/10 ring-1 ring-rose-500/40"
                  : note.level === "warn"
                  ? "bg-amber-500/10 ring-1 ring-amber-500/40"
                  : "bg-emerald-500/10 ring-1 ring-emerald-500/30"
              }`}
            >
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-slate-100">
                  目標 <b className="tabular-nums">{preview.weight}kg</b> ・ 体脂肪 {sel.bf}%
                </span>
                <span className="text-[11px] text-slate-300">{note.text}</span>
              </div>
              <button
                disabled={note.level === "blocked" || save.isPending}
                onClick={() =>
                  save.mutate({
                    height_cm: heightCm,
                    sex,
                    target_weight_kg: preview.weight,
                    target_body_fat_pct: sel.bf,
                    ffmi_normalized: sel.ffmi,
                  })
                }
                className="mt-2 w-full rounded-full bg-emerald-600/80 px-3 py-1.5 text-xs text-white hover:bg-emerald-600 disabled:opacity-40"
              >
                {save.isSuccess ? "保存しました ✓" : "この体型を目標にする"}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function FatRow({
  bf,
  sex,
  heightCm,
  selected,
  onSelect,
}: {
  bf: number;
  sex: "male" | "female";
  heightCm: number;
  selected: { ffmi: number; bf: number } | null;
  onSelect: (ffmi: number) => void;
}) {
  return (
    <>
      <div className="flex items-center justify-end pr-1 text-[10px] tabular-nums text-slate-400">{bf}%</div>
      {BUILDS.map((b) => {
        const isSel = selected?.bf === bf && selected?.ffmi === b.ffmi;
        const { weight } = computeTarget(heightCm, bf, b.ffmi);
        return (
          <button
            key={b.key}
            onClick={() => onSelect(b.ffmi)}
            className={`flex flex-col items-center rounded-lg p-1 transition ${
              isSel ? "bg-emerald-500/15 ring-1 ring-emerald-400/60" : "hover:bg-slate-800/60"
            }`}
          >
            <Silhouette bodyFat={bf} ffmi={b.ffmi} sex={sex} size={34} active={isSel} />
            <span className="text-[9px] tabular-nums text-slate-400">{weight}kg</span>
          </button>
        );
      })}
    </>
  );
}
