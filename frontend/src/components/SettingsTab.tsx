import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Coffee,
  HeartPulse,
  Moon,
  User,
  Utensils,
} from "lucide-react";
import { api } from "../lib/api";
import type { SettingsDto, SettingsUpdate } from "../lib/api";
import { PhysiqueTargetSection } from "./PhysiqueTargetSection";

/**
 * 個人差ファクター設定タブ。計算に直結する因子だけをグループ別の開閉式
 * セクションに集約する。各因子に「効く計算」のヒントを添え、派生値
 * (有効半減期・最大心拍・目標 mg/kg) はライブ表示する。
 */
export function SettingsTab({
  current,
}: {
  current?: { weight: number; bf: number } | null;
}) {
  const qc = useQueryClient();
  const s = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });

  const save = useMutation({
    mutationFn: (body: SettingsUpdate) => api.putSettings(body),
    onSuccess: (data) => {
      qc.setQueryData(["settings"], data);
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["trends"] });
      qc.invalidateQueries({ queryKey: ["day-story"] });
    },
  });

  if (!s.data) {
    return <div className="rounded-2xl bg-slate-900/40 p-4 text-xs text-slate-500">読込中…</div>;
  }
  const d = s.data;
  const set = (body: SettingsUpdate) => save.mutate(body);

  return (
    <div className="space-y-3">
      <p className="px-1 text-[11px] leading-relaxed text-slate-500">
        ここで設定した値は採点・カフェイン提案・睡眠計画・栄養目標などの計算に直接反映されます。
        空欄/未設定の項目は既定値が使われます。
      </p>

      {/* 身体・基礎 */}
      <Group icon={<User size={14} className="text-emerald-300" />} title="身体・基礎"
        summary={`${d.age}歳 / ${d.height_cm}cm`}>
        <NumberField label="年齢" value={d.age} unit="歳" min={10} max={100}
          hint="BMR・最大心拍の算出に使用" onSave={(v) => set({ age: v })} />
        <div className="pt-1 text-[11px] text-slate-500">
          身長・性別・目標体型は下のセクションで設定します。
        </div>
        <PhysiqueTargetSection current={current} />
      </Group>

      {/* 心拍ゾーン */}
      <Group icon={<HeartPulse size={14} className="text-rose-300" />} title="心拍ゾーン"
        summary={`安静${d.resting_hr} / 最大${d.max_hr}`}>
        <NumberField label="安静時心拍" value={d.resting_hr} unit="bpm" min={30} max={120}
          hint="Karvonen 心拍ゾーンの下限" onSave={(v) => set({ resting_hr: v })} />
        <NumberField label="最大心拍 (実測)" value={d.max_hr}
          unit="bpm" min={120} max={220} nullable
          hint={`実測値を入れると上書き。× で式 (208−0.7×年齢=${Math.round(208 - 0.7 * d.age)}) に戻す`}
          onSave={(v) => set({ max_hr: v })} onClear={() => set({ max_hr: null })} />
      </Group>

      {/* カフェイン PK */}
      <Group icon={<Coffee size={14} className="text-amber-300" />} title="カフェイン体質"
        summary={`半減期 ${d.caffeine_half_life_h.toFixed(1)}h`}>
        <Toggle label="喫煙している" checked={d.caffeine_smoker}
          hint="CYP1A2 誘導で半減期が短くなる (×0.6)"
          onChange={(v) => set({ caffeine_smoker: v })} />
        {d.sex === "female" && (
          <>
            <Toggle label="経口避妊薬を服用" checked={d.caffeine_oral_contraceptives}
              hint="阻害で半減期が延びる (×1.8)"
              onChange={(v) => set({ caffeine_oral_contraceptives: v })} />
            <Toggle label="妊娠中" checked={d.caffeine_pregnant}
              hint="後期は強い阻害で半減期が延びる (×2.6)"
              onChange={(v) => set({ caffeine_pregnant: v })} />
          </>
        )}
        <Segmented label="感受性" value={d.caffeine_sensitivity}
          hint="効きやすさ → 目標摂取量 mg/kg を調整"
          options={[
            { value: "high", label: "高い" },
            { value: "normal", label: "普通" },
            { value: "low", label: "低い" },
          ]}
          onChange={(v) => set({ caffeine_sensitivity: v as SettingsDto["caffeine_sensitivity"] })} />
        <NumberField label="半減期を直接指定 (上級)" value={d.caffeine_half_life_override_h ?? null}
          unit="h" min={2} max={12} step={0.1} nullable
          hint="実測した人向け。指定すると上のトグルより優先 (2–12h)"
          onSave={(v) => set({ caffeine_half_life_override_h: v })}
          onClear={() => set({ caffeine_half_life_override_h: null })} />
        <div className="grid grid-cols-2 gap-2 pt-1">
          <Derived label="有効半減期" value={`${d.caffeine_half_life_h.toFixed(2)} h`} />
          <Derived label="目標摂取量" value={`${d.caffeine_target_mg_per_kg} mg/kg`} />
        </div>
      </Group>

      {/* 睡眠 */}
      <Group icon={<Moon size={14} className="text-indigo-300" />} title="睡眠"
        summary={`起床 ${d.wake_time} / ${(d.sleep_need_min / 60).toFixed(1)}h`}>
        <TimeField label="起床時刻" value={d.wake_time}
          hint="就寝逆算・サーカディアンの基準" onSave={(v) => set({ wake_time: v })} />
        <NumberField label="必要睡眠量" value={d.sleep_need_min} unit="分" min={240} max={660} step={15}
          hint={`睡眠不足判定の基準 (= ${(d.sleep_need_min / 60).toFixed(1)}h)`}
          onSave={(v) => set({ sleep_need_min: v })} />
        <Segmented label="クロノタイプ" value={d.chronotype}
          hint="睡眠/光曝露アドバイスの個人化 (LLM)"
          options={[
            { value: "morning", label: "朝型" },
            { value: "intermediate", label: "中間" },
            { value: "evening", label: "夜型" },
          ]}
          onChange={(v) => set({ chronotype: v as SettingsDto["chronotype"] })} />
      </Group>

      {/* 栄養 */}
      <Group icon={<Utensils size={14} className="text-lime-300" />} title="栄養目標"
        summary={`P ${d.protein_g_per_kg}g/kg · 水 ${d.water_ml_per_kg}mL/kg`}>
        <NumberField label="タンパク質" value={d.protein_g_per_kg} unit="g/kg" min={0.5} max={3} step={0.1}
          hint="体重あたりのタンパク質目標" onSave={(v) => set({ protein_g_per_kg: v })} />
        <NumberField label="水分" value={d.water_ml_per_kg} unit="mL/kg" min={20} max={60} step={1}
          hint="体重あたりの水分目標・ペース予測" onSave={(v) => set({ water_ml_per_kg: v })} />
      </Group>

      {save.isError && (
        <p className="px-1 text-[11px] text-rose-400">保存に失敗しました。値の範囲を確認してください。</p>
      )}
    </div>
  );
}

// ---- 部品 ----

function Group({
  icon,
  title,
  summary,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  summary?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full items-center gap-1.5 text-left">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {icon}
        <span className="text-xs uppercase tracking-wider text-slate-300">{title}</span>
        {summary && <span className="ml-auto text-[11px] tabular-nums text-slate-500">{summary}</span>}
      </button>
      {open && <div className="space-y-3">{children}</div>}
    </section>
  );
}

function FieldShell({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="text-xs text-slate-200">{label}</div>
        {hint && <div className="text-[10px] leading-tight text-slate-500">{hint}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">{children}</div>
    </div>
  );
}

function NumberField({
  label, value, unit, min, max, step = 1, hint, nullable, onSave, onClear,
}: {
  label: string;
  value: number | null;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  nullable?: boolean;
  onSave: (v: number) => void;
  onClear?: () => void;
}) {
  const [str, setStr] = useState(value == null ? "" : String(value));
  useEffect(() => setStr(value == null ? "" : String(value)), [value]);
  const commit = () => {
    const v = parseFloat(str);
    if (Number.isFinite(v) && v !== value) onSave(v);
    else if (str === "" && value != null && nullable && onClear) onClear();
  };
  return (
    <FieldShell label={label} hint={hint}>
      <input
        type="number" inputMode="decimal" min={min} max={max} step={step}
        value={str}
        placeholder={nullable ? "自動" : ""}
        onChange={(e) => setStr(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
        className="w-20 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-right text-xs text-slate-200 tabular-nums focus:border-amber-500 focus:outline-none"
      />
      {unit && <span className="w-12 text-[10px] text-slate-500">{unit}</span>}
      {nullable && value != null && onClear && (
        <button type="button" onClick={onClear} title="自動に戻す"
          className="text-slate-500 hover:text-rose-400">×</button>
      )}
    </FieldShell>
  );
}

function TimeField({ label, value, hint, onSave }: {
  label: string; value: string; hint?: string; onSave: (v: string) => void;
}) {
  return (
    <FieldShell label={label} hint={hint}>
      <input type="time" value={value}
        onChange={(e) => { if (e.target.value) onSave(e.target.value); }}
        className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 tabular-nums focus:border-amber-500 focus:outline-none"
      />
    </FieldShell>
  );
}

function Toggle({ label, checked, hint, onChange }: {
  label: string; checked: boolean; hint?: string; onChange: (v: boolean) => void;
}) {
  return (
    <FieldShell label={label} hint={hint}>
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 rounded-full transition-colors ${checked ? "bg-emerald-500/80" : "bg-slate-700"}`}>
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
      </button>
    </FieldShell>
  );
}

function Segmented({ label, value, options, hint, onChange }: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  hint?: string;
  onChange: (v: string) => void;
}) {
  return (
    <FieldShell label={label} hint={hint}>
      <div className="flex rounded-lg bg-slate-800/70 p-0.5">
        {options.map((o) => (
          <button key={o.value} onClick={() => onChange(o.value)}
            className={`rounded-md px-2.5 py-1 text-xs ${value === o.value ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>
            {o.label}
          </button>
        ))}
      </div>
    </FieldShell>
  );
}

function Derived({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="font-mono text-sm tabular-nums text-emerald-200">{value}</div>
    </div>
  );
}
