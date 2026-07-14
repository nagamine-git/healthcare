import { useQuery } from "@tanstack/react-query";
import { api, type ScheduleEvent } from "../lib/api";

/** ISO 文字列 (…T09:00:00+09:00) から壁時計 HH:MM を取り出す (オフセット込みの時刻をそのまま表示)。 */
function hhmm(iso: string | null): string {
  return iso && iso.length >= 16 ? iso.slice(11, 16) : "";
}

function EventRow({ ev }: { ev: ScheduleEvent }) {
  return (
    <li className="flex items-baseline gap-2 py-1">
      <span className="telemetry-num w-24 shrink-0 text-xs text-ink-dim">
        {hhmm(ev.start)}<span className="text-ink-faint">–{hhmm(ev.end)}</span>
      </span>
      <span className="min-w-0 flex-1 truncate text-sm text-ink">
        {ev.title}
        {ev.is_hc_managed && <span className="ml-1 text-[10px] text-prog-300">(提案)</span>}
      </span>
      {!ev.is_busy && <span className="text-[10px] text-ink-faint">空き</span>}
    </li>
  );
}

/** 今日の予定 (Google Calendar 読み取り)。「今日」サーフェスの固定枠として、
 *  いまコレ/アラートと並べて "これから何が入っているか" を示す。未連携時は非表示。 */
export function ScheduleCard() {
  const q = useQuery({ queryKey: ["schedule-today"], queryFn: api.scheduleToday, retry: false });
  const d = q.data;
  // 未連携ならクラッタを避けて何も出さない (連携は設定側の導線)。
  if (!d || !d.configured) return null;
  const upcoming = d.events.filter((e) => !e.past);

  return (
    <section className="space-y-2 rounded-xl bg-hull p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm tracking-wide text-ink-dim">今日の予定</h2>
        <span className="text-[10px] text-ink-faint">これから {upcoming.length} 件</span>
      </div>
      {upcoming.length === 0 ? (
        <p className="text-xs text-ink-faint">これからの予定はありません。</p>
      ) : (
        <ul className="divide-y divide-hairline">
          {upcoming.map((ev, i) => (
            <EventRow key={ev.id ?? i} ev={ev} />
          ))}
        </ul>
      )}
    </section>
  );
}
