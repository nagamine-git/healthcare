import { useEffect, useState } from "react";

/** "X 分前" 等の相対時刻表記。null/undefined は "—"。 */
export function relativeMinutes(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diffMs = now - t;
  if (diffMs < 0) return "これから";
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return "たった今";
  if (min < 60) return `${min} 分前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 時間前`;
  const d = Math.floor(h / 24);
  return `${d} 日前`;
}

/** 1 分ごとに「現在時刻」を更新するフック。相対表記の自動リフレッシュ用。 */
export function useTickingNow(intervalMs = 30_000): number {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
