import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type MentalResult, type MentalStatus } from "../lib/api";

/** PHQ-2 + GAD-2 の超短縮メンタルスクリーニング。不調サイン時/定期に促し、結果を保存。
 *  医療機器ではない — 陽性=受診検討の目安、という保守的枠組みで表示する。 */
const SEVERITY_TONE: Record<MentalResult["severity"], string> = {
  none: "text-prog-300",
  mild: "text-prog-300",
  moderate: "text-act-300",
  severe: "text-risk",
};

function ResultSummary({ r }: { r: MentalResult }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline gap-2">
        <span className={`text-lg font-semibold ${SEVERITY_TONE[r.severity]}`}>{r.severity_label}</span>
        <span className="telemetry-num text-xs text-ink-faint">PHQ-4 {r.phq4}/12</span>
        <span className="ml-auto text-[10px] text-ink-faint">{r.date}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <span className="rounded-full bg-panel px-2 py-0.5 text-[11px] text-ink-dim">
          うつ PHQ-2 {r.phq2}/6
        </span>
        <span className="rounded-full bg-panel px-2 py-0.5 text-[11px] text-ink-dim">
          不安 GAD-2 {r.gad2}/6
        </span>
        {r.depression_positive && (
          <span className="rounded-full bg-act/20 px-2 py-0.5 text-[11px] text-act-300">抑うつ傾向</span>
        )}
        {r.anxiety_positive && (
          <span className="rounded-full bg-act/20 px-2 py-0.5 text-[11px] text-act-300">不安傾向</span>
        )}
      </div>
    </div>
  );
}

function Questionnaire({ data, onDone }: { data: MentalStatus; onDone: () => void }) {
  const qc = useQueryClient();
  const [ans, setAns] = useState<Record<string, number>>({});
  const submit = useMutation({
    mutationFn: () =>
      api.mentalScreen({
        phq2_1: ans.phq2_1, phq2_2: ans.phq2_2, gad2_1: ans.gad2_1, gad2_2: ans.gad2_2,
      }),
    onSuccess: (d) => {
      qc.setQueryData(["mental"], d);
      qc.invalidateQueries({ queryKey: ["next-action"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["life-tree"] });
      onDone();
    },
  });
  const complete = data.items.every((it) => ans[it.id] != null);

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-ink-faint">過去2週間、以下にどのくらいの頻度で悩まされましたか。</p>
      {data.items.map((it) => (
        <div key={it.id} className="space-y-1.5">
          <p className="text-sm text-ink">{it.text}</p>
          <div className="grid grid-cols-4 gap-1.5">
            {data.scale.map((o) => {
              const active = ans[it.id] === o.value;
              return (
                <button
                  key={o.value}
                  onClick={() => setAns((a) => ({ ...a, [it.id]: o.value }))}
                  className={`rounded-lg px-1 py-2 text-[11px] leading-tight transition-colors ${
                    active ? "bg-prog-700 text-ink" : "bg-panel text-ink-dim hover:text-ink"
                  }`}
                >
                  <span className="block telemetry-num text-xs">{o.value}</span>
                  {o.label}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      <button
        onClick={() => submit.mutate()}
        disabled={!complete || submit.isPending}
        className="w-full rounded-lg bg-prog-700 px-4 py-2 text-sm hover:bg-prog-500 disabled:opacity-50"
      >
        {submit.isPending ? "記録中…" : "記録する"}
      </button>
    </div>
  );
}

export function MentalCheckCard() {
  const q = useQuery({ queryKey: ["mental"], queryFn: api.mental, retry: false });
  const [open, setOpen] = useState(false);
  if (!q.data) return null;
  const d = q.data;
  const elevated = d.urgency === "elevated";

  return (
    <section
      className={`space-y-3 rounded-xl p-4 ${
        elevated ? "bg-hull ring-1 ring-act/40" : "bg-hull"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm tracking-wide text-ink-dim">心の健康チェック</h2>
        <span className="text-[10px] text-ink-faint">PHQ-2 + GAD-2</span>
      </div>

      {d.due && !open && (
        <p className={`text-xs ${elevated ? "text-act-300" : "text-ink-faint"}`}>
          {d.reason}
        </p>
      )}

      {!open ? (
        <>
          {d.latest && <ResultSummary r={d.latest} />}
          <button
            onClick={() => setOpen(true)}
            className={`w-full rounded-lg px-4 py-2 text-sm ${
              d.due ? "bg-prog-700 text-ink hover:bg-prog-500" : "border border-hairline text-ink-dim hover:text-ink"
            }`}
          >
            {d.latest ? "もう一度チェックする (2分)" : "チェックする (2分・4問)"}
          </button>
        </>
      ) : (
        <Questionnaire data={d} onDone={() => setOpen(false)} />
      )}

      <p className="text-[10px] leading-relaxed text-ink-faint">
        検証済みの一次スクリーニングであり、診断ではありません。つらさが2週間以上続く場合は
        産業医・かかりつけ医・相談窓口など専門家への相談を検討してください。
      </p>
    </section>
  );
}
