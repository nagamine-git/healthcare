import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Ear, Eye, VolumeX, Wind } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import type {
  SleepInterventionFlags,
  SleepInterventionHistoryNight,
  SleepInterventionHistoryResp,
  SleepInterventionSet,
} from "../lib/api";

/**
 * 過去の夜のバックフィル記録。「昨日あれ着けてたな」を後から入力し、分析を即開始できる。
 *
 * 過去は記憶が曖昧なので 3 状態トグル (未記録→着けた→外した→未記録)。覚えているものだけ記録でき、
 * 分析は未記録(null)をその夜×その介入だけ除外する。睡眠データがある夜のみ表示。
 */

type Key = keyof SleepInterventionFlags;
const ITEMS: { key: Key; label: string; icon: LucideIcon }[] = [
  { key: "earplugs", label: "耳栓", icon: Ear },
  { key: "eyemask", label: "アイマスク", icon: Eye },
  { key: "nose_strip", label: "ノーズブリーズ", icon: Wind },
  { key: "mouth_tape", label: "口テープ", icon: VolumeX },
];

// null → true → false → null
function nextState(v: boolean | null): boolean | null {
  if (v === null || v === undefined) return true;
  if (v === true) return false;
  return null;
}

export function SleepInterventionHistory() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: ["sleep-intervention-history"],
    queryFn: api.sleepInterventionHistory,
    enabled: open,
  });

  const save = useMutation({
    mutationFn: (body: SleepInterventionSet) => api.sleepInterventionSet(body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: ["sleep-intervention-history"] });
      const prev = qc.getQueryData<SleepInterventionHistoryResp>(["sleep-intervention-history"]);
      qc.setQueryData<SleepInterventionHistoryResp>(["sleep-intervention-history"], (old) => {
        if (!old) return old;
        const clearKey = body.clear?.[0];
        return {
          nights: old.nights.map((n) => {
            if (n.date !== body.date) return n;
            const patch: Partial<SleepInterventionFlags> = {};
            for (const { key } of ITEMS) if (body[key] != null) patch[key] = body[key];
            if (clearKey) patch[clearKey as Key] = null;
            return { ...n, ...patch };
          }),
        };
      });
      return { prev };
    },
    onError: (_e, _b, ctx) => {
      if (ctx?.prev) qc.setQueryData(["sleep-intervention-history"], ctx.prev);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sleep-interventions"] });
    },
  });

  const cycle = (night: SleepInterventionHistoryNight, key: Key) => {
    const nv = nextState(night[key]);
    if (nv === null) save.mutate({ date: night.date, clear: [key] });
    else save.mutate({ date: night.date, [key]: nv });
  };

  const nights = q.data?.nights ?? [];

  return (
    <section className="rounded-xl bg-hull/40">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 p-4 text-left"
      >
        <span className="text-xs uppercase tracking-wider text-ink-dim">過去の夜を記録</span>
        <span className="text-[10px] text-ink-faint">昨日はどうだった？</span>
        <ChevronDown
          size={14}
          className={`ml-auto text-ink-faint transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="space-y-2 px-4 pb-4">
          <p className="text-[10px] text-ink-faint">
            タップで 未記録 → 着けた → 外した を切替。覚えている夜だけでOK（分析は未記録をスキップ）。
          </p>
          {q.isLoading && <p className="text-[11px] text-ink-faint">読み込み中…</p>}
          {!q.isLoading && nights.length === 0 && (
            <p className="text-[11px] text-ink-faint">記録できる睡眠データがまだありません。</p>
          )}
          {nights.map((n) => (
            <div key={n.date} className="flex items-center gap-2 border-t border-hairline pt-2">
              <div className="w-20 shrink-0">
                <div className="text-[11px] text-ink-dim">{n.display_label}</div>
                <div className="text-[9px] text-ink-faint">
                  {n.sleep_score != null ? `スコア ${Math.round(n.sleep_score)}` : "スコア —"}
                </div>
              </div>
              <div className="flex flex-1 justify-end gap-1">
                {ITEMS.map(({ key, label, icon: Icon }) => {
                  const v = n[key];
                  const on = v === true;
                  const off = v === false;
                  const cls = on
                    ? "border-prog-500 bg-prog-500/15 text-prog-300"
                    : off
                      ? "border-hairline bg-panel text-ink-faint line-through"
                      : "border-dashed border-hairline bg-panel/40 text-ink-faint/60";
                  return (
                    <button
                      key={key}
                      onClick={() => cycle(n, key)}
                      title={`${label}: ${on ? "着けた" : off ? "外した" : "未記録"}`}
                      aria-label={`${label} ${n.display_label} ${on ? "着けた" : off ? "外した" : "未記録"}`}
                      className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg border transition active:scale-90 ${cls}`}
                    >
                      <Icon size={14} />
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
