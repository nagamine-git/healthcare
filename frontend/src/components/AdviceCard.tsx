import { useState } from "react";
import type { Advice, AdviceAction, AdvicePriority, GcalScheduleResult } from "../lib/api";

type Props = {
  advice: Advice | null;
  onRegenerate: () => void;
  onSchedule?: () => Promise<GcalScheduleResult>;
  gcalConfigured?: boolean;
  pending?: boolean;
};

const CATEGORY_LABEL: Record<AdviceAction["category"], string> = {
  training: "筋トレ",
  cardio: "有酸素",
  recovery: "回復",
  mobility: "モビリティ",
  nutrition: "食事/水分",
  rest: "休息",
  focus: "集中力",
  other: "その他",
};

// カテゴリは slate 単色で統一 (情報過多を避ける)
const CATEGORY_BADGE = "border border-slate-700 bg-slate-800/40 text-slate-300";

const PRIORITY_LABEL: Record<AdvicePriority, string> = {
  critical: "今すぐ",
  high: "本日中",
  mid: "推奨",
  low: "任意",
};

// 優先度は意味があるので 4 段階維持、しかし強度はおさえる
const PRIORITY_COLOR: Record<AdvicePriority, string> = {
  critical: "border border-rose-500/70 bg-rose-500/10 text-rose-300",
  high: "border border-amber-500/60 bg-amber-500/10 text-amber-300",
  mid: "border border-slate-600 bg-transparent text-slate-400",
  low: "border border-slate-700 bg-transparent text-slate-500",
};

const PRIORITY_RANK: Record<AdvicePriority, number> = {
  critical: 0,
  high: 1,
  mid: 2,
  low: 3,
};

export function AdviceCard({ advice, onRegenerate, onSchedule, gcalConfigured, pending }: Props) {
  const [scheduling, setScheduling] = useState(false);
  const [scheduleResult, setScheduleResult] = useState<GcalScheduleResult | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const handleSchedule = async () => {
    if (!onSchedule) return;
    setScheduling(true);
    setScheduleError(null);
    try {
      const r = await onSchedule();
      setScheduleResult(r);
    } catch (e) {
      setScheduleError((e as Error).message);
    } finally {
      setScheduling(false);
    }
  };

  const payload = advice?.payload ?? null;

  return (
    <div className="rounded-2xl bg-gradient-to-br from-slate-900/80 to-slate-800/60 p-5 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-slate-300">今日のフォーカス</h3>
        <div className="flex gap-2">
          <button
            onClick={onRegenerate}
            disabled={pending}
            className="rounded-full border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            {pending ? "生成中..." : "再生成"}
          </button>
          {gcalConfigured && payload && payload.actions.length > 0 && (
            <button
              onClick={handleSchedule}
              disabled={scheduling}
              className="rounded-full border border-emerald-700 bg-emerald-900/30 px-3 py-1 text-xs text-emerald-300 hover:bg-emerald-900/60 disabled:opacity-50"
            >
              {scheduling ? "登録中..." : "Calendar に追加"}
            </button>
          )}
        </div>
      </div>

      {!advice ? (
        <p className="text-slate-500">
          まだアドバイスは生成されていません。「再生成」を押すか、朝のジョブを待ってください。
        </p>
      ) : (
        <>
          {/* Headline (1行パンチライン、大きく) */}
          {payload?.headline && (
            <p className="mb-2 text-xl font-semibold leading-snug text-slate-50 sm:text-2xl">
              {payload.headline}
            </p>
          )}

          {/* Actions list — priority 順、最初 1 件は常に展開、残りは折りたたみ */}
          {payload && payload.actions.length === 0 && (
            <p className="mt-2 text-xs text-slate-400">
              本日推奨アクションなし。コンディション維持で OK。
            </p>
          )}
          {payload && payload.actions.length > 0 && (
            <ul className="mt-3 space-y-2">
              {(() => {
                const sorted = [...payload.actions].sort(
                  (a, b) =>
                    (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9) ||
                    a.time_jst.localeCompare(b.time_jst),
                );
                const visible = expanded ? sorted : sorted.slice(0, 1);
                return visible;
              })().map((a, i) => (
                  <li
                    key={`${a.time_jst}-${i}`}
                    className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2"
                  >
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[10px] tracking-wider ${
                        PRIORITY_COLOR[a.priority] ?? PRIORITY_COLOR.mid
                      }`}
                    >
                      {PRIORITY_LABEL[a.priority] ?? a.priority}
                    </span>
                    <span className="font-mono text-base tabular-nums text-slate-200">
                      {a.time_jst}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] tracking-wider ${CATEGORY_BADGE}`}
                    >
                      {CATEGORY_LABEL[a.category] ?? a.category}
                    </span>
                    <span className="text-slate-100">{a.title}</span>
                    <span className="text-xs text-slate-500">{a.duration_min} 分</span>
                    {a.intensity && (
                      <span className="text-xs text-slate-400">· {a.intensity}</span>
                    )}
                    {a.why && (
                      <span className="basis-full text-xs text-slate-500">{a.why}</span>
                    )}
                    {a.exercises && a.exercises.length > 0 && (
                      <ExerciseList exercises={a.exercises} />
                    )}
                  </li>
                ))}
            </ul>
          )}

          {/* 展開トグル */}
          {payload && (payload.actions.length > 1 || payload.focus || payload.rationale) && (
            <button
              onClick={() => setExpanded((e) => !e)}
              className="mt-3 text-xs text-slate-500 hover:text-slate-300"
            >
              {expanded
                ? "▴ 折りたたむ"
                : `▾ あと ${Math.max(0, payload.actions.length - 1)} 件 + 詳細を表示`}
            </button>
          )}

          {/* Focus と Rationale は展開時のみ */}
          {expanded && payload?.focus && (
            <p className="mt-3 text-sm leading-relaxed text-slate-300">
              {payload.focus}
            </p>
          )}
          {expanded && payload?.rationale && (
            <p className="mt-2 text-xs leading-relaxed text-slate-500">
              <span className="text-slate-400">根拠</span>: {payload.rationale}
            </p>
          )}

          {expanded && (
            <p className="mt-3 text-[10px] text-slate-500">
              {advice.model} · {formatTs(advice.generated_at)}
            </p>
          )}

          {scheduleResult && (
            <div className="mt-3 rounded-lg bg-emerald-900/20 p-3 text-xs text-emerald-200">
              {scheduleResult.created.length === 0
                ? "登録対象のアクションは未来時刻にありませんでした"
                : `${scheduleResult.created.length} 件のイベントをカレンダーに登録しました`}
              {scheduleResult.created.map((ev) => (
                <div key={ev.id} className="mt-1">
                  <a
                    href={ev.htmlLink}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline hover:text-emerald-100"
                  >
                    {ev.summary}
                  </a>{" "}
                  ·{" "}
                  {new Date(ev.start).toLocaleTimeString(undefined, {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              ))}
            </div>
          )}
          {scheduleError && (
            <div className="mt-3 rounded-lg bg-rose-900/30 p-2 text-xs text-rose-200">
              Calendar 登録失敗: {scheduleError}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ExerciseList({ exercises }: { exercises: NonNullable<AdviceAction["exercises"]> }) {
  return (
    <div className="basis-full mt-2 space-y-2">
      <ul className="space-y-1.5">
        {exercises.map((e, i) => (
          <li
            key={i}
            className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2"
          >
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
              <span className="text-sm text-slate-100">{e.name}</span>
              {e.weight && (
                <span className="font-mono text-sm tabular-nums text-emerald-300">
                  {e.weight}
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[11px] tabular-nums text-slate-400">
              <span>
                <span className="text-slate-500">セット </span>
                {e.sets}
              </span>
              <span>
                <span className="text-slate-500">回数 </span>
                {e.reps}
              </span>
              {e.rest_sec != null && (
                <span>
                  <span className="text-slate-500">休憩 </span>
                  {e.rest_sec}秒
                </span>
              )}
              {e.rir != null && (
                <span>
                  <span className="text-slate-500">RIR </span>
                  {e.rir}
                </span>
              )}
              {e.tempo && (
                <span>
                  <span className="text-slate-500">テンポ </span>
                  {e.tempo}
                </span>
              )}
            </div>
            {e.notes && (
              <div className="mt-1 text-[11px] leading-relaxed text-slate-500">
                {e.notes}
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="text-[10px] leading-relaxed text-slate-500">
        <span className="text-slate-400">RIR</span> = 限界まで何回余力を残すか (低いほど追い込む)。
        筋肥大は 1-3、筋力は 1-2、技術習得は 3-5 が目安。
        <br />
        <span className="text-slate-400">RPE</span> = 10 段階の主観強度 (Rate of Perceived Exertion)。
        6-7 = ややきつい、8-9 = かなりきつい、10 = 限界。
      </p>
    </div>
  );
}

function formatTs(ts: string | null): string {
  if (!ts) return "--";
  return new Date(ts).toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
