import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Button, Panel } from "../components/ui/cockpit";

const WD = ["日", "月", "火", "水", "木", "金", "土"];

function fmtHeader(dateStr: string): string {
  // 26.06.27(土) 00:04
  const now = new Date();
  const base = dateStr ? new Date(dateStr + "T00:00:00") : now;
  const yy = String(base.getFullYear()).slice(2);
  const mm = String(base.getMonth() + 1).padStart(2, "0");
  const dd = String(base.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const mi = String(now.getMinutes()).padStart(2, "0");
  return `${yy}.${mm}.${dd}(${WD[base.getDay()]}) ${hh}:${mi}`;
}

function Heading({ children }: { children: string }) {
  return (
    <div className="mt-3 border-b border-hairline pb-1 text-xs font-semibold tracking-wider text-ink-dim">
      {children}
    </div>
  );
}

export function JournalPage({ onBack }: { onBack: () => void }) {
  const life = useQuery({ queryKey: ["life-tree"], queryFn: api.lifeTree });
  const today = useQuery({ queryKey: ["today"], queryFn: () => api.today(null), retry: false });
  const garden = useQuery({ queryKey: ["garden"], queryFn: api.garden, retry: false });
  const cal = useQuery({ queryKey: ["journal-cal"], queryFn: api.journalCalendar, retry: false });
  const move = useMutation({ mutationFn: () => api.becomingOneMove() });
  const [openEvent, setOpenEvent] = useState<string | null>(null);

  const dateStr = today.data?.date ?? "";
  const themeKeyword = garden.data?.weakest_hint?.name
    ?? life.data?.capitals.find((c) => c.key === life.data?.focus_capital)?.label
    ?? "—";
  const winning = move.data?.move ?? null;
  const condition = today.data?.score?.total ?? null;
  const alerts = (today.data?.alerts ?? []).filter((a) => a.severity !== "info");
  const breaches = (life.data?.capitals ?? []).filter((c) => c.breach).map((c) => c.label);

  // スケジュール: チェックイン(今)〜就寝まで。予定は時刻に配置。
  const nowHour = new Date().getHours();
  const bedRaw = today.data?.tonight_plan?.bedtime; // "HH:MM"
  let bedHour = bedRaw ? parseInt(bedRaw.slice(0, 2), 10) : 23;
  if (bedHour <= nowHour) bedHour += 24; // 日跨ぎ
  const hours: number[] = [];
  for (let h = nowHour; h <= bedHour; h++) hours.push(h);
  const eventsByHour = new Map<number, { summary: string; minute: number }[]>();
  for (const e of cal.data?.events ?? []) {
    const h = e.hour < nowHour ? e.hour + 24 : e.hour;
    (eventsByHour.get(h) ?? eventsByHour.set(h, []).get(h)!).push({ summary: e.summary, minute: e.minute });
  }

  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold text-ink">今日の紙</h1>
      <p className="text-xs text-ink-faint">手書きノートに写して使う。アプリは候補を出すだけ。</p>

      <Panel>
        <div className="font-mono text-sm leading-relaxed text-ink">
          <div className="text-base font-bold">{fmtHeader(dateStr)}</div>

          <Heading>感謝・話したこと・今日のテーマ</Heading>
          <div className="mt-1 space-y-0.5 text-ink-faint">
            <div>感謝する人: <span className="text-ink-faint/40">________</span></div>
            <div>話した人: <span className="text-ink-faint/40">________</span></div>
            <div className="text-ink">
              ・<span className="text-prog-300">{themeKeyword}</span>:{" "}
              {winning ? (
                <span className="text-act-300">{winning}</span>
              ) : (
                <span className="text-ink-faint/60">(下で候補を出す)</span>
              )}
            </div>
          </div>

          <div className="mt-1 flex items-center justify-between">
            <Heading>勝ちタスク候補</Heading>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span className="flex-1 text-act-300">
              {winning ?? "(今日いちばん効く一手を提案します)"}
            </span>
            <Button variant="subtle" disabled={move.isPending} onClick={() => move.mutate()}>
              {move.isPending ? "生成中…" : winning ? "別案" : "出す"}
            </Button>
          </div>

          <Heading>スケジュール(チェックイン〜就寝 / ○=予定)</Heading>
          <div className="mt-1 space-y-0.5">
            {hours.map((h) => {
              const evs = eventsByHour.get(h) ?? [];
              const disp = h % 24;
              return (
                <div key={h} className="flex gap-2">
                  <span className="w-6 shrink-0 tabular-nums text-ink-faint">{disp}</span>
                  {evs.length > 0 ? (
                    <span className="flex-1">
                      {evs.map((ev, i) => (
                        <button
                          key={i}
                          onClick={() => setOpenEvent(ev.summary)}
                          className="mr-2 max-w-full truncate text-left text-prog-300"
                          title={ev.summary}
                        >
                          ○ {ev.summary}
                        </button>
                      ))}
                    </span>
                  ) : (
                    <span className="text-ink-faint/40">—</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </Panel>

      {openEvent && (
        <div className="rounded-lg border border-prog-700 bg-hull p-3 text-sm text-ink">
          {openEvent}
          <button onClick={() => setOpenEvent(null)} className="ml-2 text-xs text-ink-faint">
            閉じる
          </button>
        </div>
      )}

      {(breaches.length > 0 || alerts.length > 0 || condition !== null) && (
        <Panel title="今日 意識する線(アプリからの読み出し)">
          {condition !== null && (
            <p className="text-sm text-ink-dim">
              コンディション <span className="telemetry-num text-prog-300">{Math.round(condition)}</span>
              {condition < 50 && <span className="ml-1 text-act-300">— 負荷を下げる</span>}
            </p>
          )}
          {alerts.map((a) => (
            <p key={a.code} className="mt-1 text-sm text-risk">⚠ {a.title} — {a.action}</p>
          ))}
          {breaches.length > 0 && (
            <p className="mt-1 text-sm text-act-300">立て直す領域: {breaches.join(" / ")}</p>
          )}
        </Panel>
      )}
    </div>
  );
}
