import { useQuery } from "@tanstack/react-query";
import { CloudRain } from "lucide-react";
import { api } from "../lib/api";

/**
 * 片頭痛リスクを「今日の指針」内の 1 枚に集約するバナー。
 * 気圧予報(48h) × 今アクティブな個人トリガー × 発症時刻プロファイルを統合し、
 * リスク高のときは対処アクションも出す。旧『気圧降下×頭痛多発期』アラートを統合済み。
 * リスク要因が何も無ければ非表示 (狼少年回避)。
 */
export function MigraineRiskBanner() {
  const q = useQuery({ queryKey: ["forecast"], queryFn: api.forecast });
  const m = q.data?.migraine;
  if (!m) return null;

  const active = m.active_triggers ?? [];
  const hasPressure = !!(m.peak && m.confidence);
  // 何も要因が無ければ出さない (バックエンドでも保証しているが UI 側でも二重に安全に)
  if (!hasPressure && active.length === 0) return null;

  const isHigh =
    m.level === "high" || active.some((t) => t.level === "high") || m.peak?.risk === "high";
  const border = isHigh
    ? "border-rose-500/30 bg-rose-500/[0.07]"
    : "border-amber-500/30 bg-amber-500/[0.07]";
  const accent = isHigh ? "text-rose-200" : "text-amber-200";

  // 主因: 気圧 + 今まさに誘発域にある個人トリガー
  const causes: string[] = [];
  if (hasPressure) causes.push(`気圧変動 ${m.peak!.swing_hpa}hPa`);
  active.forEach((t) => causes.push(`${t.label}が今多い`));

  // 発症しやすい時間帯 (過去の発症時刻プロファイル)
  const o = m.likely_onset;
  const onsetText = o
    ? o.passed
      ? `発症しやすいのは${o.peak_bucket ?? `${o.clock}頃`}(今日のピークは過ぎ気味)`
      : `${o.clock}頃${o.hours_from_now != null ? `(あと約${o.hours_from_now}h)` : ""}に出やすい`
    : null;

  // 気圧が「何時間後から」誘発域に入るか
  const pressureWhen = hasPressure
    ? m.onset_in_hours != null
      ? m.onset_in_hours <= 0
        ? "気圧はまもなく変動"
        : `気圧は約${m.onset_in_hours}時間後${m.onset_label ? `(${m.onset_label})` : ""}から`
      : `気圧は${m.peak!.label}にピーク`
    : null;

  const whenLine = [onsetText, pressureWhen].filter(Boolean).join(" / ");

  // 右上の文脈バッジ: 直近30日の発作数 + (気圧予報があれば)確度
  const badge = [
    m.recent_count != null && m.recent_count > 0 ? `30日${m.recent_count}回` : null,
    hasPressure
      ? m.confidence === "high"
        ? "確度高"
        : m.confidence === "medium"
          ? "確度中"
          : "確度低"
      : null,
  ]
    .filter(Boolean)
    .join("・");

  return (
    <div className={`flex flex-col gap-0.5 rounded-xl border px-3 py-2 ${border}`}>
      <div className="flex items-center gap-2">
        <CloudRain size={14} className="shrink-0 text-rose-300" />
        <span className="min-w-0 flex-1 text-[12px] text-slate-200">
          片頭痛リスク{isHigh ? "高" : "やや高"}:{" "}
          <span className={`font-semibold ${accent}`}>{causes.join("・")}</span>
        </span>
        {badge && <span className="shrink-0 text-[9px] text-slate-500">{badge}</span>}
      </div>
      {whenLine && <div className="pl-6 text-[10px] text-rose-200/80">⏰ {whenLine}</div>}
      {m.actions && m.actions.length > 0 && (
        <div className="pl-6 text-[10px] text-slate-300/90">💊 {m.actions.join("・")}</div>
      )}
    </div>
  );
}
