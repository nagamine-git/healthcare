import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { DayStorySegment } from "../lib/api";

/**
 * 今日のあらすじ: 取れる全データから「その時間に何をしていたか」を推定し、
 * 1行サマリ + 24時間の行動バーで見せる。確定情報 (睡眠/運動/予定) は濃く、
 * 生理データからの推定は淡く (確度を透明度で表現)。
 */

// ラベル系統 → 色 (前方一致でマッチ。予定タイトルは既定色)
function colorFor(seg: DayStorySegment): string {
  if (seg.source === "sleep") return "#6366f1"; // indigo
  if (seg.source === "calendar") return "#64748b"; // slate
  if (seg.source === "workout") return "#34d399"; // emerald
  const l = seg.label;
  if (l.includes("外出") || l.includes("移動")) return "#38bdf8"; // sky
  if (l.includes("集中") || l.includes("デスクワーク")) return "#f59e0b"; // amber
  if (l.includes("休息") || l.includes("リラックス")) return "#2dd4bf"; // teal
  return "#475569"; // 安静・座位 など
}

const SOURCE_NOTE: Record<DayStorySegment["source"], string> = {
  sleep: "記録",
  workout: "記録",
  calendar: "予定",
  inferred: "推定",
};

function fmtH(h: number): string {
  const hh = Math.floor(h);
  const mm = Math.round((h - hh) * 60);
  return `${hh}:${mm.toString().padStart(2, "0")}`;
}

export function DayStory() {
  const q = useQuery({
    queryKey: ["day-story"],
    queryFn: () => api.dayStory(),
    refetchInterval: 5 * 60_000,
  });
  const d = q.data;
  if (q.isLoading) return null;
  if (!d || d.segments.length === 0) return null;

  const W = 960;
  const X = (h: number) => Math.max(0, Math.min(24, h)) * 40;

  return (
    <div className="rounded-2xl bg-slate-900/40 p-4">
      {/* 一言サマリ (主役) */}
      <p className="mb-3 text-base font-medium leading-snug text-slate-100">{d.summary}</p>

      {/* 24時間 行動バー */}
      <svg viewBox={`0 0 ${W} 44`} className="w-full" role="img" aria-label="今日の行動推定">
        {d.segments.map((seg, i) => {
          const x = X(seg.start_h);
          const w = Math.max(1, X(seg.end_h) - x);
          // 推定は確度で不透明度を変える (確定は濃く)
          const op = seg.source === "inferred" ? 0.35 + seg.confidence * 0.4 : 0.92;
          return (
            <g key={i}>
              <rect x={x} y={6} width={w} height={20} rx={2} fill={colorFor(seg)} opacity={op}>
                <title>{`${fmtH(seg.start_h)}–${fmtH(seg.end_h)} ${seg.label} (${SOURCE_NOTE[seg.source]})`}</title>
              </rect>
            </g>
          );
        })}
        {/* 現在線 */}
        {d.now_h != null && (
          <line x1={X(d.now_h)} y1={2} x2={X(d.now_h)} y2={30} stroke="#f43f5e" strokeWidth={1.5} />
        )}
        {/* 時間目盛 */}
        {[0, 6, 12, 18, 24].map((h) => (
          <text key={h} x={X(h)} y={40} fontSize={11} fill="#64748b"
                textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"}>
            {h}
          </text>
        ))}
      </svg>

      <p className="mt-1 text-[10px] text-slate-500">
        濃い帯＝記録 (睡眠・運動・予定) / 淡い帯＝心拍・歩数・ストレスからの推定。タップで詳細
      </p>
    </div>
  );
}
