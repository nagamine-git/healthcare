import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CaffeineSource, type MedStatus } from "../lib/api";

const DOSE = 2; // 1回2錠(バファリン/イブとも)
const MED_SOURCES = new Set<string>(["bufferin_premium", "ibuquick"]);
const MED_LABEL: Record<string, string> = { bufferin_premium: "バファリン", ibuquick: "イブ" };

/** 鎮痛薬のワンタップ記録 + 服用間隔ガード(4時間以上・1日3回まで)。
 * 早すぎる/上限到達時は記録をブロックし、次に飲める時刻を出す。MOHリスクの判断材料にも。 */
export function MedQuickLog() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["med-status"], queryFn: api.caffeineMedStatus });
  const intakes = useQuery({
    queryKey: ["med-intakes"],
    queryFn: () => api.caffeineList(72),
  });
  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["med-status"] });
    qc.invalidateQueries({ queryKey: ["med-intakes"] });
    qc.invalidateQueries({ queryKey: ["today"] });
    qc.invalidateQueries({ queryKey: ["migraine"] });
    qc.invalidateQueries({ queryKey: ["caffeine"] });
  };
  const log = useMutation({
    mutationFn: (source: CaffeineSource) => api.caffeineAdd(source, DOSE),
    onSuccess: invalidateAll,
  });
  const del = useMutation({
    mutationFn: (id: number) => api.caffeineDelete(id),
    onSuccess: invalidateAll,
  });

  const meds = status.data?.meds ?? [];
  const medRecords = (intakes.data?.items ?? []).filter((r) => MED_SOURCES.has(r.source));

  return (
    <div className="rounded-xl border border-hairline/60 bg-hull/40 p-3">
      <p className="mb-2 text-[11px] uppercase tracking-wider text-ink-dim">
        鎮痛薬を記録(4時間以上あけて・1日3回まで)
      </p>
      <div className="space-y-2">
        {meds.map((m) => (
          <MedRow
            key={m.source}
            m={m}
            pending={log.isPending}
            onLog={() => {
              if (!m.can_take) {
                // 早すぎ/上限: 二重チェック(本当に飲む?)してから記録
                if (!window.confirm(`${m.reason}\nそれでも記録しますか?`)) return;
              }
              log.mutate(m.source);
            }}
          />
        ))}
      </div>
      <p className="mt-1.5 text-[10px] text-ink-faint">
        記録は体内カフェイン/薬の使用日数に反映(飲みすぎ＝MOHリスクの警告に効く)。
      </p>

      {medRecords.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-hairline/60 pt-2">
          <p className="text-[10px] uppercase tracking-wider text-ink-faint">最近の記録(3日)</p>
          {medRecords.map((r) => (
            <div key={r.id} className="flex items-center justify-between text-[11px]">
              <span className="text-ink-dim">
                <span className="tabular-nums text-ink-dim">{fmtDT(r.ts_jst)}</span>{" "}
                {MED_LABEL[r.source] ?? r.source}({r.amount}錠)
              </span>
              <button
                disabled={del.isPending}
                onClick={() => {
                  if (window.confirm(`${fmtDT(r.ts_jst)} の ${MED_LABEL[r.source] ?? r.source} を削除しますか?`))
                    del.mutate(r.id);
                }}
                className="text-ink-faint hover:text-risk disabled:opacity-50"
              >
                削除
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MedRow({ m, pending, onLog }: { m: MedStatus; pending: boolean; onLog: () => void }) {
  const blocked = !m.can_take;
  return (
    <div className="flex items-center gap-3">
      <button
        disabled={pending}
        onClick={onLog}
        className={`shrink-0 rounded-full border px-3 py-1 text-sm transition-colors disabled:opacity-50 ${
          blocked
            ? "border-risk/60/60 bg-risk/20 text-risk hover:bg-risk/40"
            : "border-act-700/60 bg-act-700/20 text-act-300 hover:bg-act-700/40"
        }`}
      >
        {blocked ? "⚠ " : "+ "}
        {m.label}({DOSE}錠)
      </button>
      <div className="min-w-0 flex-1 text-[11px] leading-tight">
        <p className={blocked ? "text-risk" : "text-ink-dim"}>{m.reason}</p>
        <p className="text-ink-faint">
          本日 {m.doses_today}/{m.max_per_day} 回
          {m.last_taken_iso && ` ・ 前回 ${fmt(m.last_taken_iso)}`}
        </p>
      </div>
    </div>
  );
}

function fmt(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function fmtDT(iso: string): string {
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${mm}/${dd} ${fmt(iso)}`;
}
