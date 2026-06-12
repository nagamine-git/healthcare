import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Armchair, Check, Footprints, Activity, Moon, Flame, Brain, Coffee } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import type { DayStorySegment, DayStoryInsight } from "../lib/api";

type Win = "day" | "24h";

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
// 心拍は 45-165bpm をトラック高さにマップ (安静〜運動域)
const hrY = (bpm: number) => BODY_Y1 - (Math.max(0, Math.min(1, (bpm - 45) / 120)) * BODY_H);

function colorFor(seg: DayStorySegment): string {
  if (seg.source === "sleep") return "#6366f1";
  if (seg.source === "calendar") return "#64748b";
  if (seg.source === "workout") return "#34d399";
  const l = seg.label;
  if (l.includes("記録の谷間")) return "#334155";
  if (l.includes("外出") || l.includes("移動")) return "#38bdf8";
  if (l.includes("家事")) return "#22d3ee"; // 家事・育児など = シアン
  if (l.includes("集中") || l.includes("負荷") || l.includes("緊張")) return "#f59e0b";
  if (l.includes("休息") || l.includes("リラックス") || l.includes("ゆったり") || l.includes("在席")) return "#2dd4bf";
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
    .replace("・座位", "").replace(" (高め)", "").replace("・活動", "")
    .replace("・リラックス", "").replace("・歩き回り", "").replace("・ゆったり", "")
    .replace("・緊張", "").replace("など", "");
}

type Zoom = "fit" | "wide" | "max";
// fit=画面幅, wide≈1.5倍, max≈2倍 (画面幅 ~390px 基準)
const ZOOM_PX: Record<Zoom, number | null> = { fit: null, wide: 580, max: 760 };

// 表示設定は端末に記憶 (リロードしても前回の選択を維持)
function usePersisted<T extends string>(key: string, fallback: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try { return (localStorage.getItem(key) as T) || fallback; } catch { return fallback; }
  });
  const set = (nv: T) => { setV(nv); try { localStorage.setItem(key, nv); } catch { /* noop */ } };
  return [v, set];
}

export function DayStory() {
  const [win, setWin] = usePersisted<Win>("daystory.win", "24h");
  const [zoom, setZoom] = usePersisted<Zoom>("daystory.zoom", "fit");
  const story = useQuery({ queryKey: ["day-story", win], queryFn: () => api.dayStory({ window: win }), refetchInterval: 5 * 60_000 });
  const tl = useQuery({ queryKey: ["timeline", win], queryFn: () => api.timeline({ window: win }), refetchInterval: 5 * 60_000 });
  const d = story.data;
  const t = tl.data;

  // 軸ラベル: origin からの offset を実時刻に変換 (24hビューは日付をまたぐため)
  const originHour = d ? new Date(d.origin_jst).getHours() : 0;
  const axisLabel = (offset: number) => `${(originHour + offset) % 24}時`;

  const toggle = (
    <div className="flex rounded-lg bg-slate-800/70 p-0.5 text-[11px]">
      {(["24h", "day"] as Win[]).map((w) => (
        <button key={w} onClick={() => setWin(w)}
          className={`rounded-md px-2.5 py-0.5 ${win === w ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>
          {w === "24h" ? "直近24h" : "今日"}
        </button>
      ))}
    </div>
  );

  if (story.isLoading || !d || d.segments.length === 0) {
    return (
      <div className="space-y-2 rounded-2xl bg-slate-900/40 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-400">{story.isLoading ? "読み込み中..." : "まだデータがありません"}</span>
          {toggle}
        </div>
      </div>
    );
  }

  const nowH = d.now_h;
  const bb = t?.body_battery ?? [];
  const stress = t?.stress ?? [];
  const hr = t?.heart_rate ?? [];
  const hrPts = hr.map((p) => `${X(p.h)},${hrY(p.v)}`).join(" ");
  const bbArea =
    bb.length > 1
      ? `M ${X(bb[0].h)},${BODY_Y1} L ${bb.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" L ")} L ${X(bb[bb.length - 1].h)},${BODY_Y1} Z`
      : null;
  const stressPts = stress.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" ");
  // 拡大するほど狭い帯にもラベルを出せる (viewBox幅基準の閾値を下げる)
  const labelMinW = zoom === "fit" ? 52 : zoom === "wide" ? 42 : 34;

  return (
    <div className="space-y-3 rounded-2xl bg-slate-900/40 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-base font-medium leading-snug text-slate-100">{d.summary}</p>
        {toggle}
      </div>

      {/* クイック統計チップ (1日の数値サマリ) */}
      <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        <Stat icon={Footprints} label="歩数" value={d.stats.steps.toLocaleString()} />
        <Stat icon={Flame} label="消費" value={`${d.stats.active_kcal}kcal`} />
        <Stat icon={Moon} label="睡眠" value={d.stats.sleep_h != null ? `${d.stats.sleep_h}h` : "--"} />
        <Stat icon={Activity} label="運動強度" value={`${d.stats.intensity_min}分`} />
        <Stat icon={Brain} label="平均覚醒" value={d.stats.stress_avg != null ? `${d.stats.stress_avg}` : "--"} />
        <Stat icon={Coffee} label="カフェイン" value={`${d.stats.caffeine_mg}mg`} />
      </div>

      {/* 拡大すると横スクロールで各時間に幅が割かれ、帯内ラベル・軸が読める */}
      <div className={ZOOM_PX[zoom] != null ? "-mx-1 overflow-x-auto px-1" : ""}>
        <svg
          viewBox={`0 0 ${W} ${TOTAL_H}`}
          className={ZOOM_PX[zoom] == null ? "w-full" : ""}
          style={ZOOM_PX[zoom] != null ? { width: `${ZOOM_PX[zoom]}px` } : undefined}
          role="img"
          aria-label="今日のタイムライン"
        >
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
              {w >= labelMinW && seg.label !== "記録の谷間" && (
                <text x={x + w / 2} y={ACT_Y + ACT_H / 2 + 4} fontSize={12} fontWeight={600}
                      fill="#0f172a" textAnchor="middle" pointerEvents="none">{label}</text>
              )}
            </g>
          );
        })}

        {/* ── カレンダー予定 = 参考のみ (破線オーバーレイ。実際の行動とは別物) ── */}
        {(t?.events ?? []).map((e, i) => {
          const x = X(e.start_h);
          const w = Math.max(3, X(e.end_h) - x);
          return (
            <rect key={`ev${i}`} x={x + 0.5} y={ACT_Y + 0.5} width={w - 1} height={ACT_H - 1}
                  rx={3} fill="none" stroke="#94a3b8" strokeWidth={1} strokeDasharray="3 2" opacity={0.55}>
              <title>{`予定(参考): ${e.title}`}</title>
            </rect>
          );
        })}

        {/* ── 頭痛バンド (全トラック貫通、ロゼ) ── */}
        {(t?.migraine ?? []).map((m, i) => (
          <rect key={`mig${i}`} x={X(m.start_h)} y={ACT_Y}
                width={Math.max(3, X(m.end_h ?? nowH ?? 24) - X(m.start_h))}
                height={BODY_Y1 - ACT_Y} fill="#f43f5e" opacity={0.13}>
            <title>{`頭痛${m.severity != null ? ` 強度${m.severity}/10` : ""}`}</title>
          </rect>
        ))}

        {/* ── イベントマーカー行 ── */}
        {(t?.caffeine ?? []).map((c, i) => (
          <g key={`c${i}`} transform={`translate(${X(c.h)},${EVT_Y})`}>
            <circle r={4} fill="#a78bfa">
              <title>{`カフェイン ${Math.round(c.mg)}mg (${c.source})`}</title>
            </circle>
          </g>
        ))}
        {/* 体調記録: 実入力=塗り◆、無ければ推定=中空◇ を現在位置に補完 */}
        {t?.checkin ? (
          <g transform={`translate(${X(t.checkin.h)},${EVT_Y})`}>
            <rect x={-4} y={-4} width={8} height={8} transform="rotate(45)" fill="#e2e8f0">
              <title>{`体調記録 気分${t.checkin.mood ?? "-"}/活力${t.checkin.energy ?? "-"}/ストレス${t.checkin.stress ?? "-"}/筋肉痛${t.checkin.soreness ?? "-"}`}</title>
            </rect>
          </g>
        ) : t?.checkin_estimated && nowH != null ? (
          <g transform={`translate(${X(nowH)},${EVT_Y})`}>
            <rect x={-4} y={-4} width={8} height={8} transform="rotate(45)"
                  fill="none" stroke="#94a3b8" strokeWidth={1.2} opacity={0.8}>
              <title>{`体調(推定) 気分${t.checkin_estimated.mood ?? "-"}/活力${t.checkin_estimated.energy ?? "-"}/ストレス${t.checkin_estimated.stress ?? "-"}/筋肉痛${t.checkin_estimated.soreness ?? "-"}`}</title>
            </rect>
          </g>
        ) : null}

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
        {hr.length > 1 && (
          <polyline points={hrPts} fill="none" stroke="#fb7185" strokeWidth={1.1} opacity={0.7} />
        )}

        {/* 現在線 (全トラック貫通) */}
        {nowH != null && (
          <g>
            <line x1={X(nowH)} y1={ACT_Y} x2={X(nowH)} y2={BODY_Y1} stroke="#f43f5e" strokeWidth={1.5} />
            <circle cx={X(nowH)} cy={ACT_Y} r={3} fill="#f43f5e" />
          </g>
        )}

        {/* 時刻軸 (低不透明度)。24hビューは origin からの実時刻 */}
        {[0, 6, 12, 18, 24].map((h) => (
          <text key={h} x={X(h)} y={AXIS_Y} fontSize={11} fill="#64748b"
                textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"}>{axisLabel(h)}</text>
        ))}
        </svg>
      </div>

      {/* 行動カラー凡例 (帯の色が何を意味するか) */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-400">
        <Swatch c="#6366f1" t="睡眠" />
        <Swatch c="#f59e0b" t="集中・活動" />
        <Swatch c="#22d3ee" t="家事・育児など" />
        <Swatch c="#2dd4bf" t="休息・在席" />
        <Swatch c="#38bdf8" t="移動・運動" />
        <Swatch c="#34d399" t="ワークアウト" />
        <Swatch c="#334155" t="記録なし" />
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-3 rounded-sm border border-dashed border-slate-400" />
          予定(参考のみ)
        </span>
      </div>

      {/* 線/点の凡例 + 拡大コントロール */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500">
          <span><span className="text-emerald-400">━</span> Body Battery</span>
          <span><span className="text-amber-400">━</span> ストレス(覚醒)</span>
          <span><span className="text-rose-400">━</span> 心拍</span>
          <span><span className="text-violet-400">●</span> カフェイン</span>
          <span><span className="text-rose-400">▮</span> 頭痛</span>
          <span><span className="text-slate-200">◆</span> 体調記録 / <span className="text-slate-400">◇</span> 推定</span>
          <span className="text-slate-600">帯: 濃=記録 / 淡=推定</span>
        </div>
        <div className="flex rounded-lg bg-slate-800/70 p-0.5 text-[10px]">
          {(["fit", "wide", "max"] as Zoom[]).map((z) => (
            <button key={z} onClick={() => setZoom(z)}
              className={`rounded-md px-2 py-0.5 ${zoom === z ? "bg-slate-600 text-slate-100" : "text-slate-400"}`}>
              {z === "fit" ? "フィット" : z === "wide" ? "1.5倍" : "2倍"}
            </button>
          ))}
        </div>
      </div>
      {zoom !== "fit" && (
        <p className="text-[10px] text-slate-600">← 横にスクロールできます →</p>
      )}

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

function Stat({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg bg-slate-900/60 px-2 py-1.5">
      <Icon size={13} className="shrink-0 text-slate-500" />
      <div className="min-w-0 leading-tight">
        <div className="truncate text-[9px] text-slate-500">{label}</div>
        <div className="truncate text-xs font-medium tabular-nums text-slate-200">{value}</div>
      </div>
    </div>
  );
}

function Swatch({ c, t }: { c: string; t: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: c }} />
      {t}
    </span>
  );
}
