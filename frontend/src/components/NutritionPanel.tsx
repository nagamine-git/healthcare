import type { Nutrition, NutritionField, TargetRange } from "../lib/api";
import { RangeBar, formatRange } from "./RangeBar";

type Props = {
  nutrition?: Nutrition;
};

export function NutritionPanel({ nutrition: n }: Props) {
  if (!n) return null;

  const rows: Array<{
    label: string;
    field: NutritionField;
    target: TargetRange | null;
    sub?: string;
  }> = [
    {
      label: "カロリー",
      field: n.kcal_intake,
      target: n.targets.kcal_intake,
      sub: n.tdee.value
        ? `TDEE 推定 ${Math.round(n.tdee.value)} kcal (BMR ${n.tdee.bmr ?? "—"} + 活動)`
        : undefined,
    },
    {
      label: "タンパク質",
      field: n.protein_g,
      target: n.targets.protein_g,
    },
    {
      label: "水分",
      field: n.water_ml,
      target: n.targets.water_ml,
      sub: n.water_ml.today_actual != null ? "Garmin Hydration 由来" : undefined,
    },
  ];

  const minor: Array<{
    label: string;
    field: NutritionField | undefined;
    target: TargetRange | null;
  }> = [
    { label: "脂質", field: n.fat_g, target: n.targets.fat_g },
    { label: "炭水化物", field: n.carb_g, target: n.targets.carb_g },
    { label: "食物繊維", field: n.fiber_g, target: n.targets.fiber_g ?? null },
    { label: "ナトリウム", field: n.sodium_mg, target: n.targets.sodium_mg ?? null },
  ];

  return (
    <div className="rounded-xl bg-hull/70 p-4 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-ink-dim">栄養</h3>
        {!n.logged_today && (
          <span className="rounded-full border border-hairline bg-panel/40 px-2 py-0.5 text-[10px] text-ink-dim">
            食事ログ未記録 (推定値)
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {rows.map((r) => (
          <NutritionRow key={r.label} {...r} />
        ))}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {minor.map((r) => (
          <MinorRow key={r.label} {...r} />
        ))}
      </div>
    </div>
  );
}

function NutritionRow({
  label,
  field,
  target,
  sub,
}: {
  label: string;
  field: NutritionField;
  target: TargetRange | null;
  sub?: string;
}) {
  const cur = field.value;
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="min-w-0 truncate text-ink-dim">
          {label}
          {field.estimated && <span className="ml-1 text-ink-faint">(推定)</span>}
        </span>
        <span className="whitespace-nowrap tabular-nums text-ink-dim">
          {target ? formatRange(cur, target) : `${cur ?? "—"}`}
        </span>
      </div>
      {sub && <div className="truncate text-[10px] text-ink-faint">{sub}</div>}
      {target ? (
        <RangeBar current={cur} target={target} />
      ) : (
        <div className="h-2 rounded-full bg-panel" />
      )}
    </div>
  );
}

function MinorRow({
  label,
  field,
  target,
}: {
  label: string;
  field: NutritionField | undefined;
  target: TargetRange | null;
}) {
  if (!field) return null;
  const cur = field.value;
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="min-w-0 truncate text-ink-dim">
          {label}
          {field.estimated && <span className="ml-1 text-ink-faint">(推)</span>}
        </span>
        <span className="whitespace-nowrap tabular-nums text-ink-dim">
          {target ? formatRange(cur, target) : cur != null ? Math.round(cur) : "—"}
        </span>
      </div>
      {target ? (
        <RangeBar current={cur} target={target} />
      ) : (
        <div className="h-1 rounded-full bg-panel" />
      )}
    </div>
  );
}
