import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Clock3,
  Droplet,
  Dumbbell,
  Gauge,
  HeartPulse,
  Moon,
  Percent,
  Scale,
  Sprout,
  Target,
  TriangleAlert,
  Wind,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  Pressure,
  TrendMetric,
  TrendMetricKey,
  WellbeingAlert,
} from "../lib/api";

/**
 * 計器盤ランプ列 (車のダッシュボード / G-Shock 風)。
 * アイコン1つ = 1ランプ。発光色で状態、消灯 = データなし。
 * タップでストリップ直下に詳細 (マルチインフォメーションディスプレイ) を展開。
 * マウント時は全灯が白く一閃する「イグニッションチェック」。
 */

type LampState = "good" | "warn" | "bad" | "off";

const STATE_CLASS: Record<LampState, string> = {
  good: "text-emerald-300 bg-emerald-400/10",
  warn: "text-amber-300 bg-amber-400/10",
  bad: "text-rose-400 bg-rose-500/10 lamp-throb",
  off: "text-slate-700/70",
};

// SVG は textShadow が効かないので drop-shadow フィルタで発光させる
const STATE_GLOW: Record<LampState, string> = {
  good: "drop-shadow(0 0 5px rgba(52,211,153,.65))",
  warn: "drop-shadow(0 0 5px rgba(252,211,77,.65))",
  bad: "drop-shadow(0 0 6px rgba(251,113,133,.8))",
  off: "none",
};

const DIR_LABEL: Record<string, string> = {
  improving: "改善傾向", stable: "横ばい", declining: "低下傾向",
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
const METRIC_LAMPS: { key: TrendMetricKey; icon: LucideIcon; label: string }[] = [
  { key: "readiness", icon: Target, label: "攻め時" },
  { key: "sleep", icon: Moon, label: "睡眠" },
  { key: "hrv", icon: Activity, label: "自律神経" },
  { key: "energy", icon: Zap, label: "エネルギー" },
  { key: "load", icon: Dumbbell, label: "運動負荷" },
  { key: "spo2", icon: Droplet, label: "血中酸素" },
  { key: "respiration", icon: Wind, label: "呼吸数" },
  { key: "rhr_night", icon: HeartPulse, label: "夜間心拍" },
  { key: "sleep_midpoint", icon: Clock3, label: "睡眠リズム" },
  { key: "weight", icon: Scale, label: "体重" },
  { key: "body_fat", icon: Percent, label: "体脂肪" },
];

type Lamp = {
  id: string;
  icon: LucideIcon;
  label: string;
  state: LampState;
  badge?: number;
  /** 詳細パネルの見出し (例: "攻め時 70点") */
  heading: string;
  /** 詳細パネルの行 */
  rows: string[];
};

function LampCell({
  lamp,
  index,
  selected,
  onTap,
}: {
  lamp: Lamp;
  index: number;
  selected: boolean;
  onTap: () => void;
}) {
  const Icon = lamp.icon;
  return (
    <button
      type="button"
      aria-label={lamp.label}
      aria-expanded={selected}
      onClick={onTap}
      className={`relative grid h-8 w-8 shrink-0 place-items-center rounded-md transition-transform active:scale-90 ${STATE_CLASS[lamp.state]} ${
        selected ? "ring-1 ring-slate-400/70" : ""
      }`}
    >
      <Icon size={16} strokeWidth={2.2} style={{ filter: STATE_GLOW[lamp.state] }} />
      {lamp.badge != null && lamp.badge > 0 && (
        <span className="absolute -right-0.5 -top-0.5 grid h-3.5 min-w-3.5 place-items-center rounded-full bg-rose-500 px-0.5 text-[9px] font-bold text-white">
          {lamp.badge}
        </span>
      )}
      {/* イグニッションチェックの一閃 */}
      <span
        aria-hidden
        className="lamp-ignite-overlay pointer-events-none absolute inset-0 grid place-items-center rounded-md bg-slate-200/10 text-slate-100"
        style={{ animationDelay: `${index * 45}ms` }}
      >
        <Icon
          size={16}
          strokeWidth={2.2}
          style={{ filter: "drop-shadow(0 0 7px rgba(241,245,249,.9))" }}
        />
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
  const [openId, setOpenId] = useState<string | null>(null);
  const trends = useQuery({
    queryKey: ["trends", "daily"],
    queryFn: () => api.trends("daily", 28),
  });
  const life = useQuery({ queryKey: ["life"], queryFn: api.life });

  const lamps: Lamp[] = METRIC_LAMPS.map(({ key, icon, label }) => {
    const m = trends.data?.metrics[key];
    if (!m) {
      return {
        id: key, icon, label,
        state: "off" as LampState,
        heading: label,
        rows: ["データなし (同期待ち)"],
      };
    }
    const ach = m.achievement;
    const rows = [`現在値 ${fmtValue(key, m)}`];
    const wow = m.achievement_week_over_week;
    const dirPart = m.direction ? DIR_LABEL[m.direction] : null;
    const wowPart = wow ? `前週比 ${wow.delta > 0 ? "+" : ""}${wow.delta.toFixed(0)}` : null;
    if (dirPart || wowPart) rows.push([dirPart, wowPart].filter(Boolean).join(" · "));
    if (m.subtitle) rows.push(m.subtitle);
    return {
      id: key, icon, label,
      state: achState(ach),
      heading: `${label} ${ach != null ? `${Math.round(ach)}点` : "--"}`,
      rows,
    };
  });

  // ライフスコア
  const lifeData = life.data;
  const lifeScore = lifeData?.life_score ?? null;
  lamps.push({
    id: "life",
    icon: Sprout,
    label: "ライフ",
    state: achState(lifeScore),
    heading: `ライフスコア ${lifeScore != null ? `${Math.round(lifeScore)}点` : "--"}`,
    rows: lifeData
      ? [
          `記録 ${lifeData.coverage.active}/${lifeData.coverage.total} ドメイン`,
          lifeData.domains
            .filter((d) => d.achievement != null)
            .map((d) => `${d.label} ${Math.round(d.achievement!)}`)
            .join(" · ") || "達成度データなし",
        ]
      : ["読み込み中..."],
  });

  // 気圧リスク (calm は消灯 = 問題なし)
  const risk = pressure?.risk_level;
  lamps.push({
    id: "pressure",
    icon: Gauge,
    label: "気圧",
    state: risk === "severe" || risk === "warning" ? "bad" : risk === "watch" ? "warn" : "off",
    heading: `気圧 ${pressure?.current_hpa != null ? `${Math.round(pressure.current_hpa)}hPa` : ""}`,
    rows: pressure
      ? [
          pressure.risk_reason,
          pressure.delta_24h_hpa != null
            ? `24h変化 ${pressure.delta_24h_hpa > 0 ? "+" : ""}${pressure.delta_24h_hpa.toFixed(1)}hPa`
            : "",
        ].filter(Boolean)
      : ["データなし"],
  });

  // wellbeing アラート (無ければ消灯)
  const alertList = alerts ?? [];
  const hasCritical = alertList.some((a) => a.severity === "critical");
  lamps.push({
    id: "alerts",
    icon: TriangleAlert,
    label: "アラート",
    state: alertList.length === 0 ? "off" : hasCritical ? "bad" : "warn",
    badge: alertList.length,
    heading: alertList.length === 0 ? "アラートなし" : `アラート ${alertList.length}件`,
    rows: alertList.map((a) => `${a.title} — ${a.action}`),
  });

  const open = lamps.find((l) => l.id === openId) ?? null;

  return (
    <section
      className="rounded-2xl bg-slate-950/80 p-2 ring-1 ring-slate-800/60"
      aria-label="状態インジケータ"
    >
      <div className="flex flex-wrap items-center gap-1">
        {lamps.map((lamp, i) => (
          <LampCell
            key={lamp.id}
            lamp={lamp}
            index={i}
            selected={openId === lamp.id}
            onTap={() => setOpenId(openId === lamp.id ? null : lamp.id)}
          />
        ))}
      </div>

      {/* マルチインフォメーションディスプレイ (タップしたランプの詳細) */}
      {open && (
        <div className="mt-2 rounded-lg bg-slate-900/80 px-3 py-2 ring-1 ring-slate-800/80">
          <div className="flex items-center justify-between">
            <span className={`text-xs font-medium ${STATE_CLASS[open.state].split(" ")[0]}`}>
              {open.heading}
            </span>
            <button
              type="button"
              aria-label="閉じる"
              onClick={() => setOpenId(null)}
              className="grid h-5 w-5 place-items-center rounded text-slate-500 hover:text-slate-300"
            >
              <X size={12} />
            </button>
          </div>
          <div className="mt-0.5 space-y-0.5">
            {open.rows.map((row, i) => (
              <div key={i} className="text-[11px] leading-snug text-slate-400">
                {row}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
