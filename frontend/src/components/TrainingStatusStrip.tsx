import { useQuery } from "@tanstack/react-query";
import { Dumbbell } from "lucide-react";
import { api } from "../lib/api";
import { LoadingState } from "./ui/cockpit";

/**
 * トレーニング状況を「これまで→今→これから」で1本化 (2026-07-05)。
 * 散在していたトレ情報を1ストリップに。週の筋トレ回数が目標未満なら不足を赤く可視化し、
 * 「今日やれる部位」を提示して積極的に刺激を促す (under-training バイアス)。
 */

const VERDICT: Record<string, { label: string; cls: string }> = {
  enough: { label: "今週は十分", cls: "text-prog-300" },
  behind: { label: "やや不足", cls: "text-act-300" },
  way_behind: { label: "大幅に不足", cls: "text-risk" },
};

export function TrainingStatusStrip() {
  const q = useQuery({ queryKey: ["training-status"], queryFn: api.trainingStatus });
  if (q.isLoading) return <LoadingState height="h-20" />;
  if (!q.data) return null;
  const { past, now, next } = q.data;
  const v = VERDICT[now.verdict] ?? VERDICT.behind;
  const behind = now.verdict !== "enough";

  return (
    <section className="rounded-xl bg-hull/40 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <Dumbbell size={14} className="text-emerald-300" />
        <span className="text-xs uppercase tracking-wider text-ink-dim">トレーニング状況</span>
        <span className={`ml-auto text-[11px] font-semibold ${v.cls}`}>{v.label}</span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        {/* これまで */}
        <div className="rounded-lg bg-void/30 p-2">
          <div className="text-[9px] uppercase tracking-wider text-ink-faint">これまで(今週)</div>
          <div className="mt-1 text-[15px] font-semibold text-ink">
            <span className={behind ? "text-risk" : "text-prog-300"}>{past.week_strength}</span>
            <span className="text-[11px] text-ink-faint"> / {past.target_week}回 筋トレ</span>
          </div>
          <div className="text-[9px] text-ink-faint">有酸素 {past.week_cardio} · 2週で{past.strength_14d}回</div>
        </div>

        {/* 今 */}
        <div className="rounded-lg bg-void/30 p-2">
          <div className="text-[9px] uppercase tracking-wider text-ink-faint">今(回復)</div>
          <div className="mt-1 flex items-center justify-center gap-1.5 text-[12px]">
            <span className="text-prog-300" title="回復済み">●{now.recovered}</span>
            <span className="text-act-300" title="回復途中">●{now.recovering}</span>
            <span className="text-risk" title="直近に負荷">●{now.loaded}</span>
          </div>
          <div className="text-[9px] text-ink-faint">やれる / 途中 / 負荷</div>
        </div>

        {/* これから */}
        <div className="rounded-lg bg-void/30 p-2">
          <div className="text-[9px] uppercase tracking-wider text-ink-faint">これから</div>
          <div className="mt-1 text-[13px] font-semibold text-ink">
            {next.remaining_this_week > 0 ? (
              <span className="text-act-300">あと{next.remaining_this_week}回</span>
            ) : (
              <span className="text-prog-300">達成✓</span>
            )}
          </div>
          <div className="truncate text-[9px] text-ink-faint">
            {next.today_should_train.length > 0
              ? "今日: " + next.today_should_train.map((g) => g.label).join(" / ")
              : "回復待ち"}
          </div>
        </div>
      </div>

      {behind && next.today_should_train.length > 0 && (
        <p className="mt-2 text-[10px] text-act-300/90">
          筋肥大フェーズは刺激が命。今日は「{next.today_should_train.map((g) => g.label).join(" / ")}」に
          積極的に刺激を入れましょう。
        </p>
      )}
    </section>
  );
}
