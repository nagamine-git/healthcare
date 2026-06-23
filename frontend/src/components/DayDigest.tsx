import { useState } from "react";
import {
  Armchair, Brain, ChevronDown, ClipboardCheck, Coffee,
  Dumbbell, Home, ListChecks, MapPin, Moon, Sunrise,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { DayStorySegment, DayTimelineData } from "../lib/api";

/**
 * 今日のハイライト: グラフと同じデータを「何時にこれをやった」の時系列ダイジェストに。
 * グラフは"形"を読むのに強いが、離散イベント (カフェイン/運動/頭痛/記録/予定) と
 * 起床・就寝・主要な活動フェーズを時刻つきで縦に並べると一目で振り返れる。
 * 全エントリは timeline API の offset(h) を origin_jst から実時刻へ戻して表示する。
 */

type Entry = { h: number; icon: LucideIcon; color: string; text: string; sub?: string };

function pad(n: number): string {
  return n.toString().padStart(2, "0");
}

/** 推定の活動ラベル → アイコン/色/表示名。記録の谷間などは null で除外 */
function activityMeta(label: string): { icon: LucideIcon; color: string; text: string } | null {
  if (label.includes("記録")) return null; // 記録の谷間 / 記録なし
  if (label.includes("集中") || label.includes("負荷") || label.includes("緊張"))
    return { icon: Brain, color: "text-amber-300", text: "集中して作業" };
  if (label.includes("外出") || label.includes("移動"))
    return { icon: MapPin, color: "text-sky-300", text: "外出・移動" };
  if (label.includes("家事")) return { icon: Home, color: "text-cyan-300", text: "家事・育児など" };
  if (label.includes("休息") || label.includes("リラックス") || label.includes("ゆったり") || label.includes("在席"))
    return { icon: Armchair, color: "text-teal-300", text: "休息・ゆったり" };
  return null;
}

const WORKOUT_LABEL: Record<string, string> = {
  running: "ランニング", walking: "ウォーキング", cycling: "サイクリング",
  strength_training: "筋トレ", traditional_strength_training: "筋トレ",
  functional_strength_training: "筋トレ", yoga: "ヨガ", hiit: "HIIT", swimming: "スイミング",
};

export function DayDigest({ segments, t, originJst, nowH }: {
  segments: DayStorySegment[];
  t?: DayTimelineData;
  originJst: string;
  nowH: number | null;
}) {
  const [open, setOpen] = useState(true);
  const origin = new Date(originJst).getTime();
  const clock = (h: number): string => {
    const dt = new Date(origin + h * 3600_000);
    return `${dt.getHours()}:${pad(dt.getMinutes())}`;
  };
  // 未来 (予測ゾーン) のイベントは出さない。今夜の予定はグラフ下の凡例で別途出している
  const past = (h: number) => nowH == null || h <= nowH + 0.05;

  const entries: Entry[] = [];

  // 睡眠 (最長ブロック) → 就寝・起床
  const sleep = (t?.sleep_blocks ?? []).reduce<{ start_h: number; end_h: number } | null>(
    (a, b) => (!a || b.end_h - b.start_h > a.end_h - a.start_h ? b : a), null);
  if (sleep) {
    // start_h が窓の左端 (=0) に張り付くのは窓開始前から寝ていたケース → 時刻不明なので出さない
    if (sleep.start_h > 0.05 && past(sleep.start_h))
      entries.push({ h: sleep.start_h, icon: Moon, color: "text-indigo-300", text: "就寝" });
    if (sleep.end_h < 24 && past(sleep.end_h))
      entries.push({
        h: sleep.end_h, icon: Sunrise, color: "text-amber-200",
        text: "起きた", sub: `睡眠 ${(sleep.end_h - sleep.start_h).toFixed(1)}h`,
      });
  }

  // カフェイン
  for (const c of t?.caffeine ?? [])
    if (past(c.h))
      entries.push({ h: c.h, icon: Coffee, color: "text-violet-300", text: `カフェイン ${Math.round(c.mg)}mg` });

  // ワークアウト
  for (const w of t?.workouts ?? [])
    if (past(w.start_h)) {
      const min = Math.round((w.end_h - w.start_h) * 60);
      const name = w.type ? WORKOUT_LABEL[w.type] ?? w.type : "運動";
      entries.push({
        h: w.start_h, icon: Dumbbell, color: "text-emerald-300",
        text: name, sub: min > 0 ? `${min}分` : undefined,
      });
    }

  // 頭痛 (発作・おさまった)
  for (const m of t?.migraine ?? []) {
    if (past(m.start_h))
      entries.push({
        h: m.start_h, icon: Brain, color: "text-rose-300",
        text: "頭痛 発作", sub: m.severity != null ? `強度 ${m.severity}/10` : undefined,
      });
    if (m.end_h != null && past(m.end_h))
      entries.push({ h: m.end_h, icon: Brain, color: "text-rose-300/70", text: "頭痛 おさまった" });
  }

  // 体調記録
  if (t?.checkin && past(t.checkin.h)) {
    const c = t.checkin;
    const bits = [
      c.mood != null ? `気分${c.mood}` : null,
      c.energy != null ? `活力${c.energy}` : null,
      c.stress != null ? `ストレス${c.stress}` : null,
      c.soreness != null ? `筋肉痛${c.soreness}` : null,
    ].filter(Boolean);
    entries.push({
      h: c.h, icon: ClipboardCheck, color: "text-slate-200",
      text: "調子を記録", sub: bits.join(" / ") || undefined,
    });
  }

  // カレンダー予定はあくまで「予定 (参考)」で実際の行動ではないため、ハイライトには出さない
  // (グラフ上には破線オーバーレイで参考表示は残している)

  // 主要な活動フェーズ (推定の長い区間のみ。連続する同種はまとめる)
  let lastAct = "";
  for (const seg of segments) {
    if (seg.source !== "inferred" || seg.end_h - seg.start_h < 1.5 || !past(seg.start_h)) continue;
    const meta = activityMeta(seg.label);
    if (!meta || meta.text === lastAct) continue;
    lastAct = meta.text;
    entries.push({ h: seg.start_h, icon: meta.icon, color: meta.color, text: meta.text });
  }

  entries.sort((a, b) => a.h - b.h);
  if (entries.length === 0) return null;

  return (
    <div className="rounded-xl bg-slate-900/50">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1.5 px-3 py-2 text-left">
        <ListChecks size={14} className="text-slate-400" />
        <span className="text-xs uppercase tracking-wider text-slate-400">今日のハイライト</span>
        <span className="ml-auto text-[10px] text-slate-600">{entries.length}件</span>
        <ChevronDown size={14} className={`text-slate-500 transition-transform ${open ? "" : "-rotate-90"}`} />
      </button>
      {open && (
        <ul className="px-3 pb-2.5">
          {entries.map((e, i) => {
            const Icon = e.icon;
            return (
              <li key={i} className="flex items-center gap-2.5 py-1">
                <span className="w-10 shrink-0 text-right text-[11px] tabular-nums text-slate-500">{clock(e.h)}</span>
                <Icon size={14} className={`shrink-0 ${e.color}`} />
                <span className="min-w-0 leading-tight">
                  <span className="text-[13px] text-slate-200">{e.text}</span>
                  {e.sub && <span className="ml-1.5 text-[11px] text-slate-500">{e.sub}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
