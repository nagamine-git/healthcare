import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";

type Props = {
  onBack: () => void;
};

export function DebugPage({ onBack }: Props) {
  const [days, setDays] = useState(14);
  const q = useQuery({
    queryKey: ["debug", days],
    queryFn: () => api.debugSources(days),
  });

  return (
    <main className="safe-area-x pb-nav mx-auto max-w-5xl space-y-4">
      <header className="safe-area-top flex items-center justify-between pb-2">
        <button
          onClick={onBack}
          className="rounded-full border border-hairline px-3 py-1 text-xs text-ink-dim hover:bg-panel"
        >
          ← ダッシュボードに戻る
        </button>
        <div className="flex items-center gap-2 text-xs text-ink-faint">
          <label htmlFor="days">直近</label>
          <select
            id="days"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded border border-hairline bg-hull px-2 py-1"
          >
            <option value={3}>3 日</option>
            <option value={7}>7 日</option>
            <option value={14}>14 日</option>
            <option value={30}>30 日</option>
            <option value={60}>60 日</option>
          </select>
        </div>
      </header>

      <h2 className="text-base text-ink">Debug — ソース別ローデータ</h2>

      <PerfPanel />

      {q.isLoading && <p className="text-ink-dim">読み込み中...</p>}
      {q.isError && <p className="text-risk">取得失敗</p>}

      {q.data && (
        <>
          <Section title="同期ステータス">
            <Pre obj={q.data.sync} />
          </Section>

          <Section title={`Workouts (${q.data.workouts.length})`}>
            <Table rows={q.data.workouts} />
          </Section>

          <Section title={`Sleep sessions (${q.data.sleep.length})`}>
            <Table rows={q.data.sleep} />
          </Section>

          <Section title={`HRV daily (${q.data.hrv.length})`}>
            <Table rows={q.data.hrv} />
          </Section>

          <Section title={`Body Battery daily (${q.data.body_battery_daily.length})`}>
            <Table rows={q.data.body_battery_daily} />
          </Section>

          <Section title={`Body Battery samples (latest 100, shown ${q.data.body_battery_samples.length})`} collapsed>
            <Table rows={q.data.body_battery_samples} />
          </Section>

          <Section title={`Daily summary (${q.data.daily_summary.length})`}>
            <Table rows={q.data.daily_summary} />
          </Section>

          <Section title={`Weight (${q.data.weights.length})`}>
            <Table rows={q.data.weights} />
          </Section>

          <Section title={`Daily score (${q.data.daily_score.length})`}>
            <Table rows={q.data.daily_score} />
          </Section>

          <Section title={`Metric samples summary (${q.data.metric_summary.length} keys)`}>
            <Table rows={q.data.metric_summary} />
          </Section>

          <Section title={`Metric samples recent (${q.data.metric_recent.length})`} collapsed>
            <Table rows={q.data.metric_recent} />
          </Section>

          <Section title={`LLM comments (${q.data.llm_comments.length})`} collapsed>
            <Pre obj={q.data.llm_comments} />
          </Section>
        </>
      )}
    </main>
  );
}

function Section({
  title,
  children,
  collapsed,
}: {
  title: string;
  children: React.ReactNode;
  collapsed?: boolean;
}) {
  const [open, setOpen] = useState(!collapsed);
  return (
    <section className="rounded-xl bg-hull/70 p-3 sm:p-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-left text-sm text-ink"
      >
        <span>{title}</span>
        <span className="text-xs text-ink-faint">{open ? "−" : "+"}</span>
      </button>
      {open && <div className="mt-2 overflow-x-auto">{children}</div>}
    </section>
  );
}

function Table({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows || rows.length === 0) {
    return <p className="text-xs text-ink-faint">— データなし</p>;
  }
  const keys = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
  return (
    <table className="w-full text-left text-[11px]">
      <thead className="border-b border-panel text-ink-dim">
        <tr>
          {keys.map((k) => (
            <th key={k} className="px-2 py-1 font-normal">
              {k}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="text-ink-dim">
        {rows.map((r, i) => (
          <tr key={i} className="border-b border-hull/60">
            {keys.map((k) => (
              <td key={k} className="px-2 py-1 align-top tabular-nums">
                {formatCell(r[k])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Pre({ obj }: { obj: unknown }) {
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap break-all text-[11px] text-ink-dim">
      {JSON.stringify(obj, null, 2)}
    </pre>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}


function PerfPanel() {
  const q = useQuery({ queryKey: ["admin-perf"], queryFn: api.adminPerf, retry: false, refetchInterval: 30000 });
  if (!q.data) return null;
  const { live, issues } = q.data;
  const KIND: Record<string, string> = { error: "エラー", slow_request: "遅い応答", slow_query: "遅いクエリ" };
  const unresolved = issues.filter((i) => !i.resolved);
  return (
    <section className="rounded-xl bg-hull/70 p-3 sm:p-4">
      <h3 className="mb-2 text-sm text-ink">
        パフォーマンス監視{" "}
        <span className="text-xs text-ink-faint">
          (遅延 &gt;{live.thresholds.slow_request_ms}ms / クエリ &gt;{live.thresholds.slow_query_ms}ms を記録 → PRで修正)
        </span>
      </h3>
      {unresolved.length === 0 ? (
        <p className="text-xs text-prog-300">未対応の問題はありません</p>
      ) : (
        <div className="space-y-1">
          {unresolved.slice(0, 30).map((i) => (
            <div key={i.id} className="flex items-center gap-2 text-[11px]">
              <span className={`rounded px-1.5 ${i.kind === "error" ? "bg-risk/20 text-risk" : "bg-act/15 text-act-300"}`}>
                {KIND[i.kind] ?? i.kind}
              </span>
              <span className="min-w-0 flex-1 truncate font-mono text-ink-dim" title={i.detail ?? i.label}>{i.label}</span>
              <span className="telemetry-num text-ink-faint">×{i.count}</span>
              <span className="telemetry-num text-ink-faint">{Math.round(i.max_duration_ms)}ms</span>
            </div>
          ))}
        </div>
      )}
      {live.endpoints.length > 0 && (
        <div className="mt-2 border-t border-hairline pt-2">
          <p className="text-[10px] text-ink-faint">エンドポイント(p95降順)</p>
          {live.endpoints.slice(0, 8).map((e) => (
            <div key={e.label} className="flex items-center gap-2 text-[11px]">
              <span className="min-w-0 flex-1 truncate font-mono text-ink-dim">{e.label}</span>
              <span className="telemetry-num text-ink-faint">{e.count}回</span>
              <span className="telemetry-num text-ink-dim">p95 {e.p95_ms}ms</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
