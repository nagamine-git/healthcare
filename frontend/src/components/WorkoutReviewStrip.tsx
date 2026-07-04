import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { api } from "../lib/api";
import type { WorkoutReviewItem, WorkoutReviewsResp } from "../lib/api";

/**
 * 直近ワークアウトの AI 一言評価。タップで生成 (LLM はその1回だけ)、以後は保存済みを表示。
 * 「今日の流れ」ハイライトの直下に置く自己完結ストリップ (DayStory 本体の配線は触らない)。
 */

const TONE_CLS: Record<string, string> = {
  good: "border-prog-500/40 bg-prog-500/10 text-prog-300",
  caution: "border-act-700/50 bg-act/10 text-act-300",
  info: "border-hairline bg-panel/60 text-ink-dim",
};

function Row({ it }: { it: WorkoutReviewItem }) {
  const qc = useQueryClient();
  const gen = useMutation({
    mutationFn: () => api.workoutReviewCreate(it.workout_id),
    onSuccess: (updated) => {
      qc.setQueryData<WorkoutReviewsResp>(["workout-reviews"], (old) =>
        old
          ? { items: old.items.map((x) => (x.workout_id === updated.workout_id ? updated : x)) }
          : old,
      );
    },
  });

  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="tabular-nums text-ink-faint">{it.start_jst}</span>
        <span className="text-ink-dim">
          {it.type_label}
          {it.duration_min != null && <span className="text-ink-faint"> {it.duration_min}分</span>}
        </span>
        {it.est_vo2max && (
          <span
            title={`${it.est_vo2max.note} (${it.est_vo2max.low}〜${it.est_vo2max.high})`}
            className="rounded-full bg-info/10 px-2 py-0.5 text-[10px] text-info-300"
          >
            推定VO2Max ≈{Math.round(it.est_vo2max.mid)}
            <span className="opacity-70"> ({it.est_vo2max.low}–{it.est_vo2max.high})</span>
          </span>
        )}
        {!it.review_text && (
          <button
            onClick={() => gen.mutate()}
            disabled={gen.isPending}
            className="ml-auto flex items-center gap-1 rounded-full bg-panel px-2 py-0.5 text-[10px] text-ink-dim transition hover:text-ink active:scale-95 disabled:opacity-50"
          >
            <Sparkles size={10} className="text-act-300" />
            {gen.isPending ? "評価中…" : "AI評価"}
          </button>
        )}
      </div>
      {gen.isError && (
        <p className="text-[10px] text-risk/80">評価の生成に失敗しました。もう一度どうぞ。</p>
      )}
      {it.review_text && (
        <p
          className={`rounded-lg border px-2.5 py-1.5 text-[11px] leading-relaxed ${
            TONE_CLS[it.review_tone ?? "info"]
          }`}
        >
          {it.review_text}
        </p>
      )}
    </div>
  );
}

export function WorkoutReviewStrip() {
  const q = useQuery({ queryKey: ["workout-reviews"], queryFn: () => api.workoutReviews(2) });
  const items = q.data?.items ?? [];
  if (items.length === 0) return null; // 直近にワークアウトが無ければ何も出さない

  return (
    <div className="space-y-1.5 rounded-xl bg-hull/40 p-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-dim">
        ワークアウト評価
      </div>
      {items.map((it) => (
        <Row key={it.workout_id} it={it} />
      ))}
    </div>
  );
}
