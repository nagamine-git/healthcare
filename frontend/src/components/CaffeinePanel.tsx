import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import type {
  Caffeine,
  CaffeineIntake,
  CaffeineSource,
} from "../lib/api";
import { localToJstIso } from "../lib/datetime";

type Props = {
  caffeine?: Caffeine;
};

const SOURCE_LABEL: Record<CaffeineSource, string> = {
  instant_coffee: "インスタント",
  canned_coffee: "缶コーヒー",
  nespresso: "ネスプレッソ",
  green_tea: "緑茶",
  ibuquick: "イブクイック",
  bufferin_premium: "バファリンPremium",
  manual: "mg 直接",
};

export function CaffeinePanel({ caffeine }: Props) {
  const qc = useQueryClient();
  const presets = useQuery({
    queryKey: ["caffeine-presets"],
    queryFn: api.caffeinePresets,
    staleTime: 5 * 60_000,
  });
  // 履歴期間 (時間)。デフォルト 24h、ユーザーが切り替え可能
  const [historyHours, setHistoryHours] = useState(24);
  const intakes = useQuery({
    queryKey: ["caffeine-list", historyHours],
    queryFn: () => api.caffeineList(historyHours),
    refetchInterval: 60_000,
  });
  const add = useMutation({
    mutationFn: ({
      source,
      amount,
      tsIso,
    }: {
      source: CaffeineSource;
      amount: number;
      tsIso?: string;
    }) => api.caffeineAdd(source, amount, { ts_iso: tsIso }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["caffeine-list"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.caffeineDelete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["caffeine-list"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });
  const patch = useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number;
      ts_iso?: string;
      amount?: number;
      source?: CaffeineSource;
      note?: string;
    }) => api.caffeinePatch(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["caffeine-list"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const [editingId, setEditingId] = useState<number | null>(null);

  // 記録時刻 (空なら "今")。datetime-local の value 形式 "YYYY-MM-DDTHH:MM"
  const [tsLocal, setTsLocal] = useState("");

  if (!caffeine || !caffeine.available) return null;

  const recommended = caffeine.recommended_mg;
  const blocked = recommended == null;

  return (
    <div className="rounded-2xl bg-slate-900/70 p-4 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-slate-300">カフェイン提案</h3>
        <span className="text-[10px] text-slate-500">{caffeine.disclaimer}</span>
      </div>

      {blocked ? (
        <BlockedBlock caffeine={caffeine} />
      ) : (
        <RecommendBlock caffeine={caffeine} />
      )}

      <ParamGrid caffeine={caffeine} />

      {caffeine.decay_curve && caffeine.decay_curve.length > 0 && (
        <DecayCurve curve={caffeine.decay_curve} basis={caffeine.decay_curve_basis} />
      )}

      {/* 記録ボタン群 */}
      <div className="mt-5 border-t border-slate-800 pt-4">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            飲んだ / 飲む予定を記録
          </span>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            記録時刻
            <input
              type="datetime-local"
              value={tsLocal}
              onChange={(e) => setTsLocal(e.target.value)}
              className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-300 focus:border-amber-500 focus:outline-none"
            />
            {tsLocal && (
              <button
                type="button"
                onClick={() => setTsLocal("")}
                className="text-slate-500 hover:text-slate-300"
                title="クリアして今に戻す"
              >
                ×
              </button>
            )}
            {!tsLocal && <span className="text-slate-600">空=今</span>}
          </label>
        </div>
        <div className="space-y-2">
          {presets.data &&
            (
              [
                "instant_coffee",
                "canned_coffee",
                "nespresso",
                "green_tea",
                "ibuquick",
                "bufferin_premium",
              ] as CaffeineSource[]
            ).map((source) => {
              const p = presets.data[source];
              if (!p) return null;
              return (
                <PresetRow
                  key={source}
                  label={SOURCE_LABEL[source]}
                  unit={p.unit}
                  mgPerUnit={p.mg_per_unit}
                  defaultAmount={p.default_amount}
                  pending={add.isPending}
                  onAdd={(amount) =>
                    add.mutate({ source, amount, tsIso: localToJstIso(tsLocal) })
                  }
                />
              );
            })}
          <ManualInput
            onAdd={(mg) =>
              add.mutate({ source: "manual", amount: mg, tsIso: localToJstIso(tsLocal) })
            }
            pending={add.isPending}
          />
        </div>

        <IntakeList
          items={intakes.data?.items ?? []}
          totalMg={intakes.data?.total_mg ?? 0}
          existingResidualMg={caffeine.existing_residual_mg}
          historyHours={historyHours}
          onChangeHistoryHours={setHistoryHours}
          onDelete={(id) => del.mutate(id)}
          deletingId={del.variables ?? null}
          onEdit={(id) => setEditingId(id)}
        />

        {editingId != null && intakes.data && (
          <EditModal
            item={intakes.data.items.find((i) => i.id === editingId) ?? null}
            onClose={() => setEditingId(null)}
            onSave={(body) => {
              patch.mutate({ id: editingId, ...body });
              setEditingId(null);
            }}
          />
        )}
      </div>
    </div>
  );
}

function RecommendBlock({ caffeine }: { caffeine: Caffeine }) {
  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-5xl tabular-nums text-emerald-300">
          {caffeine.instant_coffee_g?.toFixed(1)}
        </span>
        <span className="text-xs text-slate-500">g インスタント</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-2xl tabular-nums text-slate-200">
          {caffeine.recommended_mg}
        </span>
        <span className="text-xs text-slate-500">mg カフェイン</span>
      </div>
      <p className="basis-full text-xs leading-relaxed text-slate-400">
        {caffeine.reason}
      </p>
    </div>
  );
}

function BlockedBlock({ caffeine }: { caffeine: Caffeine }) {
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-4xl text-rose-300">×</span>
        <span className="text-sm text-rose-300">いま飲むのは非推奨</span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-slate-400">
        {caffeine.reason}
      </p>
    </div>
  );
}

function ParamGrid({ caffeine }: { caffeine: Caffeine }) {
  return (
    <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Param
        label="就寝まで"
        value={
          caffeine.hours_until_bedtime != null
            ? `${caffeine.hours_until_bedtime.toFixed(1)}h`
            : "--"
        }
        hint={caffeine.bedtime ? `就寝 ${caffeine.bedtime}` : undefined}
      />
      <Param
        label="安全上限"
        value={
          caffeine.max_safe_mg != null
            ? `${caffeine.max_safe_mg.toFixed(1)} mg`
            : "--"
        }
        hint="就寝時 0.5 mg/L 未満"
      />
      <Param
        label="認知効果の下限"
        value={
          caffeine.min_cognitive_mg != null
            ? `${Math.round(caffeine.min_cognitive_mg)} mg`
            : "--"
        }
        hint="1mg/kg 目安"
      />
      <Param
        label="体内残量"
        value={
          caffeine.existing_residual_mg != null
            ? `${caffeine.existing_residual_mg.toFixed(1)} mg`
            : "0 mg"
        }
        hint={
          caffeine.half_life_h != null
            ? `半減期 ${caffeine.half_life_h.toFixed(1)}h`
            : undefined
        }
      />
    </div>
  );
}

function Param({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="font-mono text-sm tabular-nums text-slate-200">{value}</div>
      {hint && <div className="text-[10px] text-slate-500">{hint}</div>}
    </div>
  );
}

function DecayCurve({
  curve,
  basis,
}: {
  curve: NonNullable<Caffeine["decay_curve"]>;
  basis?: "recommended" | "existing" | null;
}) {
  const maxConc = Math.max(...curve.map((p) => p.concentration_mg_per_l), 1);
  const title =
    basis === "existing"
      ? "現在の体内残量の減衰予測 (mg/L)"
      : "就寝までの血中濃度予測 (mg/L)";
  return (
    <div className="mt-4">
      <div className="mb-1 flex items-baseline justify-between text-[10px] uppercase tracking-wider text-slate-500">
        <span>{title}</span>
        <span className="normal-case text-slate-600">
          安全閾値 0.5 mg/L を点線で表示
        </span>
      </div>
      <div className="overflow-x-auto pb-1">
        <div className="relative h-20">
          {/* 安全閾値 0.5 mg/L の点線(バーと同じ 80px プロット領域の % で配置) */}
          <div
            className="pointer-events-none absolute inset-x-0 z-10 border-t border-dashed border-rose-500/40"
            style={{ bottom: `${Math.min(100, (0.5 / maxConc) * 100)}%` }}
          />
          <div className="flex h-full items-end gap-[2px]">
            {curve.map((p) => {
              const h = Math.max(2, (p.concentration_mg_per_l / maxConc) * 100);
              const overThreshold = p.concentration_mg_per_l > 0.5;
              return (
                <div
                  key={p.time}
                  className={`shrink-0 rounded-sm ${
                    overThreshold ? "bg-rose-400" : "bg-emerald-400"
                  }`}
                  style={{ width: 14, height: `${h}%` }}
                  title={`${p.time}: ${p.concentration_mg_per_l.toFixed(2)} mg/L (残量 ${p.residual_mg} mg)`}
                />
              );
            })}
          </div>
        </div>
        {/* 時刻ラベルを別行に分離してバーのベースラインを揃える */}
        <div className="mt-1 flex gap-[2px]">
          {curve.map((p) => (
            <span
              key={p.time}
              className="shrink-0 text-center text-[8px] tabular-nums text-slate-500"
              style={{ width: 14 }}
            >
              {p.time.endsWith(":00") ? p.time.split(":")[0] : ""}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function PresetRow({
  label,
  unit,
  mgPerUnit,
  defaultAmount,
  pending,
  onAdd,
}: {
  label: string;
  unit: string;
  mgPerUnit: number;
  defaultAmount: number;
  pending: boolean;
  onAdd: (amount: number) => void;
}) {
  const [amountStr, setAmountStr] = useState(String(defaultAmount));
  const amount = parseFloat(amountStr);
  const valid = Number.isFinite(amount) && amount > 0 && amount < 100;
  const previewMg = valid ? Math.round(amount * mgPerUnit) : 0;
  // 整数単位かどうかで step を切り替え (g は小数、本/錠/カプセルは整数)
  const isIntegerUnit = unit !== "g";

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) onAdd(amount);
      }}
      className="flex items-center gap-2"
    >
      <span className="w-28 shrink-0 text-xs text-slate-200">{label}</span>
      <input
        type="number"
        inputMode={isIntegerUnit ? "numeric" : "decimal"}
        min={isIntegerUnit ? 1 : 0.1}
        max={99}
        step={isIntegerUnit ? 1 : "any"}
        value={amountStr}
        onChange={(e) => setAmountStr(e.target.value)}
        className="w-16 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-right text-xs text-slate-200 tabular-nums focus:border-amber-500 focus:outline-none"
      />
      <span className="w-12 shrink-0 text-[10px] text-slate-500">{unit}</span>
      <span className="ml-auto w-16 text-right font-mono text-xs tabular-nums text-amber-400/70">
        {previewMg} mg
      </span>
      <button
        type="submit"
        disabled={!valid || pending}
        className="rounded-full border border-amber-700/60 bg-amber-900/20 px-3 py-1 text-xs text-amber-200 hover:bg-amber-900/50 disabled:opacity-30"
      >
        + 記録
      </button>
    </form>
  );
}

function ManualInput({
  onAdd,
  pending,
}: {
  onAdd: (mg: number) => void;
  pending: boolean;
}) {
  const [mg, setMg] = useState("");
  const value = parseFloat(mg);
  const valid = Number.isFinite(value) && value > 0 && value < 1000;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) {
          onAdd(value);
          setMg("");
        }
      }}
      className="flex items-center gap-2"
    >
      <span className="w-28 shrink-0 text-xs text-slate-200">mg 直接</span>
      <input
        type="number"
        inputMode="numeric"
        min={1}
        max={999}
        step={1}
        placeholder="任意"
        value={mg}
        onChange={(e) => setMg(e.target.value)}
        className="w-16 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-right text-xs text-slate-200 tabular-nums focus:border-amber-500 focus:outline-none"
      />
      <span className="w-12 shrink-0 text-[10px] text-slate-500">mg</span>
      <span className="ml-auto w-16 text-right font-mono text-xs tabular-nums text-amber-400/70">
        {valid ? `${Math.round(value)} mg` : "--"}
      </span>
      <button
        type="submit"
        disabled={!valid || pending}
        className="rounded-full border border-amber-700/60 bg-amber-900/20 px-3 py-1 text-xs text-amber-200 hover:bg-amber-900/50 disabled:opacity-30"
      >
        + 記録
      </button>
    </form>
  );
}

function IntakeList({
  items,
  totalMg,
  existingResidualMg,
  historyHours,
  onChangeHistoryHours,
  onDelete,
  deletingId,
  onEdit,
}: {
  items: CaffeineIntake[];
  totalMg: number;
  existingResidualMg?: number;
  historyHours: number;
  onChangeHistoryHours: (h: number) => void;
  onDelete: (id: number) => void;
  deletingId: number | null;
  onEdit: (id: number) => void;
}) {
  return (
    <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-[10px] uppercase tracking-wider text-slate-500">
        <div className="flex items-center gap-1">
          <span>履歴</span>
          {[24, 72, 168, 720].map((h) => (
            <button
              key={h}
              onClick={() => onChangeHistoryHours(h)}
              className={`rounded border px-1.5 py-0.5 text-[9px] tracking-wider ${
                historyHours === h
                  ? "border-amber-600/60 bg-amber-900/30 text-amber-200"
                  : "border-slate-700 text-slate-500 hover:text-slate-300"
              }`}
            >
              {h === 24 ? "24h" : h === 72 ? "3d" : h === 168 ? "7d" : "30d"}
            </button>
          ))}
        </div>
        <span className="font-mono normal-case tabular-nums text-slate-400">
          {items.length} 件 · 摂取 {Math.round(totalMg)} mg / 体内残{" "}
          {Math.round(existingResidualMg ?? 0)} mg
        </span>
      </div>
      {items.length === 0 && (
        <p className="text-[10px] text-slate-600">
          この期間の記録はまだありません
        </p>
      )}
      <ul className="space-y-1">
        {items.map((it) => (
          <li key={it.id} className="flex items-baseline gap-2 text-xs">
            <span className="font-mono tabular-nums text-slate-400">
              {it.ts_jst}
            </span>
            <span className="text-slate-200">
              {SOURCE_LABEL[it.source as CaffeineSource] ?? it.source}
            </span>
            <span className="text-slate-500">
              {it.amount} {it.unit}
            </span>
            <span className="ml-auto font-mono tabular-nums text-amber-300">
              {Math.round(it.mg)} mg
            </span>
            <button
              onClick={() => onEdit(it.id)}
              className="text-slate-500 hover:text-amber-300"
              title="編集"
            >
              ✎
            </button>
            <button
              onClick={() => onDelete(it.id)}
              disabled={deletingId === it.id}
              className="text-slate-600 hover:text-rose-400 disabled:opacity-30"
              title="削除"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EditModal({
  item,
  onClose,
  onSave,
}: {
  item: CaffeineIntake | null;
  onClose: () => void;
  onSave: (body: {
    ts_iso?: string;
    amount?: number;
    source?: CaffeineSource;
    note?: string;
  }) => void;
}) {
  // existing ts (ISO with tz) を datetime-local 形式 (JST) に変換
  const initialLocal = item
    ? new Date(item.ts)
        .toLocaleString("sv-SE", { timeZone: "Asia/Tokyo" })
        .slice(0, 16)
        .replace(" ", "T")
    : "";

  const [tsLocal, setTsLocal] = useState(initialLocal);
  const [amount, setAmount] = useState(item ? String(item.amount) : "");
  const [source, setSource] = useState<CaffeineSource>(
    (item?.source as CaffeineSource) ?? "manual",
  );
  const [note, setNote] = useState(item?.note ?? "");

  if (!item) return null;

  const handleSave = () => {
    const amt = parseFloat(amount);
    const body: {
      ts_iso?: string;
      amount?: number;
      source?: CaffeineSource;
      note?: string;
    } = {};
    if (tsLocal && tsLocal !== initialLocal) {
      body.ts_iso = localToJstIso(tsLocal);
    }
    if (Number.isFinite(amt) && amt > 0 && amt !== item.amount) {
      body.amount = amt;
    }
    if (source !== item.source) body.source = source;
    if (note !== (item.note ?? "")) body.note = note;
    onSave(body);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 text-sm tracking-wider text-slate-300">
          カフェイン記録の編集
        </div>
        <div className="space-y-3 text-xs">
          <label className="flex items-center justify-between gap-3">
            <span className="text-slate-400">日時</span>
            <input
              type="datetime-local"
              value={tsLocal}
              onChange={(e) => setTsLocal(e.target.value)}
              className="flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-200"
            />
          </label>
          <label className="flex items-center justify-between gap-3">
            <span className="text-slate-400">種類</span>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value as CaffeineSource)}
              className="flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-200"
            >
              {(
                [
                  "instant_coffee",
                  "canned_coffee",
                  "nespresso",
                  "green_tea",
                  "ibuquick",
                  "bufferin_premium",
                  "manual",
                ] as CaffeineSource[]
              ).map((s) => (
                <option key={s} value={s}>
                  {SOURCE_LABEL[s]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center justify-between gap-3">
            <span className="text-slate-400">量</span>
            <input
              type="number"
              inputMode="decimal"
              min={0.1}
              step="any"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-24 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-right text-slate-200 tabular-nums"
            />
          </label>
          <label className="flex items-start justify-between gap-3">
            <span className="pt-1 text-slate-400">メモ</span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              className="flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-200"
            />
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400 hover:bg-slate-800"
          >
            キャンセル
          </button>
          <button
            onClick={handleSave}
            className="rounded-full border border-amber-700/60 bg-amber-900/30 px-3 py-1 text-xs text-amber-200 hover:bg-amber-900/60"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
