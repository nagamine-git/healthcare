import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Sparkles, UtensilsCrossed } from "lucide-react";
import { api } from "../lib/api";
import type { FoodItemDto, FoodItemInput, MealFrequency, MealSlot } from "../lib/api";

const SLOTS: { key: MealSlot; label: string }[] = [
  { key: "breakfast", label: "朝" },
  { key: "lunch", label: "昼" },
  { key: "dinner", label: "夜" },
  { key: "snack", label: "間食" },
];
const FREQ_LABEL: Record<MealFrequency, string> = { daily: "毎日", often: "よく", sometimes: "たまに" };
const CONF_LABEL: Record<string, string> = {
  high: "確度高(記録ベース)", medium: "確度中(全枠登録)",
  partial: "朝など固定+昼夜はランダム", none: "データ不足",
};
const SLOT_JP: Record<MealSlot, string> = { breakfast: "朝", lunch: "昼", dinner: "夜", snack: "間食" };

/**
 * 食事の頻用食品・パターン登録 → 普段の摂取を推定 → 目標との差を置換/追加で提案。
 * 食品マクロは LLM が名前+量から推定 (素人の手入力を不要に)。計算は決定的。
 */
export function MealPlanner() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const foods = useQuery({ queryKey: ["foods"], queryFn: api.foods });
  const patterns = useQuery({ queryKey: ["meal-patterns"], queryFn: api.mealPatterns });
  const plan = useQuery({ queryKey: ["meal-plan"], queryFn: api.mealPlan });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["foods"] });
    qc.invalidateQueries({ queryKey: ["meal-patterns"] });
    qc.invalidateQueries({ queryKey: ["meal-plan"] });
    qc.invalidateQueries({ queryKey: ["physique-plan"] });
  };

  const sug = plan.data;

  return (
    <section className="space-y-3 rounded-xl bg-hull/70 p-4 sm:p-5">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full items-center gap-1.5 text-left">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <UtensilsCrossed size={14} className="text-prog-300" />
        <span className="text-sm tracking-wide text-ink">食事プラン</span>
        {sug?.usual?.estimate && (
          <span className="ml-auto text-[11px] tabular-nums text-ink-dim">
            {sug.usual.complete ? "普段" : "固定"} P{Math.round(sug.usual.estimate.protein_g)}g
          </span>
        )}
      </button>

      {/* サジェスト (常時表示: 食事の核心) */}
      {sug && (
        <div className="space-y-2 rounded-xl border border-prog-700/25 bg-prog-500/15 p-3">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] font-medium text-prog-300">置換・追加サジェスト</span>
            {sug.usual && (
              <span className="text-[9px] text-ink-faint">
                {!sug.usual.estimate
                  ? "記録か頻用食品の登録で推定が始まります"
                  : sug.usual.complete
                  ? `普段の推定: ${Math.round(sug.usual.estimate.protein_g)}g P / 目標 ${sug.targets.protein_g}g · ${CONF_LABEL[sug.usual.confidence] ?? ""}`
                  : `固定 ${Math.round(sug.usual.fixed_protein_g)}g P (${sug.usual.registered_slots.map((s) => SLOT_JP[s]).join("・")}) + ${sug.usual.variable_slots.map((s) => SLOT_JP[s]).join("・")}はランダム / 目標 ${sug.targets.protein_g}g`}
              </span>
            )}
          </div>
          {sug.suggestions.map((s, i) => (
            <div key={i} className="flex items-start gap-2 text-[11px] leading-relaxed text-ink">
              <Sparkles size={12} className="mt-0.5 shrink-0 text-prog-300" />
              <span>{s.text}</span>
            </div>
          ))}
        </div>
      )}

      {open && (
        <>
          <FoodRegister onSaved={invalidate} />
          <FoodList foods={foods.data?.items ?? []} onDelete={(id) => api.foodDelete(id).then(invalidate)} />
          <PatternEditor
            foods={foods.data?.items ?? []}
            slots={patterns.data?.slots}
            onAdd={(b) => api.mealPatternAdd(b).then(invalidate)}
            onDelete={(id) => api.mealPatternDelete(id).then(invalidate)}
          />
        </>
      )}
    </section>
  );
}

function FoodRegister({ onSaved }: { onSaved: () => void }) {
  const [name, setName] = useState("");
  const [qty, setQty] = useState("");
  const [draft, setDraft] = useState<FoodItemInput | null>(null);

  const estimate = useMutation({
    mutationFn: () => api.foodEstimate(name.trim(), qty.trim() || undefined),
    onSuccess: (r) => {
      if (r.available) {
        const { available: _a, ...rest } = r;
        setDraft(rest);
      } else {
        // LLM 不可 → 空の手入力フォーム
        setDraft({ name: name.trim(), kcal: 0, protein_g: 0, fat_g: 0, carb_g: 0, unit_label: qty.trim() || "1食", category: null, is_protein_source: false });
      }
    },
  });
  const save = useMutation({
    mutationFn: () => api.foodCreate(draft!),
    onSuccess: () => { setName(""); setQty(""); setDraft(null); onSaved(); },
  });

  return (
    <div className="space-y-2 rounded-xl border border-panel bg-hull/40 p-3">
      <div className="text-[10px] uppercase tracking-wider text-ink-faint">頻用食品を登録 (LLMがマクロ推定)</div>
      <div className="flex flex-wrap items-center gap-2">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="例: 唐揚げ / プロテインバー"
          className="min-w-0 flex-1 rounded border border-hairline bg-hull px-2 py-1 text-xs text-ink focus:border-prog focus:outline-none" />
        <input value={qty} onChange={(e) => setQty(e.target.value)} placeholder="量(任意 例:5個)"
          className="w-28 rounded border border-hairline bg-hull px-2 py-1 text-xs text-ink focus:border-prog focus:outline-none" />
        <button disabled={!name.trim() || estimate.isPending} onClick={() => estimate.mutate()}
          className="rounded-full border border-prog-700/60 bg-prog-900/20 px-3 py-1 text-xs text-prog-300 hover:bg-prog-900/50 disabled:opacity-40">
          {estimate.isPending ? "推定中…" : "推定"}
        </button>
      </div>

      {draft && (
        <div className="space-y-2 rounded-lg bg-void/40 p-2">
          <div className="grid grid-cols-4 gap-1.5">
            {(["kcal", "protein_g", "fat_g", "carb_g"] as const).map((k) => (
              <label key={k} className="text-[9px] text-ink-faint">
                {k === "kcal" ? "kcal" : k === "protein_g" ? "P(g)" : k === "fat_g" ? "F(g)" : "C(g)"}
                <input type="number" value={draft[k]} onChange={(e) => setDraft({ ...draft, [k]: parseFloat(e.target.value) || 0 })}
                  className="w-full rounded border border-hairline bg-hull px-1.5 py-1 text-right text-xs text-ink tabular-nums" />
              </label>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input value={draft.unit_label} onChange={(e) => setDraft({ ...draft, unit_label: e.target.value })}
              className="w-24 rounded border border-hairline bg-hull px-2 py-1 text-xs text-ink" />
            <label className="flex items-center gap-1 text-[10px] text-ink-dim">
              <input type="checkbox" checked={draft.is_protein_source}
                onChange={(e) => setDraft({ ...draft, is_protein_source: e.target.checked })} />
              タンパク源
            </label>
            <button disabled={save.isPending} onClick={() => save.mutate()}
              className="ml-auto rounded-full border border-prog-700/60 bg-prog-900/30 px-3 py-1 text-xs text-prog-300 hover:bg-prog-900/60 disabled:opacity-40">
              保存
            </button>
            <button onClick={() => setDraft(null)} className="text-xs text-ink-faint hover:text-ink-dim">取消</button>
          </div>
        </div>
      )}
    </div>
  );
}

function FoodList({ foods, onDelete }: { foods: FoodItemDto[]; onDelete: (id: number) => void }) {
  if (!foods.length) return null;
  return (
    <div className="rounded-xl border border-panel bg-hull/40 p-3">
      <div className="mb-1.5 text-[10px] uppercase tracking-wider text-ink-faint">登録済み食品 ({foods.length})</div>
      <ul className="space-y-1">
        {foods.map((f) => (
          <li key={f.id} className="flex items-baseline gap-2 text-xs">
            <span className="text-ink">{f.name}</span>
            <span className="text-[10px] text-ink-faint">{f.unit_label}</span>
            <span className="telemetry-num tabular-nums text-act-300">{Math.round(f.protein_g)}gP</span>
            <span className="telemetry-num tabular-nums text-ink-faint">{Math.round(f.kcal)}kcal</span>
            {f.is_protein_source && <span className="text-[9px] text-prog-300">タンパク源</span>}
            <button onClick={() => onDelete(f.id)} className="ml-auto text-ink-faint hover:text-risk">×</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PatternEditor({ foods, slots, onAdd, onDelete }: {
  foods: { id: number; name: string }[];
  slots?: Record<MealSlot, { id: number; name: string; qty: number; frequency: MealFrequency; protein_g: number }[]>;
  onAdd: (b: { slot: MealSlot; food_id: number; qty?: number; frequency?: MealFrequency }) => void;
  onDelete: (id: number) => void;
}) {
  return (
    <div className="rounded-xl border border-panel bg-hull/40 p-3">
      <div className="mb-1 text-[10px] uppercase tracking-wider text-ink-faint">普段のパターン (記録が無い日の推定に使用)</div>
      <p className="mb-1.5 text-[10px] leading-tight text-ink-faint">
        登録した枠＝<span className="text-ink-dim">固定メニュー</span>。空の枠（昼・夜など）は
        <span className="text-ink-dim">ランダム</span>扱いで、固定分から残りの必要量を提案します。朝だけ登録でOK。
      </p>
      {!foods.length && <p className="text-[10px] text-ink-faint">先に頻用食品を登録してください。</p>}
      <div className="space-y-2.5">
        {SLOTS.map((s) => (
          <SlotRow key={s.key} slot={s.key} label={s.label} foods={foods}
            items={slots?.[s.key] ?? []} onAdd={onAdd} onDelete={onDelete} />
        ))}
      </div>
    </div>
  );
}

function SlotRow({ slot, label, foods, items, onAdd, onDelete }: {
  slot: MealSlot; label: string; foods: { id: number; name: string }[];
  items: { id: number; name: string; qty: number; frequency: MealFrequency }[];
  onAdd: (b: { slot: MealSlot; food_id: number; qty?: number; frequency?: MealFrequency }) => void;
  onDelete: (id: number) => void;
}) {
  const [foodId, setFoodId] = useState<number | "">("");
  const [qty, setQty] = useState("1");
  const [freq, setFreq] = useState<MealFrequency>("daily");
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <span className="w-8 shrink-0 text-xs text-ink-dim">{label}</span>
        {items.map((it) => (
          <span key={it.id} className="flex items-center gap-1 rounded-full bg-panel px-2 py-0.5 text-[10px] text-ink-dim">
            {it.name}{it.qty !== 1 ? `×${it.qty}` : ""}・{FREQ_LABEL[it.frequency]}
            <button onClick={() => onDelete(it.id)} className="text-ink-faint hover:text-risk">×</button>
          </span>
        ))}
      </div>
      {foods.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pl-8">
          <select value={foodId} onChange={(e) => setFoodId(e.target.value ? Number(e.target.value) : "")}
            className="rounded border border-hairline bg-hull px-1.5 py-1 text-[11px] text-ink">
            <option value="">食品を選択</option>
            {foods.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
          <input type="number" value={qty} onChange={(e) => setQty(e.target.value)} min={0.5} step={0.5}
            className="w-12 rounded border border-hairline bg-hull px-1.5 py-1 text-right text-[11px] text-ink tabular-nums" />
          <select value={freq} onChange={(e) => setFreq(e.target.value as MealFrequency)}
            className="rounded border border-hairline bg-hull px-1.5 py-1 text-[11px] text-ink">
            {(["daily", "often", "sometimes"] as const).map((f) => <option key={f} value={f}>{FREQ_LABEL[f]}</option>)}
          </select>
          <button disabled={!foodId} onClick={() => { if (foodId) { onAdd({ slot, food_id: foodId, qty: parseFloat(qty) || 1, frequency: freq }); setFoodId(""); setQty("1"); } }}
            className="rounded-full border border-prog-700/60 bg-prog-900/20 px-2.5 py-1 text-[11px] text-prog-300 hover:bg-prog-900/50 disabled:opacity-40">
            + 追加
          </button>
        </div>
      )}
    </div>
  );
}
