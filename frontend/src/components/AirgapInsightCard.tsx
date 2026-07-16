import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

/** Airgap の浪費実測 × 睡眠/HRV の自己内相関 (n=1・相関であり因果ではない)。
 *  データが揃うまでは何も出さない (十分な日数が無いのに気づきを騙らない)。 */
export function AirgapInsightCard() {
  const q = useQuery({ queryKey: ["airgap-insight"], queryFn: api.airgapInsight, retry: false });
  const d = q.data;
  if (!d || !d.available || d.sleep_diff == null) return null;
  // わずかな差 (±3点未満) はノイズと区別がつかないため出さない。
  if (Math.abs(d.sleep_diff) < 3) return null;

  const worse = d.sleep_diff < 0;

  return (
    <section className="space-y-2 rounded-xl bg-hull p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm tracking-wide text-ink-dim">スマホ浪費と睡眠</h2>
        <span className="text-[10px] text-ink-faint">直近{d.days_analyzed}日・自己内比較</span>
      </div>
      <p className="text-sm text-ink">
        浪費が多い日 (平均 {d.high_waste_avg_min}分) は、少ない日 (平均 {d.low_waste_avg_min}分) より
        睡眠スコアが平均{" "}
        <span className={worse ? "text-risk" : "text-prog-300"}>
          {Math.abs(d.sleep_diff)}点{worse ? "低い" : "高い"}
        </span>
        傾向があります。
      </p>
      {d.hrv_diff != null && Math.abs(d.hrv_diff) >= 3 && (
        <p className="text-xs text-ink-dim">
          HRVスコアも{d.hrv_diff < 0 ? "低め" : "高め"} (差 {Math.abs(d.hrv_diff)}点) です。
        </p>
      )}
      <p className="text-[10px] leading-relaxed text-ink-faint">
        あなた自身のデータ内での比較です(他人との比較ではありません)。相関であって因果関係の証明ではなく、
        参考程度に。
      </p>
    </section>
  );
}
