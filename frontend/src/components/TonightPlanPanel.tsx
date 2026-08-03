import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronRight, Clock, MonitorOff } from "lucide-react";
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
    // 起床時刻はこの計画すべての起点なので、変更は「気づける・押しやすい」必要がある。
    // 小さな下線リンクだと存在に気づかれず、予定が変わった日に計画が現実と食い違ったまま
    // 放置されてしまう。時刻を大きく出したタップ領域の広いチップにする。
    return (
      <button onClick={() => { setValue(plan.wake); setOpen(true); }}
        className={`press mt-2 flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left transition active:scale-[0.99] ${
          plan.wake_overridden
            ? "border-act-500/50 bg-act/10"
            : "border-hairline bg-panel/50 hover:bg-panel"
        }`}
      >
        <Clock size={15} className={plan.wake_overridden ? "text-act-300" : "text-ink-dim"} />
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block text-[12px] text-ink">
            {plan.wake_overridden ? "この日の起床時刻を変更中" : "明日の起床時刻を変える"}
          </span>
          <span className="block text-[10px] text-ink-faint">
            {plan.wake_overridden ? "タップして編集・既定に戻す" : "予定が違う日はここから"}
          </span>
        </span>
        <span className={`shrink-0 text-[15px] font-semibold tabular-nums ${
          plan.wake_overridden ? "text-act-300" : "text-ink"}`}>
          {plan.wake}
        </span>
        <ChevronRight size={14} className="shrink-0 text-ink-faint" />
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
          🌙 布団に入る目安を過ぎています。<b>今すぐ寝てください</b>
          <span className="ml-1 text-rose-300/70">
            (今から布団に入れば目覚め {plan.sleep_end ?? plan.wake} まで約 {fmtHm(plan.estimated_sleep_min)})
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
        {/* 表示するのは「布団に入る」= 実際に取る行動。plan.bedtime は**寝つく**目標
            なので、そのまま就寝時刻として出すと入眠潜時のぶん寝るのが遅れる。 */}
        <Slot
          label="就寝 (布団に入る)"
          time={sleepNow ? "今すぐ" : plan.in_bed ?? plan.bedtime}
          range={sleepNow ? undefined : plan.windows?.in_bed ?? plan.windows?.bedtime}
          hint={[
            plan.in_bed && plan.sleep_onset_min
              ? `寝つく ${plan.bedtime}・入眠まで${plan.sleep_onset_min}分${
                  plan.sleep_onset_source === "measured" ? "(実測)" : "(目安)"
                }`
              : null,
            sleepNow ? `目安 ${plan.in_bed ?? plan.bedtime} 経過` : plan.compressed ? "圧縮中" : "目標",
          ].filter(Boolean).join(" / ")}
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
      {/* 「動かせない線」と「幅を持たせてよいもの」を分けて出す。
          全部を固定の予定表として見せると、順番が変わる日に計画ごと無視されてしまう
          (入浴を就寝直前に固定していた頃、実際はトレーニング直後に入っていて破綻した)。 */}
      {plan.hard_deadlines && plan.hard_deadlines.length > 0 && (
        <div className="mt-3 rounded-lg border border-rose-400/25 bg-rose-950/15 p-2.5">
          <div className="mb-1.5 flex items-center gap-1.5">
            <MonitorOff size={12} className="text-rose-300" />
            <span className="text-[10px] uppercase tracking-wider text-rose-300">ここは動かせない</span>
          </div>
          <ul className="space-y-1">
            {plan.hard_deadlines.map((d) => (
              <li key={d.key} className="flex items-baseline gap-2 leading-tight">
                <span className="w-14 shrink-0 text-right text-[13px] font-semibold tabular-nums text-rose-200">{d.time}</span>
                <span className="min-w-0 flex-1">
                  <span className="text-[12px] text-ink">{d.label}</span>
                  <span className="ml-1.5 text-[10px] text-ink-faint">{d.why}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {plan.flexible && plan.flexible.length > 0 && (
        <div className="mt-2 rounded-lg border border-hairline bg-panel/40 p-2.5">
          <span className="mb-1.5 block text-[10px] uppercase tracking-wider text-ink-dim">ここは順番も時刻も自由</span>
          <ul className="space-y-1">
            {plan.flexible.map((f) => (
              <li key={f.key} className="flex items-baseline gap-2 leading-tight">
                <span className="w-24 shrink-0 text-right text-[12px] tabular-nums text-ink-dim">{f.window}</span>
                <span className="min-w-0 flex-1">
                  <span className="text-[12px] text-ink">{f.label}</span>
                  <span className="ml-1.5 text-[10px] text-ink-faint">{f.why}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {plan.morning_light && (
        <div className="mt-2 text-[11px] text-ink-dim">
          🌅 朝の光浴 <b className="tabular-nums text-act-300">{plan.morning_light.start}–{plan.morning_light.end}</b>
          <span className="text-ink-faint"> 起床後すぐ屋外光</span>
        </div>
      )}
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
