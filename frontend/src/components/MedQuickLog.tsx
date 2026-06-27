import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CaffeineSource, type MedStatus } from "../lib/api";

const DOSE = 2; // 1回2錠(バファリン/イブとも)

/** 鎮痛薬のワンタップ記録 + 服用間隔ガード(4時間以上・1日3回まで)。
 * 早すぎる/上限到達時は記録をブロックし、次に飲める時刻を出す。MOHリスクの判断材料にも。 */
export function MedQuickLog() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["med-status"], queryFn: api.caffeineMedStatus });
  const log = useMutation({
    mutationFn: (source: CaffeineSource) => api.caffeineAdd(source, DOSE),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["med-status"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["migraine"] });
      qc.invalidateQueries({ queryKey: ["caffeine"] });
    },
  });

  const meds = status.data?.meds ?? [];

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-3">
      <p className="mb-2 text-[11px] uppercase tracking-wider text-slate-400">
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
      <p className="mt-1.5 text-[10px] text-slate-500">
        記録は体内カフェイン/薬の使用日数に反映(飲みすぎ＝MOHリスクの警告に効く)。
      </p>
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
            ? "border-rose-700/60 bg-rose-900/20 text-rose-300 hover:bg-rose-900/40"
            : "border-amber-700/60 bg-amber-900/20 text-amber-200 hover:bg-amber-900/40"
        }`}
      >
        {blocked ? "⚠ " : "+ "}
        {m.label}({DOSE}錠)
      </button>
      <div className="min-w-0 flex-1 text-[11px] leading-tight">
        <p className={blocked ? "text-rose-300" : "text-slate-400"}>{m.reason}</p>
        <p className="text-slate-500">
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
