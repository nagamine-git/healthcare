import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioWaveform, Brain, X } from "lucide-react";
import { api } from "../lib/api";
import type { AlcoholSource, CaffeineSource, SleepInterventionFlags } from "../lib/api";
import { CheckinCard } from "./CheckinCard";
import { SleepInterventionCard } from "./SleepInterventionCard";

/**
 * グローバル「+」から開くクイックログシート。どの画面からでも 2 タップで記録する
 * (記録導線の統一 — 2026-07-02 UI/UX 改革 Phase 2)。
 *
 * 調子/頭痛 と 睡眠介入 は既存カードをそのまま埋め込み (ロジック重複ゼロ)。
 * カフェイン/酒 はプリセットのワンタップ・ミニフォーム。食事は複雑なので
 * 健康タブ (MealPlanner) へのショートカットに留める。
 */

type Seg = "checkin" | "intervention" | "caffeine" | "alcohol";
const SEGS: { key: Seg; label: string }[] = [
  { key: "checkin", label: "調子・頭痛" },
  { key: "intervention", label: "睡眠介入" },
  { key: "caffeine", label: "カフェイン" },
  { key: "alcohol", label: "酒" },
];

const CAFFEINE_LABEL: Record<string, string> = {
  instant_coffee: "インスタント",
  canned_coffee: "缶コーヒー",
  nespresso: "ネスプレッソ",
  drip_coffee: "ドリップ",
  green_tea: "緑茶",
  ibuquick: "イブクイック",
  bufferin_premium: "バファリンP",
};
const ALCOHOL_LABEL: Record<string, string> = {
  beer_glass: "ビール中",
  beer_can_500: "ビール500",
  wine_glass: "ワイン",
  sake_go: "日本酒1合",
  shochu_mizuwari: "焼酎水割",
  highball: "ハイボール",
  strong_chuhai: "ストロング",
};

function PresetGrid({
  entries,
  onTap,
  pendingKey,
}: {
  entries: { key: string; label: string; sub: string }[];
  onTap: (key: string) => void;
  pendingKey: string | null;
}) {
  return (
    <div className="grid grid-cols-3 gap-1.5">
      {entries.map((e) => (
        <button
          key={e.key}
          onClick={() => onTap(e.key)}
          disabled={pendingKey !== null}
          className={`rounded-lg border border-hairline bg-panel/60 px-2 py-2.5 text-center transition active:scale-95 hover:border-white/15 disabled:opacity-50 ${
            pendingKey === e.key ? "border-prog-500" : ""
          }`}
        >
          <div className="truncate text-[12px] text-ink">{e.label}</div>
          <div className="text-[9px] text-ink-faint">{e.sub}</div>
        </button>
      ))}
    </div>
  );
}

export function QuickLogSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [seg, setSeg] = useState<Seg>("checkin");
  const [done, setDone] = useState<string | null>(null);

  // シートを開くたびに確認メッセージはリセット
  useEffect(() => {
    if (open) setDone(null);
  }, [open]);

  const cafPresets = useQuery({
    queryKey: ["caffeine-presets"],
    queryFn: api.caffeinePresets,
    enabled: open && seg === "caffeine",
  });
  const alcPresets = useQuery({
    queryKey: ["alcohol-presets"],
    queryFn: api.alcoholPresets,
    enabled: open && seg === "alcohol",
  });

  const addCaffeine = useMutation({
    mutationFn: ({ source, amount }: { source: CaffeineSource; amount: number }) =>
      api.caffeineAdd(source, amount),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["caffeine-list"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      setDone(`${CAFFEINE_LABEL[v.source] ?? v.source} を記録しました`);
    },
  });
  const addAlcohol = useMutation({
    mutationFn: ({ source, amount }: { source: AlcoholSource; amount: number }) =>
      api.alcoholAdd(source, amount),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: ["alcohol-list"] });
      qc.invalidateQueries({ queryKey: ["today"] });
      setDone(`${ALCOHOL_LABEL[v.source] ?? v.source} を記録しました`);
    },
  });
  // 「もうやった」の事後ワンタップ (呼吸法/瞑想)。WindDownCard の呼吸セッションと違い実施時間を
  // 計測していないため、writeMindful (Apple Health への分数書き出し) はここでは呼ばない —
  // 不明な分数を真実源である HealthKit に書き込むと記録が汚れる。自前DBのフラグ (n-of-1 分析用)
  // だけ true にする。時間込みで記録したい場合は上の「呼吸で整える」セッションを使う。
  const sleepQuickLog = useMutation({
    mutationFn: (flag: "breathing" | "meditation") =>
      api.sleepInterventionSet({ [flag]: true } as Partial<SleepInterventionFlags>),
    onSuccess: (_d, flag) => {
      qc.invalidateQueries({ queryKey: ["sleep-intervention"] });
      qc.invalidateQueries({ queryKey: ["sleep-intervention-history"] });
      qc.invalidateQueries({ queryKey: ["sleep-interventions"] });
      setDone(`${flag === "breathing" ? "呼吸法" : "瞑想"}を記録しました`);
    },
  });

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-label="クイック記録">
      {/* スクリム */}
      <button
        aria-label="閉じる"
        onClick={onClose}
        className="absolute inset-0 bg-void/70 backdrop-blur-sm"
      />
      {/* シート本体 */}
      <div
        className="absolute inset-x-0 bottom-0 max-h-[82vh] overflow-y-auto rounded-t-2xl border-t border-white/10 bg-hull shadow-float"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
      >
        <div className="sticky top-0 z-10 bg-hull/95 px-4 pt-3 backdrop-blur-xl">
          <div className="mx-auto mb-2 h-1 w-9 rounded-full bg-hairline" />
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-ink">クイック記録</span>
            <button
              onClick={() => {
                onClose();
                window.location.hash = "#tab-health"; // Today の健康タブ (MealPlanner) へ
              }}
              className="text-[11px] text-ink-faint underline hover:text-ink-dim"
            >
              食事はこちら
            </button>
            <button onClick={onClose} aria-label="閉じる" className="ml-auto p-1 text-ink-faint hover:text-ink">
              <X size={18} />
            </button>
          </div>
          <div className="no-scrollbar -mx-1 mt-2 flex gap-1.5 overflow-x-auto px-1 pb-2">
            {SEGS.map((s) => (
              <button
                key={s.key}
                onClick={() => setSeg(s.key)}
                className={`press shrink-0 rounded-full px-3 py-1 text-[12px] font-medium transition-colors ${
                  seg === s.key ? "bg-ink text-void" : "bg-panel text-ink-dim hover:text-ink"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2 px-4 pt-2">
          {done && (
            <div className="rounded-lg bg-prog-500/15 px-3 py-2 text-[12px] text-prog-300">
              ✓ {done}
            </div>
          )}
          {seg === "checkin" && <CheckinCard />}
          {seg === "intervention" && (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-1.5">
                <button
                  onClick={() => sleepQuickLog.mutate("breathing")}
                  disabled={sleepQuickLog.isPending}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-hairline bg-panel/60 px-2 py-2.5 text-[12px] text-ink transition active:scale-95 hover:border-white/15 disabled:opacity-50"
                >
                  <AudioWaveform size={14} className="text-prog-300" />
                  呼吸した
                </button>
                <button
                  onClick={() => sleepQuickLog.mutate("meditation")}
                  disabled={sleepQuickLog.isPending}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-hairline bg-panel/60 px-2 py-2.5 text-[12px] text-ink transition active:scale-95 hover:border-white/15 disabled:opacity-50"
                >
                  <Brain size={14} className="text-prog-300" />
                  瞑想した
                </button>
              </div>
              <SleepInterventionCard />
            </div>
          )}
          {seg === "caffeine" && (
            <div className="space-y-2 rounded-xl bg-hull/40 p-1">
              <PresetGrid
                entries={Object.entries(cafPresets.data ?? {})
                  .filter(([k]) => k !== "manual")
                  .map(([k, p]) => ({
                    key: k,
                    label: CAFFEINE_LABEL[k] ?? k,
                    sub: `${p.default_amount}${p.unit} ≈ ${Math.round(p.default_mg)}mg`,
                  }))}
                onTap={(k) =>
                  addCaffeine.mutate({
                    source: k as CaffeineSource,
                    amount: cafPresets.data?.[k as CaffeineSource]?.default_amount ?? 1,
                  })
                }
                pendingKey={addCaffeine.isPending ? (addCaffeine.variables?.source ?? null) : null}
              />
              <p className="px-2 pb-1 text-[10px] text-ink-faint">
                タップで既定量を記録。量の調整・履歴は 健康タブ のカフェインパネルで。
              </p>
            </div>
          )}
          {seg === "alcohol" && (
            <div className="space-y-2 rounded-xl bg-hull/40 p-1">
              <PresetGrid
                entries={Object.entries(alcPresets.data ?? {})
                  .filter(([k]) => k !== "manual")
                  .map(([k, p]) => ({
                    key: k,
                    label: ALCOHOL_LABEL[k] ?? k,
                    sub: `${p.default_amount}${p.unit} ≈ ${Math.round(p.default_grams)}g`,
                  }))}
                onTap={(k) =>
                  addAlcohol.mutate({
                    source: k as AlcoholSource,
                    amount: alcPresets.data?.[k as AlcoholSource]?.default_amount ?? 1,
                  })
                }
                pendingKey={addAlcohol.isPending ? (addAlcohol.variables?.source ?? null) : null}
              />
              <p className="px-2 pb-1 text-[10px] text-ink-faint">
                タップで既定量を記録。量の調整・履歴は 健康タブ の飲酒パネルで。
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
