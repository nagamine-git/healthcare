import type { TonightPlan } from "../lib/api";

type Props = {
  plan?: TonightPlan;
};

function fmtHm(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h${m.toString().padStart(2, "0")}m`;
}

export function TonightPlanPanel({ plan }: Props) {
  if (!plan) return null;
  return (
    <div className="rounded-2xl bg-slate-900/70 p-4 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-slate-300">今夜のリズム</h3>
        <span className="text-[10px] text-slate-500">
          目安睡眠 {fmtHm(plan.estimated_sleep_min)} / 目標 {fmtHm(plan.target_sleep_min)}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Slot label="夕食終了" time={plan.dinner_cutoff} hint="就寝 3h 前" />
        <Slot label="入浴" time={plan.bath} hint="就寝 90 分前" />
        <Slot
          label="就寝"
          time={plan.bedtime}
          hint={plan.compressed ? "圧縮中" : "目標"}
          accent={plan.compressed ? "amber" : "emerald"}
        />
        <Slot label="起床 (明朝)" time={plan.wake} hint="次の日" />
      </div>
      {plan.notes.length > 0 && (
        <p className="mt-3 text-[10px] leading-relaxed text-amber-300/80">
          {plan.notes.join(" / ")}
        </p>
      )}
    </div>
  );
}

function Slot({
  label,
  time,
  hint,
  accent = "slate",
}: {
  label: string;
  time: string;
  hint?: string;
  accent?: "slate" | "emerald" | "amber";
}) {
  const color =
    accent === "emerald"
      ? "text-emerald-300"
      : accent === "amber"
      ? "text-amber-300"
      : "text-slate-200";
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={`font-mono text-xl tabular-nums ${color}`}>{time}</div>
      {hint && <div className="text-[10px] text-slate-500">{hint}</div>}
    </div>
  );
}
