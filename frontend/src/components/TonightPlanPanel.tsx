import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import type { SleepWindow, TonightPlan } from "../lib/api";

type Props = {
  plan?: TonightPlan;
};

/** 「起床する日」= 次に迎える起床の日付 (JST)。plan.sleep_now や深夜帯の判定は
 *  backend が済ませているので、ここでは wake が今日の朝か翌朝かだけを見る。 */
function wakeDateISO(plan: TonightPlan): string {
  const now = new Date();
  const [h, m] = plan.wake.split(":").map(Number);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m);
  // 起床時刻がすでに過ぎていれば翌日の朝
  const d = today > now ? today : new Date(today.getTime() + 24 * 3600_000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 起床時刻を「その日だけ」変える。恒久の既定は設定タブの起床時刻。 */
function WakeEditor({ plan }: { plan: TonightPlan }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(plan.wake);
  const date = wakeDateISO(plan);
  const done = () => {
    // 起床時刻は今夜の計画・呼吸法・通知・いまコレ等が参照するので広めに再取得する
    for (const k of ["today", "wind-down", "meditation", "next-action", "timeline"]) {
      qc.invalidateQueries({ queryKey: [k] });
    }
    setOpen(false);
  };
  const save = useMutation({
    mutationFn: () => api.sleepPlanOverrideSet({ date, wake_time: value }),
    onSuccess: done,
  });
  const clear = useMutation({
    mutationFn: () => api.sleepPlanOverrideClear(date),
    onSuccess: done,
  });

  if (!open) {
    return (
      <button onClick={() => { setValue(plan.wake); setOpen(true); }}
        className="press mt-2 text-[10px] text-ink-faint underline">
        {plan.wake_overridden ? "起床時刻を変更中 (タップで編集)" : "この日だけ起床時刻を変える"}
      </button>
    );
  }
  const busy = save.isPending || clear.isPending;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-void/40 p-2">
      <span className="text-[10px] text-ink-faint">{date} の起床</span>
      <input type="time" value={value} onChange={(e) => setValue(e.target.value)}
        className="rounded bg-hull px-2 py-1 text-[12px] tabular-nums text-ink" />
      <button onClick={() => save.mutate()} disabled={busy}
        className="press rounded bg-act-500/20 px-2 py-1 text-[11px] text-act-300 disabled:opacity-50">
        この日だけ適用
      </button>
      {plan.wake_overridden && (
        <button onClick={() => clear.mutate()} disabled={busy}
          className="press rounded px-2 py-1 text-[11px] text-ink-dim disabled:opacity-50">
          既定に戻す
        </button>
      )}
      <button onClick={() => setOpen(false)} className="press px-1 text-[11px] text-ink-faint">閉じる</button>
    </div>
  );
}

function fmtHm(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h${m.toString().padStart(2, "0")}m`;
}

export function TonightPlanPanel({ plan }: Props) {
  if (!plan) return null;
  const sleepNow = plan.sleep_now === true;
  return (
    <div className={`rounded-xl bg-hull/70 p-4 sm:p-6 ${sleepNow ? "ring-1 ring-rose-400/50" : ""}`}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-ink-dim">今夜のリズム</h3>
        <span className="text-[10px] text-ink-faint">
          目安睡眠 {fmtHm(plan.estimated_sleep_min)} / 目標 {fmtHm(plan.target_sleep_min)}
        </span>
      </div>
      {sleepNow && (
        <div className="mb-3 rounded-lg border border-rose-400/40 bg-rose-950/30 px-3 py-2 text-sm text-rose-300">
          🌙 就寝目安時刻を過ぎています。<b>今すぐ寝てください</b>
          <span className="ml-1 text-rose-300/70">
            (今から寝れば目覚め {plan.sleep_end ?? plan.wake} まで約 {fmtHm(plan.estimated_sleep_min)})
          </span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Slot
          label="夕食"
          time={plan.dinner_start && plan.dinner_end ? `${plan.dinner_start}–${plan.dinner_end}` : plan.dinner_cutoff}
          hint={sleepNow ? "済 (昨夜)" : "食べ始め–食べ終わり・遅すぎない時間に"}
        />
        <Slot
          label="入浴"
          time={plan.bath_start && plan.bath_end ? `${plan.bath_start}–${plan.bath_end}` : plan.bath}
          hint={sleepNow ? "済 (昨夜)" : `${plan.bath_method ?? "湯船"}${plan.bath_temp_c ? ` ${plan.bath_temp_c}℃` : ""}・就寝90分前に上がる`}
        />
        <Slot
          label="就寝"
          time={sleepNow ? "今すぐ" : plan.bedtime}
          range={sleepNow ? undefined : plan.windows?.bedtime}
          hint={sleepNow ? `目安 ${plan.bedtime} 経過` : plan.compressed ? "圧縮中" : "目標"}
          accent={sleepNow ? "rose" : plan.compressed ? "amber" : "emerald"}
        />
        {/* 「起床」= 布団から出る時刻。目覚め (睡眠終了) との差＝布団の中は、
            逆算の基準がなぜ起床時刻そのものでないかの説明になるので必ず併記する。 */}
        <Slot label="起床 (布団を出る)" time={plan.wake} range={plan.windows?.wake}
          hint={[
            plan.lingering_min && plan.sleep_end
              ? `目覚め ${plan.sleep_end}・布団の中 ${plan.lingering_min}分`
              : null,
            plan.wake_overridden ? "この日だけ変更中" : sleepNow ? "今日の朝" : "次の日",
          ].filter(Boolean).join(" / ")}
          accent={plan.wake_overridden ? "amber" : undefined} />
      </div>
      <WakeEditor plan={plan} />
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
        {plan.exercise_cutoff_time && (
          <span>🏃 高強度運動 <b className="tabular-nums text-act-300">{plan.exercise_cutoff_time}</b>
            <span className="text-ink-faint"> まで</span></span>
        )}
        {plan.dim_light_time && (
          <span>🌙 照明↓ <b className="tabular-nums text-indigo-200">{plan.dim_light_time}</b>
            <span className="text-ink-faint"> 以降</span></span>
        )}
      </div>
      {(() => {
        const restNotes = sleepNow ? plan.notes.slice(1) : plan.notes;
        return restNotes.length > 0 ? (
          <p className="mt-3 text-[10px] leading-relaxed text-act-300/80">
            {restNotes.join(" / ")}
          </p>
        ) : null;
      })()}
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
  accent?: "slate" | "emerald" | "amber" | "rose";
}) {
  const color =
    accent === "emerald"
      ? "text-prog-300"
      : accent === "amber"
      ? "text-act-300"
      : accent === "rose"
      ? "text-rose-300"
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
