import { useQuery } from "@tanstack/react-query";
import { Activity, Footprints, Home, HelpCircle, Sun } from "lucide-react";
import { api, type ActivityDay } from "../lib/api";

/**
 * 活動/外出シグナル。Garmin / iPhone を相互補完して日次の「動いた・外に出た」を推測。
 * どのソースも無い日は「不明」(灰) で明示し、活動ゼロとは区別する。
 * 設計: docs/superpowers/specs/2026-06-23-activity-signal-multisource-design.md
 */
export function ActivitySignalCard() {
  const q = useQuery({ queryKey: ["activity-signal"], queryFn: () => api.activitySignal(14) });
  const data = q.data;
  if (!data) return null;

  return (
    <section className="space-y-3 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 p-4 sm:p-5 ring-1 ring-slate-800">
      <div className="flex items-center gap-2">
        <Activity size={16} className="text-sky-300" />
        <h3 className="text-sm tracking-wide text-slate-100">活動・外出 (推測)</h3>
      </div>
      <p className="text-[11px] leading-relaxed text-slate-500">
        Garmin と iPhone を相互補完して「動いたか・外に出たか」を推測。どちらのデータも無い日は
        <span className="text-slate-400"> 不明</span> (活動ゼロとは区別)。
      </p>
      <ul className="space-y-1">
        {data.days.map((d) => (
          <DayRow key={d.date} d={d} />
        ))}
      </ul>
    </section>
  );
}

const CONF_LABEL: Record<string, { text: string; cls: string }> = {
  high: { text: "高", cls: "bg-emerald-500/15 text-emerald-300 ring-emerald-600/30" },
  medium: { text: "中", cls: "bg-sky-500/15 text-sky-300 ring-sky-600/30" },
  low: { text: "低", cls: "bg-slate-500/15 text-slate-400 ring-slate-600/30" },
  none: { text: "不明", cls: "bg-slate-700/30 text-slate-500 ring-slate-700/40" },
};

function DayRow({ d }: { d: ActivityDay }) {
  const unknown = d.moved == null;
  const conf = CONF_LABEL[d.confidence] ?? CONF_LABEL.none;
  const md = d.date.slice(5); // MM-DD

  return (
    <li className="flex items-center gap-2 rounded-lg bg-slate-950/40 px-3 py-1.5 text-[12px] ring-1 ring-slate-800/50">
      <span className="w-12 shrink-0 tabular-nums text-slate-500">{md}</span>
      {unknown ? (
        <span className="flex flex-1 items-center gap-1.5 text-slate-500">
          <HelpCircle size={14} /> 不明 (記録なし)
        </span>
      ) : (
        <>
          <span
            className={`flex items-center gap-1 ${d.moved ? "text-emerald-300" : "text-slate-600"}`}
            title="動いたか"
          >
            <Footprints size={14} />
            {d.steps != null ? <span className="tabular-nums">{d.steps.toLocaleString()}</span> : "—"}
          </span>
          <span
            className={`ml-1 flex items-center gap-1 ${
              d.went_outside ? "text-amber-300" : "text-slate-600"
            }`}
            title="外に出たか"
          >
            {d.went_outside ? <Sun size={14} /> : <Home size={14} />}
            {d.went_outside ? "外出" : "屋内?"}
          </span>
          {d.distance_m != null && d.distance_m > 0 && (
            <span className="text-[10px] tabular-nums text-slate-500">
              {(d.distance_m / 1000).toFixed(1)}km
            </span>
          )}
        </>
      )}
      <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] ring-1 ${conf.cls}`}>
        {conf.text}
      </span>
    </li>
  );
}
