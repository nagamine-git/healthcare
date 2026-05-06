import { useState } from "react";
import type { Advice, AdviceAction, GcalScheduleResult } from "../lib/api";

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
  other: "その他",
};

const CATEGORY_COLOR: Record<AdviceAction["category"], string> = {
  training: "bg-rose-900/40 text-rose-200 border-rose-800/60",
  cardio: "bg-amber-900/40 text-amber-200 border-amber-800/60",
  recovery: "bg-sky-900/40 text-sky-200 border-sky-800/60",
  mobility: "bg-violet-900/40 text-violet-200 border-violet-800/60",
  nutrition: "bg-emerald-900/40 text-emerald-200 border-emerald-800/60",
  rest: "bg-slate-800/60 text-slate-300 border-slate-700",
  other: "bg-slate-800/60 text-slate-300 border-slate-700",
};

export function AdviceCard({ advice, onRegenerate, onSchedule, gcalConfigured, pending }: Props) {
  const [scheduling, setScheduling] = useState(false);
  const [scheduleResult, setScheduleResult] = useState<GcalScheduleResult | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);

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
          {/* Focus */}
          {payload?.focus ? (
            <p className="text-base leading-relaxed text-slate-100">{payload.focus}</p>
          ) : (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">
              {advice.comment}
            </p>
          )}

          {/* Actions list */}
          {payload && payload.actions.length > 0 && (
            <ul className="mt-4 space-y-2">
              {payload.actions.map((a, i) => (
                <li
                  key={`${a.time_jst}-${i}`}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2"
                >
                  <span className="font-mono text-base tabular-nums text-emerald-300">
                    {a.time_jst}
                  </span>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${
                      CATEGORY_COLOR[a.category] ?? CATEGORY_COLOR.other
                    }`}
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
                </li>
              ))}
            </ul>
          )}

          {/* Rationale */}
          {payload?.rationale && (
            <p className="mt-3 text-xs leading-relaxed text-slate-500">
              <span className="text-slate-400">根拠</span>: {payload.rationale}
            </p>
          )}

          <p className="mt-3 text-[10px] text-slate-500">
            {advice.model} · {formatTs(advice.generated_at)}
          </p>

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
