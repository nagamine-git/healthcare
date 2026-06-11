import { useQuery } from "@tanstack/react-query";
import { Armchair, Check, Footprints, Activity } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import type { DayStorySegment, DayStoryInsight } from "../lib/api";

/**
 * 今日のあらすじ: 取れる全データを「同一時間軸の縦スタック」で見せる統合パネル。
 *   1行サマリ
 *   ├ 行動トラック   : 何をしていたか (推定/記録)
 *   ├ イベント       : カフェイン・運動・頭痛・チェックイン
 *   ├ 身体反応トラック: Body Battery (面) + ストレス (線)
 *   └ 気づき + 次の一手
 * 全トラックが横軸=時刻を完全共有し、縦に読むと「その時刻に何をして体がどう
 * 反応したか」が分かる (研究: 別々のチャートでなく共通軸への整列が最重要)。
 */

// ---- レイアウト (viewBox 座標) ----
const W = 960;
const PER_H = W / 24;
const X = (h: number) => Math.max(0, Math.min(24, h)) * PER_H;
const ACT_Y = 2;
const ACT_H = 30;
const EVT_Y = 38; // イベントマーカー行の中心
const BODY_Y0 = 50; // 身体反応トラック上端
const BODY_H = 64;
const BODY_Y1 = BODY_Y0 + BODY_H;
const AXIS_Y = BODY_Y1 + 14;
const TOTAL_H = AXIS_Y + 4;
const bodyY = (v: number) => BODY_Y1 - (Math.max(0, Math.min(100, v)) / 100) * BODY_H;

function colorFor(seg: DayStorySegment): string {
  if (seg.source === "sleep") return "#6366f1";
  if (seg.source === "calendar") return "#64748b";
  if (seg.source === "workout") return "#34d399";
  const l = seg.label;
  if (l.includes("記録の谷間")) return "#334155";
  if (l.includes("外出") || l.includes("移動")) return "#38bdf8";
  if (l.includes("集中") || l.includes("仕事") || l.includes("ストレス") || l.includes("負荷")) return "#f59e0b";
  if (l.includes("休息") || l.includes("リラックス") || l.includes("ゆったり")) return "#2dd4bf";
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

function shortLabel(seg: DayStorySegment): string {
  if (seg.source === "calendar") return seg.label.length > 7 ? seg.label.slice(0, 6) + "…" : seg.label;
  return seg.label
    .replace("・座位", "").replace("・軽活動", "").replace("・集中", "")
    .replace("・リラックス", "").replace("・負荷高め", "").replace(" (負荷高め)", "")
    .replace("・歩き回り", "").replace("・ゆったり", "").replace("・負荷", "");
}

export function DayStory() {
  const story = useQuery({ queryKey: ["day-story"], queryFn: () => api.dayStory(), refetchInterval: 5 * 60_000 });
  const tl = useQuery({ queryKey: ["timeline"], queryFn: () => api.timeline(), refetchInterval: 5 * 60_000 });
  const d = story.data;
  if (story.isLoading || !d || d.segments.length === 0) return null;
  const t = tl.data;

  const nowH = d.now_h;
  const bb = t?.body_battery ?? [];
  const stress = t?.stress ?? [];
  const bbArea =
    bb.length > 1
      ? `M ${X(bb[0].h)},${BODY_Y1} L ${bb.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" L ")} L ${X(bb[bb.length - 1].h)},${BODY_Y1} Z`
      : null;
  const stressPts = stress.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" ");

  return (
    <div className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <p className="text-base font-medium leading-snug text-slate-100">{d.summary}</p>

      <svg viewBox={`0 0 ${W} ${TOTAL_H}`} className="w-full" role="img" aria-label="今日のタイムライン">
        {/* 3hグリッド (全トラック貫通) */}
        {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
          <line key={h} x1={X(h)} y1={ACT_Y} x2={X(h)} y2={BODY_Y1}
                stroke="#1e293b" strokeWidth={h % 6 === 0 ? 1 : 0.5} />
        ))}

        {/* ── 行動トラック ── */}
        {d.segments.map((seg, i) => {
          const x = X(seg.start_h);
          const w = Math.max(1, X(seg.end_h) - x);
          const op = seg.source === "inferred" ? 0.4 + seg.confidence * 0.45 : 0.95;
          const label = shortLabel(seg);
          return (
            <g key={i}>
              <rect x={x} y={ACT_Y} width={w} height={ACT_H} rx={3} fill={colorFor(seg)} opacity={op}>
                <title>{`${fmtH(seg.start_h)}–${fmtH(seg.end_h)} ${seg.label} (${SOURCE_NOTE[seg.source]})`}</title>
              </rect>
              {w >= 52 && seg.label !== "記録の谷間" && (
                <text x={x + w / 2} y={ACT_Y + ACT_H / 2 + 4} fontSize={12} fontWeight={600}
                      fill="#0f172a" textAnchor="middle" pointerEvents="none">{label}</text>
              )}
            </g>
          );
        })}

        {/* ── イベントマーカー行 ── */}
        {(t?.caffeine ?? []).map((c, i) => (
          <g key={`c${i}`} transform={`translate(${X(c.h)},${EVT_Y})`}>
            <circle r={4} fill="#a78bfa">
              <title>{`カフェイン ${Math.round(c.mg)}mg (${c.source})`}</title>
            </circle>
          </g>
        ))}
        {t?.checkin && (
          <g transform={`translate(${X(t.checkin.h)},${EVT_Y})`}>
            <rect x={-3.5} y={-3.5} width={7} height={7} transform="rotate(45)" fill="#e2e8f0">
              <title>{`チェックイン 気分${t.checkin.mood ?? "-"}/活力${t.checkin.energy ?? "-"}`}</title>
            </rect>
          </g>
        )}

        {/* ── 身体反応トラック (Body Battery 面 + ストレス線) ── */}
        <line x1={0} y1={BODY_Y1} x2={W} y2={BODY_Y1} stroke="#1e293b" strokeWidth={1} />
        {bbArea && <path d={bbArea} fill="#34d399" opacity={0.16} />}
        {bb.length > 1 && (
          <polyline points={bb.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" ")}
                    fill="none" stroke="#34d399" strokeWidth={2} strokeLinejoin="round" />
        )}
        {stress.length > 1 && (
          <polyline points={stressPts} fill="none" stroke="#f59e0b" strokeWidth={1.2} opacity={0.8} />
        )}

        {/* 現在線 (全トラック貫通) */}
        {nowH != null && (
          <g>
            <line x1={X(nowH)} y1={ACT_Y} x2={X(nowH)} y2={BODY_Y1} stroke="#f43f5e" strokeWidth={1.5} />
            <circle cx={X(nowH)} cy={ACT_Y} r={3} fill="#f43f5e" />
          </g>
        )}

        {/* 時刻軸 (低不透明度) */}
        {[0, 6, 12, 18, 24].map((h) => (
          <text key={h} x={X(h)} y={AXIS_Y} fontSize={11} fill="#64748b"
                textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"}>{h}時</text>
        ))}
      </svg>

      {/* 凡例 */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500">
        <span><span className="text-emerald-400">━</span> Body Battery</span>
        <span><span className="text-amber-400">━</span> ストレス(覚醒)</span>
        <span><span className="text-violet-400">●</span> カフェイン</span>
        <span className="text-slate-600">濃=記録 / 淡=推定</span>
      </div>

      {/* 気づき + 次の一手 */}
      {d.insights.length > 0 && (
        <div className="space-y-1.5 pt-1">
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
    </div>
  );
}
