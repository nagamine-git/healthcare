import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type {
  Pressure,
  TrendMetric,
  TrendMetricKey,
  WellbeingAlert,
} from "../lib/api";

/**
 * 計器盤ランプ列 (車のダッシュボード / G-Shock 風)。
 * 漢字1文字 = 1ランプ。発光色で状態、消灯 = データなし。
 * マウント時は全灯が白く一閃する「イグニッションチェック」。
 */

type LampState = "good" | "warn" | "bad" | "off";

const STATE_CLASS: Record<LampState, string> = {
  good: "text-emerald-300 bg-emerald-400/10",
  warn: "text-amber-300 bg-amber-400/10",
  bad: "text-rose-400 bg-rose-500/10 lamp-throb",
  off: "text-slate-700/70",
};

const STATE_GLOW: Record<LampState, string> = {
  good: "0 0 8px rgba(52,211,153,.55)",
  warn: "0 0 8px rgba(252,211,77,.55)",
  bad: "0 0 10px rgba(251,113,133,.7)",
  off: "none",
};

function achState(ach: number | null | undefined): LampState {
  if (ach == null) return "off";
  if (ach >= 70) return "good";
  if (ach >= 40) return "warn";
  return "bad";
}

function fmtValue(key: TrendMetricKey, m: TrendMetric): string {
  if (m.current_raw == null) return "--";
  if (key === "sleep") {
    const h = Math.floor(m.current_raw / 60);
    const mm = Math.round(m.current_raw % 60);
    return `${h}時間${mm.toString().padStart(2, "0")}分`;
  }
  if (key === "sleep_midpoint") {
    const h = Math.floor(m.current_raw);
    const mm = Math.round((m.current_raw - h) * 60);
    return `${h}:${mm.toString().padStart(2, "0")}`;
  }
  return `${m.current_raw}${m.unit}`;
}

// トレンド指標 → ランプ (表示順 = 重要度順)
const METRIC_LAMPS: { key: TrendMetricKey; glyph: string; label: string }[] = [
  { key: "readiness", glyph: "攻", label: "攻め時" },
  { key: "sleep", glyph: "睡", label: "睡眠" },
  { key: "hrv", glyph: "神", label: "自律神経" },
  { key: "energy", glyph: "燃", label: "エネルギー" },
  { key: "load", glyph: "荷", label: "運動負荷" },
  { key: "spo2", glyph: "酸", label: "血中酸素" },
  { key: "respiration", glyph: "呼", label: "呼吸数" },
  { key: "rhr_night", glyph: "拍", label: "夜間心拍" },
  { key: "sleep_midpoint", glyph: "律", label: "睡眠リズム" },
  { key: "weight", glyph: "重", label: "体重" },
  { key: "body_fat", glyph: "脂", label: "体脂肪" },
];

type Lamp = {
  glyph: string;
  state: LampState;
  tooltip: string;
  targetId: string;
  badge?: number;
};

function LampCell({ lamp, index }: { lamp: Lamp; index: number }) {
  return (
    <button
      type="button"
      title={lamp.tooltip}
      aria-label={lamp.tooltip}
      onClick={() =>
        document.getElementById(lamp.targetId)?.scrollIntoView({ behavior: "smooth" })
      }
      className={`relative grid h-8 w-8 shrink-0 place-items-center rounded-md text-[15px] font-medium leading-none transition-transform active:scale-90 ${STATE_CLASS[lamp.state]}`}
      style={{ textShadow: STATE_GLOW[lamp.state] }}
    >
      {lamp.glyph}
      {lamp.badge != null && lamp.badge > 0 && (
        <span className="absolute -right-0.5 -top-0.5 grid h-3.5 min-w-3.5 place-items-center rounded-full bg-rose-500 px-0.5 text-[9px] font-bold text-white">
          {lamp.badge}
        </span>
      )}
      {/* イグニッションチェックの一閃 */}
      <span
        aria-hidden
        className="lamp-ignite-overlay pointer-events-none absolute inset-0 grid place-items-center rounded-md bg-slate-200/10 text-[15px] font-medium text-slate-100"
        style={{ animationDelay: `${index * 45}ms`, textShadow: "0 0 10px rgba(241,245,249,.9)" }}
      >
        {lamp.glyph}
      </span>
    </button>
  );
}

export function StatusLamps({
  alerts,
  pressure,
}: {
  alerts?: WellbeingAlert[];
  pressure?: Pressure | null;
}) {
  const trends = useQuery({
    queryKey: ["trends", "daily"],
    queryFn: () => api.trends("daily", 28),
  });
  const life = useQuery({ queryKey: ["life"], queryFn: api.life });

  const lamps: Lamp[] = METRIC_LAMPS.map(({ key, glyph, label }) => {
    const m = trends.data?.metrics[key];
    if (!m) {
      return { glyph, state: "off" as LampState, tooltip: `${label}: データなし`, targetId: "trends-section" };
    }
    const ach = m.achievement;
    return {
      glyph,
      state: achState(ach),
      tooltip: `${label} ${ach != null ? Math.round(ach) : "--"}点 · ${fmtValue(key, m)}`,
      targetId: "trends-section",
    };
  });

  // 命: ライフスコア
  const lifeScore = life.data?.life_score ?? null;
  lamps.push({
    glyph: "命",
    state: achState(lifeScore),
    tooltip: `ライフスコア ${lifeScore != null ? Math.round(lifeScore) : "--"}点`,
    targetId: "life-section",
  });

  // 圧: 気圧リスク (calm は消灯 = 問題なし)
  const risk = pressure?.risk_level;
  lamps.push({
    glyph: "圧",
    state: risk === "severe" || risk === "warning" ? "bad" : risk === "watch" ? "warn" : "off",
    tooltip: pressure ? `気圧: ${pressure.risk_reason}` : "気圧: データなし",
    targetId: "trends-section",
  });

  // 警: wellbeing アラート (無ければ消灯)
  const alertList = alerts ?? [];
  const hasCritical = alertList.some((a) => a.severity === "critical");
  lamps.push({
    glyph: "警",
    state: alertList.length === 0 ? "off" : hasCritical ? "bad" : "warn",
    tooltip:
      alertList.length === 0
        ? "アラートなし"
        : alertList.map((a) => a.title).join(" / "),
    targetId: "alerts-section",
    badge: alertList.length,
  });

  return (
    <section
      className="flex flex-wrap items-center gap-1 rounded-2xl bg-slate-950/80 p-2 ring-1 ring-slate-800/60"
      aria-label="状態インジケータ"
    >
      {lamps.map((lamp, i) => (
        <LampCell key={lamp.glyph} lamp={lamp} index={i} />
      ))}
    </section>
  );
}
