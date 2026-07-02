import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ear, Eye, VolumeX, Wind } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import { LoadingState } from "./ui/cockpit";
import type {
  SleepInterventionFlags,
  SleepInterventionNight,
  SleepInterventionRecord,
  SleepInterventionSet,
} from "../lib/api";

/**
 * 就寝前の介入トラッカー。耳栓/アイマスク/ノーズブリーズ/口テープを「今夜」ワンタップ記録。
 *
 * 効果分析は「着けた夜 vs 外した夜」を比較するため、未記録(null)と「外した(false)」を区別する。
 * 最初のタップでその夜が記録済みになり、タップした介入=使用(true)、残り=なし(false)として
 * 4項目すべてを明示保存する。以後タップでトグル。「クリア」で未記録に戻す。
 */

type Key = keyof SleepInterventionFlags;
const ITEMS: { key: Key; label: string; icon: LucideIcon }[] = [
  { key: "earplugs", label: "耳栓", icon: Ear },
  { key: "eyemask", label: "アイマスク", icon: Eye },
  { key: "nose_strip", label: "ノーズブリーズ", icon: Wind },
  { key: "mouth_tape", label: "口テープ", icon: VolumeX },
];
const KEYS = ITEMS.map((i) => i.key);

export function SleepInterventionCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sleep-intervention"], queryFn: api.sleepInterventionGet });

  const save = useMutation({
    mutationFn: (body: SleepInterventionSet) => api.sleepInterventionSet(body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: ["sleep-intervention"] });
      const prev = qc.getQueryData<SleepInterventionRecord>(["sleep-intervention"]);
      qc.setQueryData<SleepInterventionRecord>(["sleep-intervention"], (old) => {
        if (!old) return old;
        const t = old.tonight;
        const next: SleepInterventionNight = body.reset
          ? { ...t, earplugs: null, eyemask: null, nose_strip: null, mouth_tape: null, updated_at: null }
          : {
              ...t,
              earplugs: body.earplugs ?? t.earplugs,
              eyemask: body.eyemask ?? t.eyemask,
              nose_strip: body.nose_strip ?? t.nose_strip,
              mouth_tape: body.mouth_tape ?? t.mouth_tape,
              updated_at: new Date().toISOString(),
            };
        return { ...old, tonight: next };
      });
      return { prev };
    },
    onError: (_e, _b, ctx) => {
      if (ctx?.prev) qc.setQueryData(["sleep-intervention"], ctx.prev);
    },
    onSuccess: (data) => {
      qc.setQueryData(["sleep-intervention"], data);
      // 分析パネルと today スコアに反映
      qc.invalidateQueries({ queryKey: ["sleep-interventions"] });
    },
  });

  if (q.isLoading) return <LoadingState />;
  if (!q.data) return null;
  const t = q.data.tonight;
  const recorded = !!t.updated_at;

  // タップした介入だけ反転。未記録の他項目は false で確定させ、着脱を明示する。
  const toggle = (key: Key) => {
    const full: SleepInterventionSet = {};
    for (const k of KEYS) full[k] = (t[k] ?? false) as boolean;
    full[key] = !(t[key] ?? false);
    save.mutate(full);
  };

  return (
    <section className="space-y-2 rounded-xl bg-hull/40 p-4">
      <div className="flex items-center gap-1.5">
        <span className="text-xs uppercase tracking-wider text-ink-dim">就寝前の介入</span>
        <span className="ml-auto flex items-center gap-2">
          {recorded && (
            <button
              onClick={() => save.mutate({ reset: true })}
              className="text-[10px] text-ink-faint hover:text-ink-dim"
            >
              クリア
            </button>
          )}
          <span className="text-[10px] text-ink-faint">{t.display_label}</span>
        </span>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        {ITEMS.map(({ key, label, icon: Icon }) => {
          const v = t[key]; // true=使用 / false=なし / null=未記録
          const on = v === true;
          const off = v === false;
          const cls = on
            ? "border-prog-500 bg-prog-500/15 text-ink"
            : off
              ? "border-hairline bg-panel text-ink-faint"
              : "border-dashed border-hairline bg-panel/40 text-ink-faint";
          return (
            <button
              key={key}
              onClick={() => toggle(key)}
              aria-pressed={on}
              className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition active:scale-[0.98] ${cls}`}
            >
              <Icon size={16} className={on ? "text-prog-300" : "text-ink-faint"} />
              <span className="min-w-0 flex-1 truncate text-[12px]">{label}</span>
              <span className="shrink-0 text-[10px] tabular-nums">
                {on ? "使用" : off ? "なし" : "—"}
              </span>
            </button>
          );
        })}
      </div>
      <p className="text-[10px] text-ink-faint">
        {recorded
          ? "タップで使用/なしを切替。効果は「着けた夜 vs 外した夜」で分析します。"
          : "今夜使うものをタップ。1つ押すと残りは自動で「なし」になり、その夜が記録されます。"}
      </p>
    </section>
  );
}
