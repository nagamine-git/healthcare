import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type CaffeineSource } from "../lib/api";

const MEDS: { source: CaffeineSource; label: string; amount: number }[] = [
  { source: "bufferin_premium", label: "バファリン", amount: 2 },
  { source: "ibuquick", label: "イブ", amount: 2 },
];

/** 鎮痛薬のワンタップ記録(頭痛タブ用)。薬の使用日数=MOH リスクの判断材料。 */
export function MedQuickLog() {
  const qc = useQueryClient();
  const log = useMutation({
    mutationFn: (m: { source: CaffeineSource; amount: number }) =>
      api.caffeineAdd(m.source, m.amount),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["today"] });
      qc.invalidateQueries({ queryKey: ["migraine"] });
      qc.invalidateQueries({ queryKey: ["caffeine"] });
    },
  });

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-3">
      <p className="mb-2 text-[11px] uppercase tracking-wider text-slate-400">鎮痛薬を記録</p>
      <div className="flex flex-wrap gap-2">
        {MEDS.map((m) => (
          <button
            key={m.source}
            disabled={log.isPending}
            onClick={() => log.mutate(m)}
            className="rounded-full border border-amber-700/60 bg-amber-900/20 px-3 py-1 text-sm text-amber-200 hover:bg-amber-900/40 disabled:opacity-50"
          >
            + {m.label}({m.amount}錠)
          </button>
        ))}
      </div>
      <p className="mt-1.5 text-[10px] text-slate-500">
        記録すると体内カフェイン/薬の使用日数に反映(飲みすぎ＝MOHリスクの警告に効く)。
      </p>
      {log.isSuccess && !log.isPending && (
        <p className="mt-1 text-[10px] text-emerald-400">記録しました</p>
      )}
    </div>
  );
}
