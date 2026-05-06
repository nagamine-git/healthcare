import { useState } from "react";
import type { Advice, GcalScheduleResult } from "../lib/api";

type Props = {
  advice: Advice | null;
  onRegenerate: () => void;
  onSchedule?: () => Promise<GcalScheduleResult>;
  gcalConfigured?: boolean;
  pending?: boolean;
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

  return (
    <div className="rounded-2xl bg-gradient-to-br from-slate-900/80 to-slate-800/60 p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm tracking-wider text-slate-300">
          今日のフォーカス
        </h3>
        <div className="flex gap-2">
          <button
            onClick={onRegenerate}
            disabled={pending}
            className="rounded-full border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            {pending ? "生成中..." : "再生成"}
          </button>
          {gcalConfigured && advice && (
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
      {advice ? (
        <>
          <p className="whitespace-pre-wrap text-base leading-relaxed text-slate-100">
            {advice.comment}
          </p>
          <p className="mt-3 text-xs text-slate-500">
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
                  · {new Date(ev.start).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
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
      ) : (
        <p className="text-slate-500">
          まだアドバイスは生成されていません。「再生成」を押すか、朝のジョブを待ってください。
        </p>
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
