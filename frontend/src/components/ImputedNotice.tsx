import { Sparkles } from "lucide-react";
import type { ImputedMetric } from "../lib/api";

/**
 * 一次データ欠損日に、統計推定で埋めた指標を「推定」バッジ付きで明示する。
 * 完璧を装わず、値・信頼度・予測区間・寄与要因を正直に出す。
 */

const LABEL: Record<string, string> = {
  sleep_score: "睡眠スコア",
  sleep_total_min: "睡眠時間",
  hrv: "HRV",
  body_battery: "Body Battery",
  resting_hr: "安静時心拍",
  steps: "歩数",
};

const CONF: Record<string, { text: string; cls: string }> = {
  high: { text: "信頼度 高", cls: "text-emerald-300" },
  medium: { text: "信頼度 中", cls: "text-sky-300" },
  low: { text: "信頼度 低", cls: "text-slate-400" },
};

function fmt(metric: string, v: number): string {
  if (metric === "sleep_total_min") return `${Math.floor(v / 60)}時間${Math.round(v % 60)}分`;
  return String(Math.round(v));
}

export function ImputedNotice({ imputed }: { imputed?: Record<string, ImputedMetric> }) {
  const items = imputed ? Object.values(imputed) : [];
  if (items.length === 0) return null;
  return (
    <section className="space-y-2 rounded-2xl border border-amber-500/25 bg-amber-500/[0.06] p-3">
      <div className="flex items-center gap-1.5">
        <Sparkles size={13} className="text-amber-300" />
        <span className="text-[11px] font-semibold text-amber-200">推定モード</span>
        <span className="text-[10px] text-slate-400">一次データ欠損 — 過去・気圧・曜日などから推定</span>
      </div>
      <div className="grid gap-1">
        {items.map((it) => {
          const conf = CONF[it.confidence] ?? CONF.low;
          return (
            <div key={it.metric} className="flex items-baseline gap-2 text-[11px]">
              <span className="w-24 shrink-0 text-slate-300">{LABEL[it.metric] ?? it.metric}</span>
              <span className="shrink-0 tabular-nums text-slate-100">
                {fmt(it.metric, it.value)}
                {it.low != null && it.high != null && (
                  <span className="ml-1 text-[9px] text-slate-500">
                    ({fmt(it.metric, it.low)}〜{fmt(it.metric, it.high)})
                  </span>
                )}
              </span>
              <span className={`shrink-0 text-[9px] ${conf.cls}`}>{conf.text}</span>
              {it.drivers.length > 0 && (
                <span className="min-w-0 flex-1 truncate text-[9px] text-slate-500">
                  根拠: {it.drivers.join("・")}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <p className="text-[9px] text-slate-500">
        推定値です。実測ではありません。装着すれば実測に切り替わります。
      </p>
    </section>
  );
}
