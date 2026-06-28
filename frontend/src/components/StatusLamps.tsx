import { useEffect, useRef, useState } from "react";
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
import { achState, type AchState } from "../lib/achievement";
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

type LampState = AchState;

const STATE_CLASS: Record<LampState, string> = {
  // good は発光を弱め、warn/bad を相対的に目立たせる (図と地の分離)
  good: "text-prog-300/90 bg-prog-500/5",
  warn: "text-act-300 bg-act/10",
  bad: "text-risk bg-risk/10 lamp-throb",
  off: "text-hairline/70",
};

// SVG は textShadow が効かないので drop-shadow フィルタで発光させる。
// good は静かな点灯、warn/bad だけ強く光らせる。
const STATE_GLOW: Record<LampState, string> = {
  good: "none",
  warn: "drop-shadow(0 0 5px rgba(252,211,77,.65))",
  bad: "drop-shadow(0 0 6px rgba(251,113,133,.8))",
  off: "none",
};

const DIR_LABEL: Record<string, string> = {
  improving: "改善傾向", stable: "横ばい", declining: "低下傾向",
};

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

// 各ランプの「意味」と「状態に応じた次の一手」。
// desc = この指標が何か。good/attn = 状態別の具体行動 (じゃあ何すれば？に答える)。
const LAMP_META: Partial<Record<TrendMetricKey, { desc: string; good: string; attn: string }>> = {
  readiness: {
    desc: "Garminが睡眠・HRV・回復から出す『今日どれだけ追い込めるか』。高い=高強度OK",
    good: "夜に全身筋トレ or タバタHIITを1本入れる",
    attn: "筋トレ/HIITは明日に回し、今日はシャドーボクシング20分か散歩だけ",
  },
  sleep: {
    desc: "前夜の睡眠時間と質。7〜9時間が目標",
    good: "今夜も同じ時刻に就寝。寝る90分前に入浴を済ませる",
    attn: "今夜は30分早く布団へ。眠ければ15〜17時に20分だけ仮眠",
  },
  hrv: {
    desc: "心拍のゆらぎ＝自律神経の回復度。高い=回復、低い=疲労/ストレス",
    good: "予定通り動いてOK。負荷をかけて良い日",
    attn: "4-4-4-4のボックスブレシングを5分。今夜は30分早く寝る",
  },
  energy: {
    desc: "Garminの体力残量(0-100)。活動・ストレスで減り、休息・睡眠で回復",
    good: "今のうちに一番難しい仕事か運動を片付ける",
    attn: "15〜17時に20分仮眠を取る(コーヒーより効く)",
  },
  load: {
    desc: "急性(7日)÷慢性(28日)の運動負荷比。0.8〜1.3が安全帯",
    good: "今のペースを維持(増やしも減らしもしない)",
    attn: "物足りなければシャドーボクシング20分、疲れていれば今日は完全休養",
  },
  spo2: {
    desc: "睡眠中の血中酸素。95%以上が正常。低下が続くと無呼吸の疑い",
    good: "正常域。気にしなくてOK",
    attn: "時計を手首の骨から指1本ぶん上にずらして密着。数夜続けば睡眠外来へ",
  },
  respiration: {
    desc: "睡眠中の呼吸数。普段比+2以上は体調変化の先行サイン",
    good: "普段どおり",
    attn: "今日は運動を休み、水を1.5L以上、いつもより1時間早く就寝",
  },
  rhr_night: {
    desc: "睡眠中の安静時心拍。低い=回復良好。普段比+5以上は疲労/病気の兆候",
    good: "回復良好。普段どおりでOK",
    attn: "今日の筋トレは軽い有酸素に置き換え、夜は早めに就寝",
  },
  sleep_midpoint: {
    desc: "就寝リズムの規則性。ばらつき小=概日リズム安定(死亡リスク低)",
    good: "この就寝時刻をキープ",
    attn: "今夜はいつもの就寝時刻の±30分以内に布団に入る",
  },
  weight: {
    desc: "目標体重との差。範囲内が良い",
    good: "目標圏内。今の食事・運動を維持",
    attn: "夕食にタンパク質+20g(プロテイン1杯 or 卵2個 or 豆腐1丁)。減りすぎ注意",
  },
  body_fat: {
    desc: "体脂肪率。目標±許容内が良い",
    good: "目標圏内。維持",
    attn: "高ければ間食を素焼きナッツに替える、低すぎれば魚・卵で脂質を足す",
  },
};

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
  ignite,
  onTap,
}: {
  lamp: Lamp;
  index: number;
  selected: boolean;
  ignite: boolean;
  onTap: () => void;
}) {
  const Icon = lamp.icon;
  // reduced-motion 時は点滅の代わりにリングで bad を静的強調
  const badRing = lamp.state === "bad" ? "motion-reduce:ring-1 motion-reduce:ring-risk/80" : "";
  return (
    <button
      type="button"
      aria-label={lamp.label}
      aria-expanded={selected}
      onClick={onTap}
      // ヒット領域 44px (HIG/Material 準拠) を確保しつつアイコンは 8px 角の発光面に集約
      className="relative grid h-11 w-11 shrink-0 place-items-center"
    >
      <span
        className={`relative grid h-8 w-8 place-items-center rounded-md transition-transform active:scale-90 ${STATE_CLASS[lamp.state]} ${badRing} ${
          selected ? "ring-1 ring-ink-dim/70" : ""
        }`}
      >
        <Icon size={16} strokeWidth={2.2} style={{ filter: STATE_GLOW[lamp.state] }} />
        {lamp.badge != null && lamp.badge > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid h-3.5 min-w-3.5 place-items-center rounded-full bg-risk px-0.5 text-[9px] font-bold text-white">
            {lamp.badge}
          </span>
        )}
        {/* イグニッションチェックの一閃 (初回 / 更新時のみ) */}
        {ignite && (
          <span
            aria-hidden
            className="lamp-ignite-overlay pointer-events-none absolute inset-0 grid place-items-center rounded-md bg-ink/10 text-ink"
            style={{ animationDelay: `${index * 45}ms` }}
          >
            <Icon
              size={16}
              strokeWidth={2.2}
              style={{ filter: "drop-shadow(0 0 7px rgba(241,245,249,.9))" }}
            />
          </span>
        )}
      </span>
    </button>
  );
}

export function StatusLamps({
  alerts,
  pressure,
  igniteSignal,
}: {
  alerts?: WellbeingAlert[];
  pressure?: Pressure | null;
  /** 値が変わると起動演出を再生 (初回マウント=初回、データ更新時=手動/自動更新)。 */
  igniteSignal?: string | number | null;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [ignite, setIgnite] = useState(false);
  const lastSignal = useRef<string | number | null | undefined>(undefined);

  useEffect(() => {
    // 初回マウント、または igniteSignal が変化したときだけ一閃を再生する。
    // (毎レンダーでは光らないので「開くたび」の煩わしさを避ける)
    if (lastSignal.current === igniteSignal) return;
    lastSignal.current = igniteSignal;
    setIgnite(true);
    const t = setTimeout(() => setIgnite(false), 1400);
    return () => clearTimeout(t);
  }, [igniteSignal]);

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
    const st = achState(ach);
    const meta = LAMP_META[key];
    // 意味 → 現在値/トレンド → 次の一手 の順 (何か→今どう→どうする)
    const rows: string[] = [];
    if (meta) rows.push(meta.desc);
    rows.push(`現在値 ${fmtValue(key, m)}`);
    const wow = m.achievement_week_over_week;
    // 28日回帰の傾向と前週比の符号が矛盾するときは傾向ラベルを出さない
    const dirConsistent =
      m.direction &&
      !(wow && ((m.direction === "improving" && wow.delta < 0) ||
                (m.direction === "declining" && wow.delta > 0)));
    const dirPart = dirConsistent && m.direction ? DIR_LABEL[m.direction] : null;
    const wowPart = wow ? `前週比 ${wow.delta > 0 ? "+" : ""}${wow.delta.toFixed(0)}` : null;
    if (dirPart || wowPart) rows.push([dirPart, wowPart].filter(Boolean).join(" · "));
    if (m.subtitle) rows.push(m.subtitle);
    if (meta && st !== "off") rows.push(`→ ${st === "good" ? meta.good : meta.attn}`);
    return {
      id: key, icon, label,
      state: st,
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
      className="rounded-xl bg-void/80 p-2 ring-1 ring-panel/60"
      aria-label="状態インジケータ"
    >
      <div className="flex flex-wrap items-center gap-0.5">
        {lamps.map((lamp, i) => (
          <LampCell
            key={lamp.id}
            lamp={lamp}
            index={i}
            selected={openId === lamp.id}
            ignite={ignite}
            onTap={() => setOpenId(openId === lamp.id ? null : lamp.id)}
          />
        ))}
      </div>

      {/* マルチインフォメーションディスプレイ (タップしたランプの詳細) */}
      {open && (
        <div className="mt-2 rounded-lg bg-hull/80 px-3 py-2 ring-1 ring-panel/80">
          <div className="flex items-center justify-between">
            <span className={`text-xs font-medium ${STATE_CLASS[open.state].split(" ")[0]}`}>
              {open.heading}
            </span>
            <button
              type="button"
              aria-label="閉じる"
              onClick={() => setOpenId(null)}
              className="grid h-5 w-5 place-items-center rounded text-ink-faint hover:text-ink-dim"
            >
              <X size={12} />
            </button>
          </div>
          <div className="mt-0.5 space-y-0.5">
            {open.rows.map((row, i) => {
              const isAction = row.startsWith("→");
              const tone = open.state === "good" ? "text-prog-300" : "text-act-300";
              return (
                <div
                  key={i}
                  className={`text-[11px] leading-snug ${isAction ? `font-medium ${tone}` : "text-ink-dim"}`}
                >
                  {row}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
