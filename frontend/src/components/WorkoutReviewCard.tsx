import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Dumbbell, RotateCcw, Sparkles } from "lucide-react";
import type { WorkoutExerciseReview, WorkoutReviewItem, WorkoutReviewsResp } from "../lib/api";
import { api } from "../lib/api";
import { LoadingState } from "./ui/cockpit";

/**
 * ワークアウトの AI 評価 (総合 + 筋トレは種目ごと)。タップで生成し、以後は保存済みを表示
 * (LLM コストはタップ時のみ)。既存の「評価」は総合コメント1つだけで、実は
 * Garmin exerciseSets (種目/rep/重量) が取れているのに使われていなかった
 * (バックエンドは持っていたが、このカード自体がフロントに存在しなかった)。
 *
 * 「再分析」は保存済み評価の明示的な force 上書き。サーバー側に日次上限があり (429)、
 * 連打防止はこのコンポーネント側でも pending 中ボタンを disable することで二重に防ぐ。
 */

const TONE_CLS: Record<string, string> = {
  good: "border-prog-500/40 bg-prog-500/10 text-prog-300",
  caution: "border-act-700/50 bg-act/10 text-act-300",
  info: "border-hairline bg-panel/60 text-ink-dim",
};

function fmtDelta(ex: WorkoutExerciseReview): string | null {
  if (ex.volume_delta_kg == null) return null;
  const sign = ex.volume_delta_kg >= 0 ? "+" : "";
  const pct =
    ex.volume_delta_pct != null ? ` (${ex.volume_delta_pct >= 0 ? "+" : ""}${ex.volume_delta_pct}%)` : "";
  return `前回比 ${sign}${ex.volume_delta_kg}kg${pct}`;
}

function ExerciseReviewRow({ ex }: { ex: WorkoutExerciseReview }) {
  const delta = fmtDelta(ex);
  return (
    <li className={`rounded-lg border px-2.5 py-1.5 ${TONE_CLS[ex.tone] ?? TONE_CLS.info}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
        <span className="text-[12px] font-medium text-ink">{ex.name_ja}</span>
        <span className="text-[10px] tabular-nums text-ink-faint">
          {ex.set_count}セット
          {ex.rep_range && ` · ${ex.rep_range[0]}〜${ex.rep_range[1]}回`}
          {ex.volume_kg != null && ` · ${ex.volume_kg}kg`}
        </span>
      </div>
      {delta && <div className="mt-0.5 text-[10px] text-ink-faint">{delta}</div>}
      <p className="mt-1 text-[11px] leading-relaxed">{ex.comment}</p>
    </li>
  );
}

function ReviewRow({ item }: { item: WorkoutReviewItem }) {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const gen = useMutation({
    mutationFn: (force: boolean) => api.workoutReviewCreate(item.workout_id, force),
    onSuccess: (updated) => {
      setErr(null);
      qc.setQueryData<WorkoutReviewsResp>(["workout-reviews"], (old) => ({
        items: (old?.items ?? []).map((x) => (x.workout_id === updated.workout_id ? updated : x)),
      }));
    },
    onError: (e: Error) => {
      setErr(
        e.message.startsWith("429")
          ? "本日の再分析の上限に達しました。日をまたいでからお試しください。"
          : `評価に失敗しました (${e.message})`,
      );
    },
  });

  const hasReview = !!item.review_text;

  return (
    <li className="rounded-xl border border-hairline bg-hull/40 p-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <Dumbbell size={13} className="shrink-0 text-emerald-300" />
        <span className="text-[12px] font-medium text-ink">{item.type_label}</span>
        <span className="text-[11px] tabular-nums text-ink-faint">
          {item.date} {item.start_jst}
        </span>
        {item.duration_min != null && (
          <span className="text-[11px] text-ink-faint">{item.duration_min}分</span>
        )}
        {!hasReview && (
          <button
            onClick={() => gen.mutate(false)}
            disabled={gen.isPending}
            className="press ml-auto flex items-center gap-1 rounded-full border border-ink-faint px-2.5 py-1 text-[11px] text-ink-dim hover:bg-panel disabled:opacity-50"
          >
            <Sparkles size={11} />
            {gen.isPending ? "評価中…" : "評価する"}
          </button>
        )}
      </div>

      {hasReview && (
        <>
          <p
            className={`mt-2 rounded-lg border px-2.5 py-1.5 text-[12px] leading-relaxed ${
              TONE_CLS[item.review_tone ?? "info"]
            }`}
          >
            {item.review_text}
          </p>

          {item.review_exercises && item.review_exercises.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {item.review_exercises.map((ex, i) => (
                <ExerciseReviewRow key={`${ex.category}-${ex.name}-${i}`} ex={ex} />
              ))}
            </ul>
          )}

          <div className="mt-2 flex items-center gap-2">
            <button
              onClick={() => gen.mutate(true)}
              disabled={gen.isPending}
              className="press flex items-center gap-1 rounded-full border border-ink-faint px-2.5 py-1 text-[11px] text-ink-dim hover:bg-panel disabled:opacity-50"
            >
              <RotateCcw size={11} />
              {gen.isPending ? "再分析中…" : "再分析"}
            </button>
            {item.reviewed_at && (
              <span className="text-[10px] text-ink-faint">
                {new Date(item.reviewed_at).toLocaleString(undefined, {
                  month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
                })}
              </span>
            )}
          </div>
          {err && <p className="mt-1 text-[10px] text-risk">{err}</p>}
        </>
      )}
    </li>
  );
}

export function WorkoutReviewCard() {
  const [open, setOpen] = useState(true);
  const q = useQuery({ queryKey: ["workout-reviews"], queryFn: () => api.workoutReviews(3) });

  if (q.isLoading) return <LoadingState height="h-24" />;
  if (!q.data || q.data.items.length === 0) return null;

  return (
    <section className="rounded-xl bg-hull/40 p-3">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1.5 text-left">
        <Sparkles size={14} className="text-emerald-300" />
        <span className="text-xs uppercase tracking-wider text-ink-dim">ワークアウトAI評価</span>
        <span className="ml-auto text-[10px] text-ink-faint">{q.data.items.length}件</span>
        <ChevronDown size={14} className={`text-ink-faint transition-transform ${open ? "" : "-rotate-90"}`} />
      </button>
      {open && (
        <ul className="mt-2 space-y-2">
          {q.data.items.map((item) => (
            <ReviewRow key={item.workout_id} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}
