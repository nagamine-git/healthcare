import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AlcoholIntake, AlcoholSource } from "../lib/api";
import { localToJstIso } from "../lib/datetime";

const STORAGE_KEY = "healthcare:alcoholPanelOpen";

const SOURCE_LABEL: Record<AlcoholSource, string> = {
  beer_glass: "ビール 中ジョッキ",
  beer_can_500: "ビール 500ml 缶",
  wine_glass: "ワイン グラス",
  sake_go: "日本酒 1 合",
  shochu_mizuwari: "焼酎 水割り",
  highball: "ハイボール",
  strong_chuhai: "ストロング系チューハイ",
  manual: "g 直接",
};

export function AlcoholPanel() {
  const qc = useQueryClient();
  const [open, setOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, open ? "1" : "0");
    } catch {
      // ignore
    }
  }, [open]);

  const presets = useQuery({
    queryKey: ["alcohol-presets"],
    queryFn: api.alcoholPresets,
    staleTime: 5 * 60_000,
    enabled: open,
  });
  const intakes = useQuery({
    queryKey: ["alcohol-list"],
    queryFn: () => api.alcoholList(168),
    refetchInterval: 60_000,
    enabled: open,
  });
  const add = useMutation({
    mutationFn: ({
      source,
      amount,
      tsIso,
    }: {
      source: AlcoholSource;
      amount: number;
      tsIso?: string;
    }) => api.alcoholAdd(source, amount, { ts_iso: tsIso }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alcohol-list"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });
  const del = useMutation({
    mutationFn: (id: number) => api.alcoholDelete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alcohol-list"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const [tsLocal, setTsLocal] = useState("");

  const items = intakes.data?.items ?? [];
  const totalG = intakes.data?.total_grams ?? 0;
  const drinks = intakes.data?.drinks_equivalent ?? 0;

  return (
    <div className="rounded-xl bg-hull/70 p-4 sm:p-6">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <div className="flex items-baseline gap-3">
          <h3 className="text-sm tracking-wider text-ink-dim">アルコール記録</h3>
          {!open && intakes.data && intakes.data.items.length > 0 && (
            <span className="text-[10px] tabular-nums text-ink-faint">
              直近 7d 計 {Math.round(intakes.data.total_grams)} g
            </span>
          )}
        </div>
        <span className="text-xs text-ink-faint">{open ? "▾" : "▸"}</span>
      </button>
      {!open && (
        <p className="mt-1 text-[10px] text-ink-faint">
          飲んだ時に展開して記録 (純アルコール g、1 drink ≈ 10g 換算)
        </p>
      )}
      {!open && null}
      {open && (
        <>
      <div className="mb-3 mt-3 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[10px] text-ink-faint">
          純アルコール g、1 drink ≈ 10g 換算
        </span>
      </div>

      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[10px] uppercase tracking-wider text-ink-faint">
          飲んだ
        </span>
        <label className="flex items-center gap-1 text-[10px] text-ink-faint">
          記録時刻
          <input
            type="datetime-local"
            value={tsLocal}
            onChange={(e) => setTsLocal(e.target.value)}
            className="rounded border border-hairline bg-hull px-1.5 py-0.5 text-[10px] text-ink-dim focus:border-act focus:outline-none"
          />
          {tsLocal ? (
            <button
              type="button"
              onClick={() => setTsLocal("")}
              className="text-ink-faint hover:text-ink-dim"
              title="クリア"
            >
              ×
            </button>
          ) : (
            <span className="text-ink-faint">空=今</span>
          )}
        </label>
      </div>

      <div className="space-y-2">
        {presets.data &&
          (
            [
              "beer_glass",
              "beer_can_500",
              "wine_glass",
              "sake_go",
              "shochu_mizuwari",
              "highball",
              "strong_chuhai",
            ] as AlcoholSource[]
          ).map((source) => {
            const p = presets.data[source];
            if (!p) return null;
            return (
              <PresetRow
                key={source}
                label={SOURCE_LABEL[source]}
                unit={p.unit}
                gramsPerUnit={p.grams_per_unit}
                defaultAmount={p.default_amount}
                pending={add.isPending}
                onAdd={(amount) =>
                  add.mutate({ source, amount, tsIso: localToJstIso(tsLocal) })
                }
              />
            );
          })}
        <ManualInput
          onAdd={(grams) =>
            add.mutate({
              source: "manual",
              amount: grams,
              tsIso: localToJstIso(tsLocal),
            })
          }
          pending={add.isPending}
        />
      </div>

      <IntakeList
        items={items}
        totalG={totalG}
        drinks={drinks}
        onDelete={(id) => del.mutate(id)}
        deletingId={del.variables ?? null}
      />
        </>
      )}
    </div>
  );
}

function PresetRow({
  label,
  unit,
  gramsPerUnit,
  defaultAmount,
  pending,
  onAdd,
}: {
  label: string;
  unit: string;
  gramsPerUnit: number;
  defaultAmount: number;
  pending: boolean;
  onAdd: (amount: number) => void;
}) {
  const [amountStr, setAmountStr] = useState(String(defaultAmount));
  const amount = parseFloat(amountStr);
  const valid = Number.isFinite(amount) && amount > 0 && amount < 100;
  const previewG = valid ? Math.round(amount * gramsPerUnit) : 0;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) onAdd(amount);
      }}
      className="flex items-center gap-2"
    >
      <span className="w-40 shrink-0 text-xs text-ink">{label}</span>
      <input
        type="number"
        inputMode="decimal"
        min={0.1}
        max={99}
        step="any"
        value={amountStr}
        onChange={(e) => setAmountStr(e.target.value)}
        className="w-16 rounded border border-hairline bg-hull px-2 py-1 text-right text-xs text-ink tabular-nums focus:border-act focus:outline-none"
      />
      <span className="w-12 shrink-0 text-[10px] text-ink-faint">{unit}</span>
      <span className="ml-auto w-16 text-right telemetry-num text-xs tabular-nums text-act-300/70">
        {previewG} g
      </span>
      <button
        type="submit"
        disabled={!valid || pending}
        className="rounded-full border border-act-700/60 bg-act-700/20 px-3 py-1 text-xs text-act-300 hover:bg-act-700/50 disabled:opacity-30"
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
  onAdd: (grams: number) => void;
  pending: boolean;
}) {
  const [g, setG] = useState("");
  const value = parseFloat(g);
  const valid = Number.isFinite(value) && value > 0 && value < 200;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) {
          onAdd(value);
          setG("");
        }
      }}
      className="flex items-center gap-2"
    >
      <span className="w-40 shrink-0 text-xs text-ink">g 直接</span>
      <input
        type="number"
        inputMode="decimal"
        min={1}
        max={200}
        step="any"
        placeholder="任意"
        value={g}
        onChange={(e) => setG(e.target.value)}
        className="w-16 rounded border border-hairline bg-hull px-2 py-1 text-right text-xs text-ink tabular-nums focus:border-act focus:outline-none"
      />
      <span className="w-12 shrink-0 text-[10px] text-ink-faint">g</span>
      <span className="ml-auto w-16 text-right telemetry-num text-xs tabular-nums text-act-300/70">
        {valid ? `${Math.round(value)} g` : "--"}
      </span>
      <button
        type="submit"
        disabled={!valid || pending}
        className="rounded-full border border-act-700/60 bg-act-700/20 px-3 py-1 text-xs text-act-300 hover:bg-act-700/50 disabled:opacity-30"
      >
        + 記録
      </button>
    </form>
  );
}

function IntakeList({
  items,
  totalG,
  drinks,
  onDelete,
  deletingId,
}: {
  items: AlcoholIntake[];
  totalG: number;
  drinks: number;
  onDelete: (id: number) => void;
  deletingId: number | null;
}) {
  return (
    <div className="mt-3 rounded-xl border border-panel bg-hull/40 p-3">
      <div className="mb-2 flex items-baseline justify-between text-[10px] uppercase tracking-wider text-ink-faint">
        <span>直近 7 日の記録</span>
        <span className="telemetry-num normal-case tabular-nums text-ink-dim">
          {items.length} 件 · 計 {Math.round(totalG)} g (約 {drinks.toFixed(1)} drinks)
        </span>
      </div>
      {items.length === 0 && (
        <p className="text-[10px] text-ink-faint">
          直近 7 日の記録はありません
        </p>
      )}
      <ul className="space-y-1">
        {items.slice(-10).map((it) => (
          <li key={it.id} className="flex items-baseline gap-2 text-xs">
            <span className="telemetry-num tabular-nums text-ink-dim">
              {it.ts_jst}
            </span>
            <span className="text-ink">
              {SOURCE_LABEL[it.source as AlcoholSource] ?? it.source}
            </span>
            <span className="text-ink-faint">
              {it.amount} {it.unit}
            </span>
            <span className="ml-auto telemetry-num tabular-nums text-act-300">
              {Math.round(it.grams)} g
            </span>
            <button
              onClick={() => onDelete(it.id)}
              disabled={deletingId === it.id}
              className="text-ink-faint hover:text-risk disabled:opacity-30"
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
