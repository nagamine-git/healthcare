import { useQuery } from "@tanstack/react-query";
import { CloudRain } from "lucide-react";
import { api } from "../lib/api";
import type { ForecastRisk } from "../lib/api";

/**
 * 片頭痛リスク予報を「今日の指針」内に出す 1 行バナー (旧・未来予測カードから移設)。
 * 検証済みトリガー(気圧変動)×48h気圧予報。確度で濃淡。リスク低×低確度なら控えめ。
 */

const RISK: Record<ForecastRisk, { text: string; cls: string; border: string }> = {
  high: { text: "高", cls: "text-rose-200", border: "border-rose-500/30 bg-rose-500/[0.07]" },
  elevated: { text: "やや高", cls: "text-amber-200", border: "border-amber-500/30 bg-amber-500/[0.07]" },
  low: { text: "低", cls: "text-emerald-200/80", border: "border-slate-700/40 bg-slate-800/40" },
};
const OPACITY: Record<string, string> = { high: "opacity-100", medium: "opacity-90", low: "opacity-70" };

export function MigraineRiskBanner() {
  const q = useQuery({ queryKey: ["forecast"], queryFn: api.forecast });
  const m = q.data?.migraine;
  if (!m) return null;
  const r = RISK[m.peak.risk];
  return (
    <div className={`flex items-center gap-2 rounded-xl border px-3 py-2 ${r.border} ${OPACITY[m.confidence]}`}>
      <CloudRain size={14} className="shrink-0 text-rose-300" />
      <span className="min-w-0 flex-1 truncate text-[12px] text-slate-200">
        片頭痛リスク予報: <span className={`font-semibold ${r.cls}`}>{m.peak.label} {r.text}</span>
        <span className="ml-1 text-[10px] text-slate-400">気圧変動 {m.peak.swing_hpa}hPa</span>
      </span>
      <span className="shrink-0 text-[9px] text-slate-500">
        {m.confidence === "high" ? "確度高" : m.confidence === "medium" ? "確度中" : "確度低"}
        {!m.is_trigger_validated ? "・一般基準" : ""}
      </span>
    </div>
  );
}
