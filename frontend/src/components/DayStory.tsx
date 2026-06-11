import { useQuery } from "@tanstack/react-query";
import { Armchair, Check, Footprints, Activity } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import type { DayStorySegment, DayStoryInsight } from "../lib/api";

/**
 * 今日のあらすじ: 取れる全データから「その時間に何をしていたか」を推定し、
 * 1行サマリ + 24時間の行動バー + 「次にやること」付きの気づきで見せる。
 * 確定情報 (睡眠/運動/予定) は濃く、生理データからの推定は淡く (確度=不透明度)。
 */

function colorFor(seg: DayStorySegment): string {
  if (seg.source === "sleep") return "#6366f1";
  if (seg.source === "calendar") return "#64748b";
  if (seg.source === "workout") return "#34d399";
  const l = seg.label;
  if (l.includes("外出") || l.includes("移動")) return "#38bdf8";
  if (l.includes("集中") || l.includes("デスクワーク")) return "#f59e0b";
  if (l.includes("休息") || l.includes("リラックス")) return "#2dd4bf";
  return "#64748b";
}

const SOURCE_NOTE: Record<DayStorySegment["source"], string> = {
  sleep: "記録", workout: "記録", calendar: "予定", inferred: "推定",
};

const INSIGHT_ICON: Record<DayStoryInsight["icon"], LucideIcon> = {
  sit: Armchair, run: Activity, walk: Footprints, ok: Check,
};

function fmtH(h: number): string {
  const hh = Math.floor(h);
  const mm = Math.round((h - hh) * 60);
  return `${hh}:${mm.toString().padStart(2, "0")}`;
}

/** 短いラベル (帯の中に収める用) */
function shortLabel(seg: DayStorySegment): string {
  if (seg.source === "calendar") return seg.label.length > 8 ? seg.label.slice(0, 7) + "…" : seg.label;
  return seg.label
    .replace("・座位", "")
    .replace("・軽活動", "")
    .replace("・集中", "")
    .replace("・リラックス", "")
    .replace("・負荷高め", "");
}

export function DayStory() {
  const q = useQuery({
    queryKey: ["day-story"],
    queryFn: () => api.dayStory(),
    refetchInterval: 5 * 60_000,
  });
  const d = q.data;
  if (q.isLoading || !d || d.segments.length === 0) return null;

  const W = 960;
  const BAR_H = 34;
  const X = (h: number) => Math.max(0, Math.min(24, h)) * 40;

  return (
    <div className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      {/* 一言サマリ (主役) */}
      <p className="text-base font-medium leading-snug text-slate-100">{d.summary}</p>

      {/* 24時間 行動バー (帯内ラベル付き) */}
      <svg viewBox={`0 0 ${W} ${BAR_H + 18}`} className="w-full" role="img" aria-label="今日の行動推定">
        {d.segments.map((seg, i) => {
          const x = X(seg.start_h);
          const w = Math.max(1, X(seg.end_h) - x);
          const op = seg.source === "inferred" ? 0.4 + seg.confidence * 0.4 : 0.95;
          const label = shortLabel(seg);
          // 帯幅が十分 (≈45min以上) なら帯内にラベルを描く
          const showLabel = w >= 50;
          return (
            <g key={i}>
              <rect x={x} y={2} width={w} height={BAR_H} rx={3} fill={colorFor(seg)} opacity={op}>
                <title>{`${fmtH(seg.start_h)}–${fmtH(seg.end_h)} ${seg.label} (${SOURCE_NOTE[seg.source]})`}</title>
              </rect>
              {showLabel && (
                <text x={x + w / 2} y={2 + BAR_H / 2 + 4} fontSize={12} fontWeight={600}
                      fill="#0f172a" textAnchor="middle" pointerEvents="none">
                  {label}
                </text>
              )}
            </g>
          );
        })}
        {d.now_h != null && (
          <line x1={X(d.now_h)} y1={0} x2={X(d.now_h)} y2={BAR_H + 4} stroke="#f43f5e" strokeWidth={2} />
        )}
        {[0, 6, 12, 18, 24].map((h) => (
          <text key={h} x={X(h)} y={BAR_H + 16} fontSize={11} fill="#64748b"
                textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"}>
            {h}時
          </text>
        ))}
      </svg>

      {/* 気づき + 次の一手 */}
      {d.insights.length > 0 && (
        <div className="space-y-1.5">
          {d.insights.map((ins, i) => {
            const Icon = INSIGHT_ICON[ins.icon] ?? Check;
            const tone = ins.tone === "good" ? "text-emerald-300" : "text-amber-300";
            return (
              <div key={i} className="flex items-start gap-2 rounded-xl bg-slate-900/60 px-3 py-2">
                <Icon size={16} className={`mt-0.5 shrink-0 ${tone}`} />
                <div className="min-w-0">
                  <div className="text-sm text-slate-200">{ins.text}</div>
                  <div className="text-xs text-slate-400">→ {ins.action}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p className="text-[10px] text-slate-500">
        濃い帯＝記録 (睡眠・運動・予定) / 淡い帯＝心拍・歩数・消費カロリーからの推定。タップで時刻
      </p>
    </div>
  );
}
