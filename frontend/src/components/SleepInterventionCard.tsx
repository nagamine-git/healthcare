import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioWaveform, BedDouble, Brain, Ear, Eye, VolumeX, Wind } from "lucide-react";
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
 * 就寝前の介入トラッカー。耳栓/アイマスク/ノーズブリーズ/口テープ/呼吸法/瞑想を「今夜」ワンタップ記録。
 *
 * 効果分析は「着けた夜 vs 外した夜」を比較するため、未記録(null)と「外した(false)」を区別する。
 * 最初のタップでその夜が記録済みになり、タップした介入=使用(true)、残り=なし(false)として
 * 全項目を明示保存する。以後タップでトグル。「クリア」で未記録に戻す。
 *
 * breathing は WindDownCard の呼吸セッション完了時に自動 ON されるが、ここでも手動トグルできる
 * ようにして「今夜つけた/外した」を後から上書きできるようにしている(最後の書き込みが勝つ)。
 */

type Key = keyof SleepInterventionFlags;
const ITEMS: { key: Key; label: string; icon: LucideIcon }[] = [
  { key: "earplugs", label: "耳栓", icon: Ear },
  { key: "eyemask", label: "アイマスク", icon: Eye },
  { key: "nose_strip", label: "ノーズブリーズ", icon: Wind },
  { key: "mouth_tape", label: "口テープ", icon: VolumeX },
  { key: "breathing", label: "呼吸法", icon: AudioWaveform },
  { key: "meditation", label: "瞑想", icon: Brain },
];
const KEYS = ITEMS.map((i) => i.key);

export function SleepInterventionCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sleep-intervention"], queryFn: api.sleepInterventionGet });
  const beddingQ = useQuery({ queryKey: ["bedding-options"], queryFn: api.beddingOptions });

  const save = useMutation({
    mutationFn: (body: SleepInterventionSet) => api.sleepInterventionSet(body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: ["sleep-intervention"] });
      const prev = qc.getQueryData<SleepInterventionRecord>(["sleep-intervention"]);
      qc.setQueryData<SleepInterventionRecord>(["sleep-intervention"], (old) => {
        if (!old) return old;
        const t = old.tonight;
        const next: SleepInterventionNight = body.reset
          ? {
              ...t,
              ...Object.fromEntries(KEYS.map((k) => [k, null])),
              updated_at: null,
            }
          : {
              ...t,
              ...Object.fromEntries(KEYS.map((k) => [k, body[k] ?? t[k]])),
              bedding: body.bedding === undefined ? t.bedding : body.bedding || null,
              in_bed_at:
                body.in_bed_now === undefined
                  ? t.in_bed_at
                  : body.in_bed_now
                    ? new Date().toISOString()
                    : null,
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

      {/* どの布団で寝たか (自由登録)。効果分析は「その布団の夜 vs 他の布団の夜」の
          one-vs-rest。選択肢が2つ以上あって初めて比較できる。 */}
      <BeddingPicker
        current={t.bedding}
        options={beddingQ.data?.items ?? []}
        onPick={(name) => save.mutate({ bedding: name })}
      />

      {/* 「布団に入った時刻」は Garmin が測れない唯一の時刻 (寝ついた時刻は測れる)。
          記録が貯まると入眠潜時が臨床既定値 15分 から本人の実測 median に切り替わり、
          今夜の計画の「布団に入る」時刻がその人に合った値になる。 */}
      <button
        onClick={() => save.mutate({ in_bed_now: !t.in_bed_at })}
        aria-pressed={!!t.in_bed_at}
        className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition active:scale-[0.98] ${
          t.in_bed_at
            ? "border-prog-500 bg-prog-500/15 text-ink"
            : "border-dashed border-hairline bg-panel/40 text-ink-faint"
        }`}
      >
        <BedDouble size={16} className={t.in_bed_at ? "text-prog-300" : "text-ink-faint"} />
        <span className="min-w-0 flex-1 truncate text-[12px]">布団に入った</span>
        <span className="shrink-0 text-[10px] tabular-nums">
          {t.in_bed_at
            ? new Date(t.in_bed_at).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })
            : "いま記録"}
        </span>
      </button>
      <p className="text-[10px] text-ink-faint">
        寝ついた時刻は Garmin が測れますが、布団に入った時刻は測れません。押しておくと
        「布団に入ってから寝つくまで」が実測でき、今夜の計画の逆算があなたの値に変わります。
      </p>
    </section>
  );
}


/** 布団の選択チップ + 選択肢の追加/削除。名前は好きな数だけ登録できる。 */
function BeddingPicker({ current, options, onPick }: {
  current: string | null;
  options: { id: number; name: string }[];
  onPick: (name: string) => void;
}) {
  const qc = useQueryClient();
  const [managing, setManaging] = useState(false);
  const [newName, setNewName] = useState("");
  const refresh = (data: { items: { id: number; name: string }[] }) =>
    qc.setQueryData(["bedding-options"], data);
  const add = useMutation({ mutationFn: api.beddingOptionAdd, onSuccess: refresh });
  const del = useMutation({ mutationFn: api.beddingOptionDelete, onSuccess: refresh });

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <BedDouble size={12} className="text-ink-faint" />
        <span className="text-[10px] text-ink-dim">今夜の布団</span>
        <button onClick={() => setManaging((m) => !m)}
          className="ml-auto text-[10px] text-ink-faint hover:text-ink-dim">
          {managing ? "閉じる" : "編集"}
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = current === o.name;
          return (
            <span key={o.id} className="flex items-center">
              <button
                onClick={() => onPick(on ? "" : o.name)}
                aria-pressed={on}
                className={`press rounded-full border px-2.5 py-1 text-[11px] ${
                  on ? "border-prog-500 bg-prog-500/15 text-ink"
                     : "border-hairline bg-panel/40 text-ink-dim"
                }`}
              >
                {o.name}
              </button>
              {managing && (
                <button onClick={() => del.mutate(o.id)} aria-label={`${o.name} を削除`}
                  className="press ml-0.5 px-1 text-[11px] text-rose-300">×</button>
              )}
            </span>
          );
        })}
        {options.length === 0 && !managing && (
          <button onClick={() => setManaging(true)}
            className="text-[11px] text-ink-faint underline">布団を登録する</button>
        )}
      </div>
      {managing && (
        <div className="flex items-center gap-1.5">
          <input value={newName} onChange={(e) => setNewName(e.target.value)}
            placeholder="例: 羽毛 / せんべい / 客用"
            maxLength={60}
            className="min-w-0 flex-1 rounded bg-hull px-2 py-1 text-[11px] text-ink" />
          <button
            onClick={() => { if (newName.trim()) { add.mutate(newName.trim()); setNewName(""); } }}
            disabled={add.isPending || !newName.trim()}
            className="press rounded bg-act-500/20 px-2 py-1 text-[11px] text-act-300 disabled:opacity-40">
            追加
          </button>
        </div>
      )}
      <p className="text-[9px] text-ink-faint">
        選択肢を消しても過去の夜の記録と分析は残ります。2種類以上の記録が貯まると比較できます。
      </p>
    </div>
  );
}