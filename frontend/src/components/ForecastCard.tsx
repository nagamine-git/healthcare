import { useQuery } from "@tanstack/react-query";
import { TrendingUp, CloudRain, BatteryLow } from "lucide-react";
import { api } from "../lib/api";
import type { ForecastRisk, ImputedMetric } from "../lib/api";

/**
 * 未来予測カード。確度で濃淡をつける:
 * 【高・濃い】片頭痛リスク予報 (検証済みトリガー×48h気圧予報)
 * 【中】今日この先のエネルギー(Body Battery)推移
 * 【低・薄い】明日の一次指標 (補完エンジン、ベイズ天井で参考値)
 */

// confidence → 不透明度 (確度が高いほど濃く)
const OPACITY: Record<string, string> = { high: "opacity-100", medium: "opacity-80", low: "opacity-50" };
const CONF_LABEL: Record<string, string> = { high: "確度 高", medium: "確度 中", low: "確度 低（参考）" };

const RISK: Record<ForecastRisk, { text: string; cls: string; dot: string }> = {
  high: { text: "高", cls: "text-rose-300", dot: "#fb7185" },
  elevated: { text: "やや高", cls: "text-amber-300", dot: "#fbbf24" },
  low: { text: "低", cls: "text-emerald-300", dot: "#34d399" },
};

const TM_LABEL: Record<string, string> = {
  sleep_score: "睡眠スコア", sleep_total_min: "睡眠時間", hrv: "HRV",
  body_battery: "Body Battery", resting_hr: "安静時心拍", steps: "歩数",
};
const tmFmt = (m: string, v: number) =>
  m === "sleep_total_min" ? `${Math.floor(v / 60)}h${Math.round(v % 60)}m` : String(Math.round(v));

function hhmm(iso: string): string {
  const t = iso.length >= 16 ? iso.slice(11, 16) : iso.slice(11, 13) + ":00";
  return t;
}

export function ForecastCard() {
  const q = useQuery({ queryKey: ["forecast"], queryFn: api.forecast });
  if (q.isLoading || !q.data) {
    return (
      <section className="rounded-2xl bg-slate-900/40 p-4">
        <span className="text-xs text-slate-500">未来予測を計算中…</span>
      </section>
    );
  }
  const f = q.data;
  const tomorrow = Object.values(f.tomorrow) as ImputedMetric[];

  return (
    <section className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-center gap-1.5">
        <TrendingUp size={14} className="text-sky-300" />
        <span className="text-xs uppercase tracking-wider text-slate-400">未来予測</span>
        <span className="ml-auto text-[10px] text-slate-600">確度で濃淡</span>
      </div>

      {/* 【高】片頭痛リスク予報 */}
      {f.migraine && (
        <div className={`rounded-xl border border-rose-500/20 bg-rose-500/[0.05] p-2.5 ${OPACITY[f.migraine.confidence]}`}>
          <div className="mb-1 flex items-center gap-1.5">
            <CloudRain size={12} className="text-rose-300" />
            <span className="text-[11px] font-semibold text-rose-200">片頭痛リスク予報 (48h)</span>
            <span className="ml-auto text-[9px] text-slate-500">{CONF_LABEL[f.migraine.confidence]}</span>
          </div>
          <p className="text-[12px] text-slate-200">
            ピーク: <span className={`font-semibold ${RISK[f.migraine.peak.risk].cls}`}>{f.migraine.peak.label} リスク{RISK[f.migraine.peak.risk].text}</span>
            <span className="ml-1 text-[10px] text-slate-400">(気圧変動 {f.migraine.peak.swing_hpa}hPa)</span>
          </p>
          <div className="mt-1.5 flex gap-1">
            {f.migraine.buckets.map((b) => (
              <div key={b.start} className="flex-1 rounded bg-slate-900/60 px-1 py-1 text-center">
                <div className="text-[8px] text-slate-500">{b.label}</div>
                <div className="my-0.5 h-1.5 rounded-full" style={{ background: RISK[b.risk].dot }} />
                <div className="text-[8px] tabular-nums text-slate-500">{b.swing_hpa}</div>
              </div>
            ))}
          </div>
          {!f.migraine.is_trigger_validated && (
            <p className="mt-1 text-[9px] text-slate-500">※気圧トリガー未確立のため一般基準で判定（薄め）</p>
          )}
        </div>
      )}

      {/* 【中】今日この先のエネルギー */}
      {f.energy_today && (
        <div className={`rounded-xl bg-slate-900/60 p-2.5 ${OPACITY[f.energy_today.confidence]}`}>
          <div className="mb-1 flex items-center gap-1.5">
            <BatteryLow size={12} className="text-amber-300" />
            <span className="text-[11px] font-semibold text-amber-200">エネルギー推移 (今日)</span>
            <span className="ml-auto text-[9px] text-slate-500">{CONF_LABEL[f.energy_today.confidence]}</span>
          </div>
          <p className="text-[12px] text-slate-200">
            現在 Body Battery {f.energy_today.current} · 消耗 {Math.abs(f.energy_today.slope_per_h)}/h
            {f.energy_today.empty_eta ? (
              <span className="ml-1 text-amber-300">→ {hhmm(f.energy_today.empty_eta)}頃に{f.energy_today.floor}を下回る見込み</span>
            ) : (
              <span className="ml-1 text-slate-400">→ 当面は維持の見込み</span>
            )}
          </p>
        </div>
      )}

      {/* 【低】明日の一次指標 (参考・薄い) */}
      {tomorrow.length > 0 && (
        <div className="rounded-xl bg-slate-900/60 p-2.5 opacity-50">
          <div className="mb-1 flex items-center gap-1.5">
            <span className="text-[11px] font-semibold text-slate-300">明日の見通し</span>
            <span className="ml-auto text-[9px] text-slate-500">確度 低（参考・ベイズ天井）</span>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-slate-400">
            {tomorrow.map((it) => (
              <span key={it.metric} className="tabular-nums">
                {TM_LABEL[it.metric] ?? it.metric} <span className="text-slate-200">{tmFmt(it.metric, it.value)}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
