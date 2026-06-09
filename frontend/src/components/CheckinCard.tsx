import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Smile } from "lucide-react";
import { api } from "../lib/api";
import type { CheckinUpdate } from "../lib/api";

/**
 * 今日の調子: 気分/活力/ストレス/筋肉痛を 5 段階でタップ記録 (即時保存)。
 * 客観データ (HRV/睡眠) が代理する「実際どう感じるか」の結果変数を入れる。
 */

type Dim = {
  key: keyof CheckinUpdate;
  label: string;
  // 高い値が良いか (色の向き)。stress/soreness は高いほど悪い。
  goodHigh: boolean;
};

const DIMS: Dim[] = [
  { key: "mood", label: "気分", goodHigh: true },
  { key: "energy", label: "活力", goodHigh: true },
  { key: "stress", label: "ストレス", goodHigh: false },
  { key: "soreness", label: "筋肉痛", goodHigh: false },
];

function dotColor(level: number, value: number | null, goodHigh: boolean): string {
  if (value == null || level > value) return "bg-slate-700";
  // 値の "良し悪し" で色: goodHigh は高いほど緑、低いほど赤。stress 等は逆。
  const good = goodHigh ? value >= 4 : value <= 2;
  const bad = goodHigh ? value <= 2 : value >= 4;
  if (good) return "bg-emerald-500";
  if (bad) return "bg-rose-500";
  return "bg-amber-500";
}

export function CheckinCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["checkin"], queryFn: api.getCheckin });
  const save = useMutation({
    mutationFn: (body: CheckinUpdate) => api.postCheckin(body),
    onSuccess: (data) => {
      qc.setQueryData(["checkin"], data);
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const today = q.data?.today;

  return (
    <section className="space-y-2 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center gap-1.5">
        <Smile size={14} className="text-emerald-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">今日の調子</span>
        <span className="ml-auto text-[10px] text-slate-500">タップで記録 (1=低 / 5=高)</span>
      </div>

      <div className="grid gap-1.5">
        {DIMS.map((d) => {
          const value = (today?.[d.key] as number | null) ?? null;
          return (
            <div key={d.key} className="flex items-center gap-2">
              <span className="w-14 text-[11px] text-slate-300">{d.label}</span>
              <div className="flex gap-1.5">
                {[1, 2, 3, 4, 5].map((lvl) => (
                  <button
                    key={lvl}
                    aria-label={`${d.label} ${lvl}`}
                    onClick={() => save.mutate({ [d.key]: lvl } as CheckinUpdate)}
                    className={`h-5 w-5 rounded-full transition active:scale-90 ${dotColor(lvl, value, d.goodHigh)} ${
                      value != null && lvl <= value ? "" : "hover:bg-slate-600"
                    }`}
                  />
                ))}
              </div>
              {value != null && (
                <span className="text-[10px] tabular-nums text-slate-500">{value}</span>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
