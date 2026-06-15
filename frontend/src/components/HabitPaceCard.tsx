import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { api } from "../lib/api";
import type { HabitPaceItem } from "../lib/api";

/**
 * 今のペース。「いつもの今頃」(個人履歴の同時刻中央値) と今日の実績を比べ、
 * 遅れている push 系 (水分/歩数/活動) は具体的に促す。
 * 例: いつもは今頃 800ml、まだ 0ml → 1杯飲もう！
 */

const STATUS: Record<string, { cls: string; bar: string; text: string }> = {
  behind: { cls: "text-amber-300", bar: "#fbbf24", text: "遅れ" },
  on_pace: { cls: "text-emerald-300", bar: "#34d399", text: "順調" },
  ahead: { cls: "text-sky-300", bar: "#38bdf8", text: "前倒し" },
  high: { cls: "text-rose-300", bar: "#fb7185", text: "いつもより多い" },
  low: { cls: "text-slate-400", bar: "#94a3b8", text: "いつもより少ない" },
  normal: { cls: "text-slate-400", bar: "#64748b", text: "いつも通り" },
  no_data: { cls: "text-slate-600", bar: "#475569", text: "履歴待ち" },
};

function PaceRow({ h }: { h: HabitPaceItem }) {
  const st = STATUS[h.status] ?? STATUS.no_data;
  const pct = h.expected && h.expected > 0 ? Math.min(140, (h.actual / h.expected) * 100) : 0;
  return (
    <div className="rounded-md px-2 py-1.5">
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="shrink-0">{h.emoji}</span>
        <span className="shrink-0 text-slate-200">{h.label}</span>
        <span className="min-w-0 flex-1 truncate text-[10px] text-slate-500">
          {h.expected != null ? `いつも今頃 ${h.expected}${h.unit} / 今 ${h.actual}${h.unit}` : "履歴待ち"}
        </span>
        <span className={`shrink-0 text-[10px] ${st.cls}`}>{st.text}</span>
      </div>
      {h.expected != null && (
        <div className="relative mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
          {/* いつものペース (100%) の目盛り */}
          <div className="absolute top-0 z-10 h-full w-px bg-slate-400/60" style={{ left: "71%" }} />
          <div className="h-full rounded-full transition-all" style={{ width: `${Math.max(pct, 2)}%`, background: st.bar }} />
        </div>
      )}
    </div>
  );
}

export function HabitPaceCard() {
  const q = useQuery({ queryKey: ["habit-pace"], queryFn: api.habitPace, refetchInterval: 10 * 60_000 });
  if (q.isLoading || !q.data) return null;
  const s = q.data;
  const shown = s.habits.filter((h) => h.status !== "no_data");
  if (shown.length === 0) return null;

  return (
    <section className="space-y-2 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center gap-1.5">
        <Gauge size={14} className="text-sky-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">今のペース</span>
        <span className="ml-auto text-[10px] text-slate-600">いつもの今頃 vs 今日</span>
      </div>

      {/* 遅れナッジ (あれば強調) */}
      {s.nudges.length > 0 && (
        <div className="space-y-1">
          {s.nudges.map((n, i) => (
            <div key={i} className="rounded-lg bg-amber-500/10 px-2.5 py-1.5 text-[12px] text-amber-100">{n}</div>
          ))}
        </div>
      )}

      <div className="grid gap-0.5">
        {shown.map((h) => <PaceRow key={h.key} h={h} />)}
      </div>
      <p className="text-[9px] text-slate-500">｜が「いつものペース(同時刻の中央値)」。バーが届いていなければ遅れ。</p>
    </section>
  );
}
