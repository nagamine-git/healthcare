import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { api } from "../lib/api";

/**
 * 今日の指針付近に出す、さりげない予測文。
 * 予測可能な系列 (カフェイン消失時刻・気圧3h予報・集中ピーク窓) を 1 行で。
 */
export function DayPrediction() {
  const q = useQuery({
    queryKey: ["timeline", "24h"],
    queryFn: () => api.timeline({ window: "24h" }),
    refetchInterval: 5 * 60_000,
  });
  const text = q.data?.prediction_text;
  if (!text) return null;
  return (
    <div className="flex items-start gap-1.5 px-1 text-[11px] text-ink-faint">
      <TrendingUp size={12} className="mt-0.5 shrink-0 text-info/70" />
      <span>
        <span className="text-ink-dim">この先の予測</span> · {text}
      </span>
    </div>
  );
}
