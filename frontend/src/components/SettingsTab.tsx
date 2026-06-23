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
import { NotificationSettings } from "./NotificationSettings";

/**
 * 個人差ファクター設定タブ。計算に直結する因子だけをグループ別の開閉式
 * セクションに集約する。
 *
 * 「わからない / 自動で考えてほしい」項目は、自動計算値 (派生/デフォルト) を
 * グレーで表示する (= 自動モード)。明示的に値を入れると通常色になり、× で
 * いつでも自動に戻せる。auto 判定は overrides[field] == null。
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
  const ov = d.overrides;
  const set = (body: SettingsUpdate) => save.mutate(body);
  const isAuto = (f: keyof SettingsDto["overrides"]) => ov[f] == null;

  return (
    <div className="space-y-3">
      <p className="px-1 text-[11px] leading-relaxed text-slate-500">
        計算に効く体質・生活パラメータ。<span className="text-slate-400">グレーの値は自動</span>
        （派生・デフォルト）で、迷ったらそのままでOK。値を入れると個人設定になり、× で自動に戻せます。
      </p>

      <NotificationSettings />

      {/* 身体・基礎 */}
      <Group icon={<User size={14} className="text-emerald-300" />} title="身体・基礎"
        summary={`${d.age}歳 / ${d.height_cm}cm`}>
        <DateField label="生年月日" value={d.birth_date} auto={isAuto("birth_date")}
          hint="入れておくと年齢を都度自動計算 (BMR・最大心拍に反映)"
          onSave={(v) => set({ birth_date: v })} onClear={() => set({ birth_date: null })} />
        <Derived label="年齢 (自動算出)" value={`${d.age} 歳`} />
        <div className="pt-1 text-[11px] text-slate-500">
          身長・性別・目標体型は下のセクションで設定します。
        </div>
        <PhysiqueTargetSection current={current} />
      </Group>

      {/* 心拍ゾーン */}
      <Group icon={<HeartPulse size={14} className="text-rose-300" />} title="心拍ゾーン"
        summary={`安静${d.resting_hr} / 最大${d.max_hr}`}>
        <NumberField label="安静時心拍" value={d.resting_hr} auto={isAuto("resting_hr")} unit="bpm"
          min={30} max={120} hint="Karvonen 心拍ゾーンの下限"
          onSave={(v) => set({ resting_hr: v })} onClear={() => set({ resting_hr: null })} />
        <NumberField label="最大心拍" value={d.max_hr} auto={isAuto("max_hr")} unit="bpm"
          min={120} max={220}
          hint={`自動は Tanaka 式 (208−0.7×年齢=${Math.round(208 - 0.7 * d.age)})。実測があれば上書き`}
          onSave={(v) => set({ max_hr: v })} onClear={() => set({ max_hr: null })} />
      </Group>

      {/* カフェイン PK */}
      <Group icon={<Coffee size={14} className="text-amber-300" />} title="カフェイン体質"
        summary={`半減期 ${d.caffeine_half_life_h.toFixed(1)}h`}>
        <Toggle label="喫煙している" checked={d.caffeine_smoker} auto={isAuto("caffeine_smoker")}
          hint="CYP1A2 誘導で半減期が短くなる (×0.6)"
          onChange={(v) => set({ caffeine_smoker: v })} onClear={() => set({ caffeine_smoker: null })} />
        {d.sex === "female" && (
          <>
            <Toggle label="経口避妊薬を服用" checked={d.caffeine_oral_contraceptives}
              auto={isAuto("caffeine_oral_contraceptives")} hint="阻害で半減期が延びる (×1.8)"
              onChange={(v) => set({ caffeine_oral_contraceptives: v })}
              onClear={() => set({ caffeine_oral_contraceptives: null })} />
            <Toggle label="妊娠中" checked={d.caffeine_pregnant} auto={isAuto("caffeine_pregnant")}
              hint="後期は強い阻害で半減期が延びる (×2.6)"
              onChange={(v) => set({ caffeine_pregnant: v })}
              onClear={() => set({ caffeine_pregnant: null })} />
          </>
        )}
        <Segmented label="感受性" value={d.caffeine_sensitivity} auto={isAuto("caffeine_sensitivity")}
          hint="効きやすさ → 目標摂取量 mg/kg を調整"
          options={[
            { value: "high", label: "高い" },
            { value: "normal", label: "普通" },
            { value: "low", label: "低い" },
          ]}
          onChange={(v) => set({ caffeine_sensitivity: v as SettingsDto["caffeine_sensitivity"] })}
          onClear={() => set({ caffeine_sensitivity: null })} />
        <NumberField label="半減期を直接指定 (上級)"
          value={ov.caffeine_half_life_override_h ?? d.caffeine_half_life_h}
          auto={isAuto("caffeine_half_life_override_h")} unit="h" min={2} max={12} step={0.1}
          hint="自動は喫煙等の因子から算出。実測した人は直接指定 (2–12h、トグルより優先)"
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
        <TimeField label="起床時刻" value={d.wake_time} auto={isAuto("wake_time")}
          hint="就寝逆算・サーカディアンの基準"
          onSave={(v) => set({ wake_time: v })} onClear={() => set({ wake_time: null })} />
        <NumberField label="必要睡眠量" value={d.sleep_need_min} auto={isAuto("sleep_need_min")}
          unit="分" min={240} max={660} step={15}
          hint={`睡眠不足判定の基準 (= ${(d.sleep_need_min / 60).toFixed(1)}h)`}
          onSave={(v) => set({ sleep_need_min: v })} onClear={() => set({ sleep_need_min: null })} />
        <Segmented label="クロノタイプ" value={d.chronotype} auto={isAuto("chronotype")}
          hint="睡眠/光曝露アドバイスの個人化 (LLM)"
          options={[
            { value: "morning", label: "朝型" },
            { value: "intermediate", label: "中間" },
            { value: "evening", label: "夜型" },
          ]}
          onChange={(v) => set({ chronotype: v as SettingsDto["chronotype"] })}
          onClear={() => set({ chronotype: null })} />
      </Group>

      {/* 栄養 */}
      <Group icon={<Utensils size={14} className="text-lime-300" />} title="栄養目標"
        summary={`P ${d.protein_g_per_kg}g/kg · 水 ${d.water_ml_per_kg}mL/kg`}>
        <NumberField label="タンパク質" value={d.protein_g_per_kg} auto={isAuto("protein_g_per_kg")}
          unit="g/kg" min={0.5} max={3} step={0.1} hint="体重あたりのタンパク質目標"
          onSave={(v) => set({ protein_g_per_kg: v })} onClear={() => set({ protein_g_per_kg: null })} />
        <NumberField label="水分" value={d.water_ml_per_kg} auto={isAuto("water_ml_per_kg")}
          unit="mL/kg" min={20} max={60} step={1} hint="体重あたりの水分目標・ペース予測"
          onSave={(v) => set({ water_ml_per_kg: v })} onClear={() => set({ water_ml_per_kg: null })} />
      </Group>

      {save.isError && (
        <p className="px-1 text-[11px] text-rose-400">保存に失敗しました。値の範囲を確認してください。</p>
      )}
    </div>
  );
}

// ---- 部品 ----

function Group({
  icon, title, summary, children,
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

/** 自動モードの「自動」バッジ。明示設定時はクリア (×) ボタンを出す。 */
function AutoTrailing({ auto, onClear }: { auto: boolean; onClear: () => void }) {
  if (auto) {
    return (
      <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-500">
        自動
      </span>
    );
  }
  return (
    <button type="button" onClick={onClear} title="自動に戻す"
      className="rounded px-1 text-xs text-slate-500 hover:text-rose-400">
      ×
    </button>
  );
}

function NumberField({
  label, value, auto, unit, min, max, step = 1, hint, onSave, onClear,
}: {
  label: string;
  value: number;
  auto: boolean;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  onSave: (v: number) => void;
  onClear: () => void;
}) {
  const [str, setStr] = useState(String(value));
  useEffect(() => setStr(String(value)), [value]);
  const commit = () => {
    const v = parseFloat(str);
    if (Number.isFinite(v) && v !== value) onSave(v);
    else setStr(String(value));
  };
  return (
    <FieldShell label={label} hint={hint}>
      <input
        type="number" inputMode="decimal" min={min} max={max} step={step}
        value={str}
        onChange={(e) => setStr(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
        className={`w-20 rounded border bg-slate-900 px-2 py-1 text-right text-xs tabular-nums focus:border-amber-500 focus:outline-none ${
          auto ? "border-slate-800 italic text-slate-500" : "border-slate-700 text-slate-200"
        }`}
      />
      {unit && <span className="w-12 text-[10px] text-slate-500">{unit}</span>}
      <AutoTrailing auto={auto} onClear={onClear} />
    </FieldShell>
  );
}

function DateField({ label, value, auto, hint, onSave, onClear }: {
  label: string; value: string | null; auto: boolean; hint?: string;
  onSave: (v: string) => void; onClear: () => void;
}) {
  return (
    <FieldShell label={label} hint={hint}>
      <input type="date" value={value ?? ""} max={new Date().toISOString().slice(0, 10)}
        onChange={(e) => { if (e.target.value) onSave(e.target.value); }}
        className={`rounded border bg-slate-900 px-2 py-1 text-xs tabular-nums focus:border-amber-500 focus:outline-none ${
          auto ? "border-slate-800 italic text-slate-500" : "border-slate-700 text-slate-200"
        }`}
      />
      <AutoTrailing auto={auto} onClear={onClear} />
    </FieldShell>
  );
}

function TimeField({ label, value, auto, hint, onSave, onClear }: {
  label: string; value: string; auto: boolean; hint?: string;
  onSave: (v: string) => void; onClear: () => void;
}) {
  return (
    <FieldShell label={label} hint={hint}>
      <input type="time" value={value}
        onChange={(e) => { if (e.target.value) onSave(e.target.value); }}
        className={`rounded border bg-slate-900 px-2 py-1 text-xs tabular-nums focus:border-amber-500 focus:outline-none ${
          auto ? "border-slate-800 italic text-slate-500" : "border-slate-700 text-slate-200"
        }`}
      />
      <AutoTrailing auto={auto} onClear={onClear} />
    </FieldShell>
  );
}

function Toggle({ label, checked, auto, hint, onChange, onClear }: {
  label: string; checked: boolean; auto: boolean; hint?: string;
  onChange: (v: boolean) => void; onClear: () => void;
}) {
  // 自動時はオフ扱いだがミュート表示。クリックで明示 ON/OFF になる。
  const on = checked && !auto;
  return (
    <FieldShell label={label} hint={hint}>
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 rounded-full transition-colors ${
          auto ? "bg-slate-800 ring-1 ring-slate-700" : on ? "bg-emerald-500/80" : "bg-slate-700"
        }`}>
        <span className={`absolute top-0.5 h-4 w-4 rounded-full transition-transform ${
          auto ? "translate-x-0.5 bg-slate-600" : on ? "translate-x-4 bg-white" : "translate-x-0.5 bg-white"
        }`} />
      </button>
      <AutoTrailing auto={auto} onClear={onClear} />
    </FieldShell>
  );
}

function Segmented({ label, value, auto, options, hint, onChange, onClear }: {
  label: string;
  value: string;
  auto: boolean;
  options: { value: string; label: string }[];
  hint?: string;
  onChange: (v: string) => void;
  onClear: () => void;
}) {
  return (
    <FieldShell label={label} hint={hint}>
      <div className="flex rounded-lg bg-slate-800/70 p-0.5">
        {options.map((o) => {
          const active = value === o.value;
          return (
            <button key={o.value} onClick={() => onChange(o.value)}
              className={`rounded-md px-2.5 py-1 text-xs ${
                active
                  ? auto
                    ? "bg-slate-700/60 italic text-slate-400"
                    : "bg-slate-600 text-slate-100"
                  : "text-slate-400"
              }`}>
              {o.label}
            </button>
          );
        })}
      </div>
      <AutoTrailing auto={auto} onClear={onClear} />
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
