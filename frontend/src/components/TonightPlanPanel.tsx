import type { SleepWindow, TonightPlan } from "../lib/api";

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
    <div className="rounded-xl bg-hull/70 p-4 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-ink-dim">今夜のリズム</h3>
        <span className="text-[10px] text-ink-faint">
          目安睡眠 {fmtHm(plan.estimated_sleep_min)} / 目標 {fmtHm(plan.target_sleep_min)}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Slot
          label="夕食"
          time={plan.dinner_start && plan.dinner_end ? `${plan.dinner_start}–${plan.dinner_end}` : plan.dinner_cutoff}
          hint="食べ始め–食べ終わり・遅すぎない時間に"
        />
        <Slot
          label="入浴"
          time={plan.bath_start && plan.bath_end ? `${plan.bath_start}–${plan.bath_end}` : plan.bath}
          hint={`${plan.bath_method ?? "湯船"}${plan.bath_temp_c ? ` ${plan.bath_temp_c}℃` : ""}・就寝90分前に上がる`}
        />
        <Slot
          label="就寝"
          time={plan.bedtime}
          range={plan.windows?.bedtime}
          hint={plan.compressed ? "圧縮中" : "目標"}
          accent={plan.compressed ? "amber" : "emerald"}
        />
        <Slot label="起床 (明朝)" time={plan.wake} range={plan.windows?.wake} hint="次の日" />
      </div>
      {/* 科学的に大事な timing (厳選) */}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-dim">
        {plan.morning_light && (
          <span>🌅 朝の光浴 <b className="tabular-nums text-act-300">{plan.morning_light.start}–{plan.morning_light.end}</b>
            <span className="text-ink-faint"> 起床後すぐ屋外光</span></span>
        )}
        {plan.caffeine_cutoff_time && (
          <span>☕ カフェイン最終 <b className="tabular-nums text-act-300">{plan.caffeine_cutoff_time}</b>
            <span className="text-ink-faint"> まで</span></span>
        )}
        {plan.dim_light_time && (
          <span>🌙 照明↓ <b className="tabular-nums text-indigo-200">{plan.dim_light_time}</b>
            <span className="text-ink-faint"> 以降</span></span>
        )}
      </div>
      {plan.notes.length > 0 && (
        <p className="mt-3 text-[10px] leading-relaxed text-act-300/80">
          {plan.notes.join(" / ")}
        </p>
      )}
    </div>
  );
}

function Slot({
  label,
  time,
  range,
  hint,
  accent = "slate",
}: {
  label: string;
  time: string;
  range?: SleepWindow;
  hint?: string;
  accent?: "slate" | "emerald" | "amber";
}) {
  const color =
    accent === "emerald"
      ? "text-prog-300"
      : accent === "amber"
      ? "text-act-300"
      : "text-ink";
  return (
    <div className="rounded-xl border border-panel bg-hull/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-ink-faint">
        {label}
      </div>
      {/* 推奨絶対時刻 (大) + 推奨範囲 (小) の両方。範囲(–入り)はやや小さく */}
      <div className={`telemetry-num tabular-nums ${time.includes("–") ? "text-base" : "text-xl"} ${color}`}>{time}</div>
      {range && (
        <div className="telemetry-num text-[10px] tabular-nums text-ink-dim">
          {range.start}–{range.end}
        </div>
      )}
      {hint && <div className="text-[10px] text-ink-faint">{hint}</div>}
    </div>
  );
}
