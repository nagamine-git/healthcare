import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Armchair, Check, Footprints, Activity, Moon, Flame, Coffee, Droplet } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import type { DayStorySegment, DayStoryInsight } from "../lib/api";
import { DayDigest } from "./DayDigest";
import { Skeleton } from "./ui/cockpit";
import { P } from "../lib/palette";

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
const SCHED_Y = AXIS_Y + 11; // 今夜の理想スケジュールのアイコン行 (軸の下)
const TOTAL_H = SCHED_Y + 5;
const bodyY = (v: number) => BODY_Y1 - (Math.max(0, Math.min(100, v)) / 100) * BODY_H;

// 以下の行動カテゴリ色 (indigo/cyan/teal/violet 等) は P のトークンには無い色相で、
// 多数の行動カテゴリを同時に見分けられるようにするための意図的な固有色。
// P の 4 色相 (prog/act/risk/info) に寄せると別カテゴリ同士が同色化し区別できなくなるため、
// 暗色前提の背景/文字トークンとは別物として残す (テーマに関わらず彩度・明度が十分で判読可能)。
function colorFor(seg: DayStorySegment): string {
  if (seg.source === "sleep") return "#6366f1";
  if (seg.source === "calendar") return P.inkFaint;
  if (seg.source === "workout") return P.prog300;
  const l = seg.label;
  if (l.includes("記録の谷間")) return P.hairline;
  if (l.includes("外出") || l.includes("移動")) return P.info;
  if (l.includes("家事")) return "#22d3ee"; // 家事・育児など = シアン
  if (l.includes("集中") || l.includes("負荷") || l.includes("緊張")) return P.act;
  if (l.includes("休息") || l.includes("リラックス") || l.includes("ゆったり") || l.includes("在席")) return "#2dd4bf";
  return P.inkFaint;
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

  // 軸ラベルは origin からの実時刻 (24hビューは日付をまたぐため)
  const originHour = d ? new Date(d.origin_jst).getHours() : 0;

  const toggle = (
    <div className="flex rounded-lg bg-panel/70 p-0.5 text-[11px]">
      {(["24h", "day"] as Win[]).map((w) => (
        <button key={w} onClick={() => setWin(w)}
          className={`rounded-md px-2.5 py-0.5 ${win === w ? "bg-ink-faint text-ink" : "text-ink-dim"}`}>
          {w === "24h" ? "直近24h" : "今日"}
        </button>
      ))}
    </div>
  );

  if (story.isLoading) {
    return (
      <div className="space-y-2 rounded-xl border border-hairline bg-hull p-4">
        <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
        <Skeleton className="h-24" />
      </div>
    );
  }
  if (!d || d.segments.length === 0) {
    return (
      <div className="space-y-2 rounded-xl bg-hull/40 p-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-ink-dim">まだデータがありません</span>
          {toggle}
        </div>
      </div>
    );
  }

  const nowH = d.now_h;

  // 今夜の理想スケジュール (夕食/入浴/就寝)。各イベントは推奨「範囲」を持つ。x昇順・未来のみ。
  const SCHED_ICON: Record<string, string> = {
    dinner: "🍽", dinner_cutoff: "🍽", bath: "🛁", bedtime: "🛌", wake: "☀",
    caffeine_cutoff: "☕", dim_light: "🌙",
  };
  // colorFor と同じ理由で固有色を維持 (各予定アイコンを見分けるための固有色相)
  const SCHED_FILL: Record<string, string> = {
    dinner: "#fb923c", bath: "#22d3ee", bedtime: "#818cf8", wake: P.act300,
    caffeine_cutoff: P.act, dim_light: "#6366f1",
  };
  const schedMarks = (t?.schedule ?? [])
    .map((sc) => ({
      key: sc.key, icon: SCHED_ICON[sc.key] ?? "•", fill: SCHED_FILL[sc.key] ?? "#a5b4fc",
      label: sc.label, time: sc.time, h: sc.h, x: X(sc.h),
      xs: X(sc.start_h), xe: X(sc.end_h), endH: sc.end_h,
    }))
    .filter((p) => nowH == null || p.endH >= nowH - 0.3)
    .sort((a, b) => a.x - b.x);

  const bb = t?.body_battery ?? [];
  const stress = t?.stress ?? [];
  const bbArea =
    bb.length > 1
      ? `M ${X(bb[0].h)},${BODY_Y1} L ${bb.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" L ")} L ${X(bb[bb.length - 1].h)},${BODY_Y1} Z`
      : null;
  const stressPts = stress.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" ");
  // 拡大するほど狭い帯にもラベルを出せる (viewBox幅基準の閾値を下げる)
  const labelMinW = zoom === "fit" ? 52 : zoom === "wide" ? 42 : 34;
  // 目盛り間隔: 拡大するほど細かく (fit=3h grid/6h label, wide=1h/2h, max=30m/1h)
  const gridStep = zoom === "fit" ? 3 : zoom === "wide" ? 1 : 0.5;
  const labelStep = zoom === "fit" ? 6 : zoom === "wide" ? 2 : 1;
  const gridTicks = Array.from({ length: Math.round(24 / gridStep) + 1 }, (_, i) => i * gridStep);
  const labelTicks = Array.from({ length: Math.round(24 / labelStep) + 1 }, (_, i) => i * labelStep);
  // 24hビューは origin からの実時刻、30分刻みは ":30" まで出す
  const tickText = (off: number) => {
    const total = (originHour * 60 + off * 60) % (24 * 60);
    const hh = Math.floor(total / 60);
    const mm = Math.round(total % 60);
    return mm === 0 ? `${hh}時` : `${hh}:${mm.toString().padStart(2, "0")}`;
  };

  // 連続「座りっぱなし」区間 (Diaz 2023: 30分超で要中断)。推定の座位系ラベルを連結
  const SEDENTARY = ["安静・座位", "在席", "軽い活動", "集中・活動", "高負荷", "緊張"];
  const isSed = (lbl: string) => SEDENTARY.some((s) => lbl.includes(s));
  const sedRuns: { start_h: number; end_h: number }[] = [];
  for (const seg of d.segments) {
    if (seg.source === "inferred" && isSed(seg.label)) {
      const last = sedRuns[sedRuns.length - 1];
      if (last && Math.abs(last.end_h - seg.start_h) < 0.01) last.end_h = seg.end_h;
      else sedRuns.push({ start_h: seg.start_h, end_h: seg.end_h });
    }
  }
  const longSed = sedRuns.filter((r) => r.end_h - r.start_h >= 0.5);

  return (
    <div className="space-y-3 rounded-xl bg-hull/40 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-base font-medium leading-snug text-ink">{d.summary}</p>
        {toggle}
      </div>

      {/* クイック統計チップ (1日の数値サマリ) */}
      <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        <Stat icon={Footprints} label="歩数" value={d.stats.steps.toLocaleString()} />
        <Stat icon={Flame} label="消費" value={`${d.stats.active_kcal}kcal`} />
        <Stat icon={Moon} label="睡眠" value={d.stats.sleep_h != null ? `${d.stats.sleep_h}h` : "--"} />
        <Stat icon={Activity} label="運動強度" value={`${d.stats.intensity_min}分`} />
        <Stat icon={Coffee} label="カフェイン" value={`${d.stats.caffeine_mg}mg`} />
        <Stat icon={Droplet} label="水分" value={t?.water?.intake_total_ml != null ? `${(t.water.intake_total_ml / 1000).toFixed(1)}L` : "--"} />
      </div>

      {/* 今日のハイライト (時系列ダイジェスト): 何時に何をしたかをグラフと同じ軸で */}
      <DayDigest segments={d.segments} t={t} originJst={d.origin_jst} nowH={d.now_h} />

      {/* 拡大すると横スクロール。メイン+カフェイン+水分を1つの容器に入れ、
          同じ幅・同じグリッド・同じx軸でスクロールが連動する */}
      <div className={ZOOM_PX[zoom] != null ? "-mx-1 space-y-1 overflow-x-auto px-1" : "space-y-1"}>
        <div style={ZOOM_PX[zoom] != null ? { width: `${ZOOM_PX[zoom]}px` } : undefined} className="space-y-1">
        <svg
          viewBox={`0 0 ${W + 12} ${TOTAL_H}`}
          className="w-full"
          role="img"
          aria-label="今日のタイムライン"
        >
        {/* 未来領域 (現在線より右) = これからの「予測」ゾーン。移動・運動の水色と
            混同しないよう中立のスレートで薄く塗る */}
        {nowH != null && nowH < 24 && (
          <>
            <rect x={X(nowH)} y={ACT_Y} width={X(24) - X(nowH)} height={BODY_Y1 - ACT_Y} fill={P.inkFaint} opacity={0.12} />
            <text x={(X(nowH) + X(24)) / 2} y={ACT_Y + 9} fontSize={9} fill={P.inkDim} textAnchor="middle" opacity={0.8}>予測ゾーン</text>
          </>
        )}
        {/* 時間グリッド (拡大で細かく)。整時は濃いめ、半端目盛りは薄く */}
        {gridTicks.map((h) => (
          <line key={h} x1={X(h)} y1={ACT_Y} x2={X(h)} y2={BODY_Y1}
                stroke={P.panel} strokeWidth={Number.isInteger(h) && h % 6 === 0 ? 1 : 0.5}
                opacity={Number.isInteger(h) ? 1 : 0.5} />
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
                      fill={P.hull} textAnchor="middle" pointerEvents="none">{label}</text>
              )}
            </g>
          );
        })}

        {/* ── 座りっぱなし区間 (30分超) を活動バー下端に赤帯で警告 ── */}
        {longSed.map((r, i) => (
          <rect key={`sed${i}`} x={X(r.start_h)} y={ACT_Y + ACT_H - 2}
                width={Math.max(2, X(r.end_h) - X(r.start_h))} height={2.5} fill={P.risk300} opacity={0.9}>
            <title>{`座りっぱなし ${(r.end_h - r.start_h).toFixed(1)}h (30分ごとに立つと良い)`}</title>
          </rect>
        ))}

        {/* ── カレンダー予定 = 参考のみ (破線オーバーレイ。実際の行動とは別物) ── */}
        {(t?.events ?? []).map((e, i) => {
          const x = X(e.start_h);
          const w = Math.max(3, X(e.end_h) - x);
          return (
            <rect key={`ev${i}`} x={x + 0.5} y={ACT_Y + 0.5} width={w - 1} height={ACT_H - 1}
                  rx={3} fill="none" stroke={P.inkDim} strokeWidth={1} strokeDasharray="3 2" opacity={0.55}>
              <title>{`予定(参考): ${e.title}`}</title>
            </rect>
          );
        })}

        {/* ── 頭痛バンド (全トラック貫通、ロゼ) ── */}
        {(t?.migraine ?? []).map((m, i) => (
          <rect key={`mig${i}`} x={X(m.start_h)} y={ACT_Y}
                width={Math.max(3, X(m.end_h ?? nowH ?? 24) - X(m.start_h))}
                height={BODY_Y1 - ACT_Y} fill={P.risk} opacity={0.13}>
            <title>{`頭痛${m.severity != null ? ` 強度${m.severity}/10` : ""}`}</title>
          </rect>
        ))}

        {/* ── イベントマーカー行 ── */}
        {/* violet はカフェイン専用の固有色 (凡例の text-violet-400 と対応、P にトークン無し) */}
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
            <rect x={-4} y={-4} width={8} height={8} transform="rotate(45)" fill={P.ink}>
              <title>{`体調記録 気分${t.checkin.mood ?? "-"}/活力${t.checkin.energy ?? "-"}/ストレス${t.checkin.stress ?? "-"}/筋肉痛${t.checkin.soreness ?? "-"}`}</title>
            </rect>
          </g>
        ) : t?.checkin_estimated && nowH != null ? (
          <g transform={`translate(${X(nowH)},${EVT_Y})`}>
            <rect x={-4} y={-4} width={8} height={8} transform="rotate(45)"
                  fill="none" stroke={P.inkDim} strokeWidth={1.2} opacity={0.8}>
              <title>{`体調(推定) 気分${t.checkin_estimated.mood ?? "-"}/活力${t.checkin_estimated.energy ?? "-"}/ストレス${t.checkin_estimated.stress ?? "-"}/筋肉痛${t.checkin_estimated.soreness ?? "-"}`}</title>
            </rect>
          </g>
        ) : null}

        {/* ── 文脈ウィンドウ (背景レイヤー) ── */}
        {/* 回復ゾーン: 副交感優位 (Garmin安息帯) を身体トラック背景に薄緑 */}
        {(t?.recovery_bands ?? []).map((r, i) => (
          <rect key={`rec${i}`} x={X(r.start_h)} y={BODY_Y0}
                width={Math.max(2, X(r.end_h) - X(r.start_h))} height={BODY_H}
                fill={P.prog300} opacity={0.07}>
            <title>{`回復ゾーン (自律神経が休息モード)`}</title>
          </rect>
        ))}
        {/* 就寝/メラトニン窓: 夜の藍バンド */}
        {t?.sleep_window && (
          <rect x={X(t.sleep_window.melatonin_h)} y={ACT_Y}
                width={Math.max(2, X(t.sleep_window.bedtime_h) - X(t.sleep_window.melatonin_h))}
                height={BODY_Y1 - ACT_Y} fill="#6366f1" opacity={0.08}>
            <title>{`メラトニン上昇〜就寝の窓 (この時間に光を抑えると寝つきやすい)`}</title>
          </rect>
        )}
        {/* 今夜の理想スケジュール: 推奨「範囲」を帯で表現 + 端の点線 + アイコン */}
        {schedMarks.map((m, i) => (
          <g key={`sc${i}`}>
            <rect x={m.xs} y={ACT_Y} width={Math.max(2, m.xe - m.xs)} height={BODY_Y1 - ACT_Y}
                  fill={m.fill} opacity={0.1} rx={2} />
            <line x1={m.xs} y1={ACT_Y} x2={m.xs} y2={AXIS_Y - 2} stroke={m.fill} strokeWidth={0.8}
                  strokeDasharray="2 3" opacity={0.5} />
            <line x1={m.xe} y1={ACT_Y} x2={m.xe} y2={AXIS_Y - 2} stroke={m.fill} strokeWidth={0.8}
                  strokeDasharray="2 3" opacity={0.5} />
            <text x={(m.xs + m.xe) / 2} y={SCHED_Y} fontSize={11} textAnchor="middle">{m.icon}</text>
            <title>{`今夜の予定: ${m.label} ${m.time}`}</title>
          </g>
        ))}
        {/* 集中ピーク窓: 活動バー上端に琥珀の点線 */}
        {(t?.focus_windows ?? []).map((f, i) => (
          <rect key={`fw${i}`} x={X(f.start_h)} y={ACT_Y - 0.5}
                width={Math.max(2, X(f.end_h) - X(f.start_h))} height={ACT_H + 1}
                fill="none" stroke={P.act300} strokeWidth={1.2} strokeDasharray="2 2" opacity={0.7} rx={3}>
            <title>{`集中ピーク窓 (予測スコア${f.score}) — 重い思考タスク向き`}</title>
          </rect>
        ))}

        {/* ── 身体反応トラック (Body Battery 面 + ストレス線) ── */}
        <line x1={0} y1={BODY_Y1} x2={W} y2={BODY_Y1} stroke={P.panel} strokeWidth={1} />
        {bbArea && <path d={bbArea} fill={P.prog300} opacity={0.16} />}
        {bb.length > 1 && (
          <polyline points={bb.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" ")}
                    fill="none" stroke={P.prog300} strokeWidth={2} strokeLinejoin="round" />
        )}
        {/* Body Battery 予測 (最終実測〜未来、破線)。受け渡し点にマーカー */}
        {/* teal は「予測」を実測の P.prog300 と見分けるための固有色 (同色だと実測/予測が区別不能) */}
        {(t?.body_battery_forecast?.length ?? 0) > 1 && (
          <>
            <polyline points={t!.body_battery_forecast!.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" ")}
                      fill="none" stroke="#5eead4" strokeWidth={2} strokeDasharray="4 3" opacity={0.95} strokeLinejoin="round" />
            <circle cx={X(t!.body_battery_forecast![0].h)} cy={bodyY(t!.body_battery_forecast![0].v)} r={2.6} fill="#5eead4" />
          </>
        )}
        {stress.length > 1 && (
          <polyline points={stressPts} fill="none" stroke={P.act} strokeWidth={1.2} opacity={0.8} />
        )}
        {/* ストレス 予測 (最終実測〜未来、破線) */}
        {(t?.stress_forecast?.length ?? 0) > 1 && (
          <>
            <polyline points={t!.stress_forecast!.map((p) => `${X(p.h)},${bodyY(p.v)}`).join(" ")}
                      fill="none" stroke={P.act300} strokeWidth={1.4} strokeDasharray="4 3" strokeLinejoin="round" />
            <circle cx={X(t!.stress_forecast![0].h)} cy={bodyY(t!.stress_forecast![0].v)} r={2.2} fill={P.act300} />
          </>
        )}

        {/* 現在線 (全トラック貫通) */}
        {nowH != null && (
          <g>
            <line x1={X(nowH)} y1={ACT_Y} x2={X(nowH)} y2={BODY_Y1} stroke={P.risk} strokeWidth={1.5} />
            <circle cx={X(nowH)} cy={ACT_Y} r={3} fill={P.risk} />
          </g>
        )}

        {/* 時刻軸 (低不透明度)。拡大で細かく、24hビューは origin からの実時刻 */}
        {labelTicks.map((h) => (
          <text key={h} x={X(h)} y={AXIS_Y} fontSize={10} fill={P.inkFaint}
                textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"}>{tickText(h)}</text>
        ))}
        </svg>

        {/* 今夜の理想スケジュール凡例 (時刻は重ならないようここで読みやすく) */}
        {schedMarks.length > 0 && (
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 px-1 text-[10px] text-indigo-300/80">
            <span className="text-ink-faint">今夜の予定</span>
            {schedMarks.map((m, i) => (
              <span key={i} className="tabular-nums">
                {m.icon} {m.label} <b className="text-indigo-200">{m.time}</b>
              </span>
            ))}
          </div>
        )}

        {/* 心拍・運動レーン (心臓と身体の負荷を別枠で。運動かストレスか見分けやすく) */}
        {t && (t.heart_rate.length > 1 || (t.steps_binned?.length ?? 0) > 0) && (
          <HeartMotionTrack
            hr={t.heart_rate}
            hrForecast={t.heart_rate_forecast ?? []}
            steps={t.steps_binned ?? []}
            restingHr={t.resting_hr}
            nowH={nowH}
            X={X}
            gridTicks={gridTicks}
          />
        )}

        {/* カフェイン・水分も同じ容器内 = 同幅・同グリッド・スクロール連動 */}
        {t && t.caffeine_curve.length > 1 && (
          <CaffeineTrack curve={t.caffeine_curve} threshold={t.caffeine_bedtime_safe_mg}
            floor={t.caffeine_alert_floor_mg} todayMg={t.caffeine_today_mg} dailyLimit={t.caffeine_daily_limit_mg}
            nowH={nowH} X={X} gridTicks={gridTicks} />
        )}
        {t?.water && ((t.water.intake_total_ml ?? 0) > 0 || (t.water.expected_curve?.length ?? 0) > 1) && (
          <WaterTrack water={t.water} nowH={nowH} X={X} gridTicks={gridTicks} />
        )}
        {t && (t.pressure_curve?.length ?? 0) > 1 && (
          <PressureTrack curve={t.pressure_curve} nowH={nowH} X={X} gridTicks={gridTicks} />
        )}

        {/* サブチャート下の共有 x 軸 */}
        {(t?.caffeine_curve.length || t?.water) ? (
          <svg viewBox={`0 0 ${W + 12} 14`} className="w-full" aria-hidden>
            {labelTicks.map((h) => (
              <text key={h} x={X(h)} y={10} fontSize={10} fill={P.inkFaint}
                    textAnchor={h === 0 ? "start" : h === 24 ? "end" : "middle"}>{tickText(h)}</text>
            ))}
          </svg>
        ) : null}
        </div>
      </div>

      {/* 行動カラー凡例 (帯の色が何を意味するか) */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-ink-dim">
        <Swatch c="#6366f1" t="睡眠" />
        <Swatch c={P.act} t="集中・活動" />
        <Swatch c="#22d3ee" t="家事・育児など" />
        <Swatch c="#2dd4bf" t="休息・在席" />
        <Swatch c={P.info} t="移動・運動" />
        <Swatch c={P.prog300} t="ワークアウト" />
        <Swatch c={P.hairline} t="記録なし" />
        <span className="flex items-center gap-1">
          <span className="inline-block h-2.5 w-3 rounded-sm border border-dashed border-ink-dim" />
          予定(参考のみ)
        </span>
      </div>

      {/* 線/点の凡例 + 拡大コントロール */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-ink-faint">
          <span><span className="text-emerald-400">━</span> Body Battery</span>
          <span><span className="text-amber-400">━</span> ストレス(覚醒)</span>
          <span><span className="text-rose-400">━</span> 心拍</span>
          <span><span className="text-sky-400">▮</span> 歩数(運動量)</span>
          <span><span className="text-violet-400">●</span> カフェイン</span>
          <span><span className="text-rose-400">▮</span> 頭痛</span>
          <span><span className="text-red-400">▁</span> 座りっぱなし(30分超)</span>
          <span><span className="text-amber-400">⌑</span> 集中ピーク窓</span>
          <span><span className="text-emerald-400/60">▦</span> 回復ゾーン</span>
          <span><span className="text-indigo-400/60">▦</span> 就寝窓</span>
          <span><span className="text-ink">◆</span> 体調記録 / <span className="text-ink-dim">◇</span> 推定</span>
          <span className="text-ink-faint">帯: 濃=記録 / 淡=推定</span>
        </div>
        <div className="flex rounded-lg bg-panel/70 p-0.5 text-[10px]">
          {(["fit", "wide", "max"] as Zoom[]).map((z) => (
            <button key={z} onClick={() => setZoom(z)}
              className={`rounded-md px-2 py-0.5 ${zoom === z ? "bg-ink-faint text-ink" : "text-ink-dim"}`}>
              {z === "fit" ? "フィット" : z === "wide" ? "1.5倍" : "2倍"}
            </button>
          ))}
        </div>
      </div>
      {zoom !== "fit" && (
        <p className="text-[10px] text-ink-faint">← 横にスクロールできます (全グラフ連動) →</p>
      )}

      {/* 気づき + 次の一手 */}
      {d.insights.length > 0 && (
        <div className="space-y-1.5 pt-1">
          {d.insights.map((ins, i) => {
            const Icon = INSIGHT_ICON[ins.icon] ?? Check;
            const tone = ins.tone === "good" ? "text-prog-300" : "text-act-300";
            return (
              <div key={i} className="flex items-start gap-2 rounded-xl bg-hull/60 px-3 py-2">
                <Icon size={16} className={`mt-0.5 shrink-0 ${tone}`} />
                <div className="min-w-0">
                  <div className="text-sm text-ink">{ins.text}</div>
                  <div className="text-xs text-ink-dim">→ {ins.action}</div>
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
    <div className="flex items-center gap-1.5 rounded-lg bg-hull/60 px-2 py-1.5">
      <Icon size={13} className="shrink-0 text-ink-faint" />
      <div className="min-w-0 leading-tight">
        <div className="truncate text-[9px] text-ink-faint">{label}</div>
        <div className="truncate text-xs font-medium tabular-nums text-ink">{value}</div>
      </div>
    </div>
  );
}

// サブチャート共通の時間グリッド (メインと同じ X・gridTicks で整列)
function SubGrid({ gridTicks, X, y0, y1 }: { gridTicks: number[]; X: (h: number) => number; y0: number; y1: number }) {
  return (
    <>
      {gridTicks.map((h) => (
        <line key={h} x1={X(h)} y1={y0} x2={X(h)} y2={y1} stroke={P.panel}
              strokeWidth={Number.isInteger(h) && h % 6 === 0 ? 1 : 0.5}
              opacity={Number.isInteger(h) ? 1 : 0.5} />
      ))}
    </>
  );
}

const SUB_W = 960;
const SUB_H = 46;

/** 移動平均で心拍をなだらかに (per-minute はスパイクが多い) */
function smooth(pts: { h: number; v: number }[], win = 5): { h: number; v: number }[] {
  if (pts.length <= win) return pts;
  return pts.map((p, i) => {
    const lo = Math.max(0, i - Math.floor(win / 2));
    const hi = Math.min(pts.length, i + Math.ceil(win / 2));
    const slice = pts.slice(lo, hi);
    return { h: p.h, v: slice.reduce((a, q) => a + q.v, 0) / slice.length };
  });
}

function HeartMotionTrack({ hr, hrForecast, steps, restingHr, nowH, X, gridTicks }: {
  hr: { h: number; v: number }[];
  hrForecast?: { h: number; v: number }[];
  steps: { h: number; steps: number }[];
  restingHr: number | null;
  nowH: number | null;
  X: (h: number) => number;
  gridTicks: number[];
}) {
  const H = 52;
  const hrLo = 40, hrHi = 170;
  const y = (bpm: number) => H - 8 - (Math.max(0, Math.min(1, (bpm - hrLo) / (hrHi - hrLo))) * (H - 22));
  const sm = smooth(hr, 7);
  const peakSteps = Math.max(200, ...steps.map((s) => s.steps));
  const barH = (s: number) => (s / peakSteps) * (H - 22);
  const binW = steps.length > 1 ? Math.max(2, X(steps[1].h) - X(steps[0].h)) - 1 : 6;
  const nowBpm = nowH != null && sm.length
    ? sm.reduce((a, p) => (Math.abs(p.h - nowH) < Math.abs(a.h - nowH) ? p : a)).v : (sm.length ? sm[sm.length - 1].v : null);
  return (
    <svg viewBox={`0 0 ${SUB_W + 12} ${H}`} className="w-full" role="img" aria-label="心拍と運動">
      <SubGrid gridTicks={gridTicks} X={X} y0={14} y1={H - 8} />
      {/* 歩数バー (運動量。心拍の背後に薄く) */}
      {steps.map((s, i) => s.steps > 0 && (
        <rect key={i} x={X(s.h) - binW / 2} y={H - 8 - barH(s.steps)} width={binW} height={barH(s.steps)}
              fill={P.info} opacity={0.22}>
          <title>{`${s.steps}歩`}</title>
        </rect>
      ))}
      {/* 安静時心拍の基準線 */}
      {restingHr != null && (
        <line x1={0} y1={y(restingHr)} x2={SUB_W} y2={y(restingHr)} stroke={P.risk} strokeWidth={0.7} strokeDasharray="3 3" opacity={0.45} />
      )}
      {/* 平滑化した心拍 */}
      {sm.length > 1 && (
        <polyline points={sm.map((p) => `${X(p.h)},${y(p.v)}`).join(" ")} fill="none" stroke={P.risk} strokeWidth={1.6} strokeLinejoin="round" />
      )}
      {/* 心拍 予測 (最終実測〜未来、安静へ減衰。破線)。受け渡し点にマーカー */}
      {(hrForecast?.length ?? 0) > 1 && (
        <>
          <polyline points={hrForecast!.map((p) => `${X(p.h)},${y(p.v)}`).join(" ")} fill="none" stroke={P.risk300} strokeWidth={1.8} strokeDasharray="4 3" opacity={0.95} strokeLinejoin="round" />
          <circle cx={X(hrForecast![0].h)} cy={y(hrForecast![0].v)} r={2.4} fill={P.risk300} />
        </>
      )}
      {nowH != null && <line x1={X(nowH)} y1={12} x2={X(nowH)} y2={H - 8} stroke={P.risk} strokeWidth={1} />}
      <text x={4} y={9} fontSize={10} fill={P.inkDim}>
        <tspan fill={P.risk}>━</tspan> 心拍(平滑){nowBpm != null ? `約${Math.round(nowBpm)}` : ""}{restingHr != null ? `/安静${Math.round(restingHr)}` : ""}
        {"  "}<tspan fill={P.info}>▮</tspan> 歩数(動いた量)
      </text>
    </svg>
  );
}

function CaffeineTrack({ curve, threshold, floor, todayMg, dailyLimit, nowH, X, gridTicks }: {
  curve: { h: number; mg: number }[];
  threshold: number | null;
  floor: number | null;
  todayMg: number | null;
  dailyLimit: number | null;
  nowH: number | null;
  X: (h: number) => number;
  gridTicks: number[];
}) {
  const H = SUB_H;
  // 覚醒下限も収まるよう描画レンジを確保
  const peak = Math.max(50, floor ?? 0, ...curve.map((p) => p.mg));
  const y = (mg: number) => H - 8 - (Math.max(0, mg) / peak) * (H - 22);
  const area = `M ${X(curve[0].h)},${H - 8} L ${curve.map((p) => `${X(p.h)},${y(p.mg)}`).join(" L ")} L ${X(curve[curve.length - 1].h)},${H - 8} Z`;
  const nowMg = nowH != null ? curve.reduce((a, p) => (Math.abs(p.h - nowH) < Math.abs(a.h - nowH) ? p : a)).mg : curve[curve.length - 1].mg;
  const over = threshold != null && nowMg > threshold;
  const overLimit = todayMg != null && dailyLimit != null && todayMg > dailyLimit;
  return (
    <svg viewBox={`0 0 ${SUB_W + 12} ${H}`} className="w-full" role="img" aria-label="体内カフェイン量">
      <SubGrid gridTicks={gridTicks} X={X} y0={14} y1={H - 8} />
      {/* 覚醒効果の下限 (1mg/kg, Smith 2002): これ以上残れば効果継続 */}
      {floor != null && floor < peak && (
        <>
          <line x1={0} y1={y(floor)} x2={SUB_W} y2={y(floor)} stroke={P.prog300} strokeWidth={0.8} strokeDasharray="2 3" opacity={0.5} />
          <text x={SUB_W - 4} y={y(floor) - 2} fontSize={8} fill={P.prog300} textAnchor="end" opacity={0.8}>覚醒{Math.round(floor)}</text>
        </>
      )}
      {/* 就寝安全 (0.5mg/L, Drake 2013): これ以下なら睡眠を妨げにくい */}
      {threshold != null && (
        <>
          <line x1={0} y1={y(threshold)} x2={SUB_W} y2={y(threshold)} stroke={P.act} strokeWidth={0.8} strokeDasharray="4 3" opacity={0.6} />
          <text x={SUB_W - 4} y={y(threshold) - 2} fontSize={8} fill={P.act} textAnchor="end" opacity={0.85}>就寝{Math.round(threshold)}</text>
        </>
      )}
      {/* violet はカフェイン専用の固有色 (上のイベントマーカーと同色で統一) */}
      <path d={area} fill="#a78bfa" opacity={0.18} />
      {/* 実測 (現在まで) は実線、未来 (減衰予測) は破線 */}
      {(() => {
        const past = nowH == null ? curve : curve.filter((p) => p.h <= nowH);
        const fut = nowH == null ? [] : curve.filter((p) => p.h >= nowH);
        return (
          <>
            {past.length > 1 && <polyline points={past.map((p) => `${X(p.h)},${y(p.mg)}`).join(" ")} fill="none" stroke="#a78bfa" strokeWidth={1.5} />}
            {fut.length > 1 && <polyline points={fut.map((p) => `${X(p.h)},${y(p.mg)}`).join(" ")} fill="none" stroke="#a78bfa" strokeWidth={1.5} strokeDasharray="3 3" opacity={0.7} />}
          </>
        );
      })()}
      {nowH != null && <line x1={X(nowH)} y1={12} x2={X(nowH)} y2={H - 8} stroke={P.risk} strokeWidth={1} />}
      <text x={4} y={9} fontSize={10} fill={over || overLimit ? P.act300 : P.inkDim}>
        体内カフェイン 現在約{Math.round(nowMg)}mg{todayMg != null && dailyLimit != null ? ` · 本日${todayMg}/${dailyLimit}mg` : ""}
      </text>
    </svg>
  );
}

function WaterTrack({ water, nowH, X, gridTicks }: {
  water: NonNullable<NonNullable<import("../lib/api").DayTimelineData["water"]>>;
  nowH: number | null;
  X: (h: number) => number;
  gridTicks: number[];
}) {
  const H = SUB_H;
  const goal = water.goal_ml ?? 2000;
  const total = water.intake_total_ml ?? 0;
  const peak = Math.max(goal, total, 500);
  const y = (ml: number) => H - 8 - (Math.max(0, ml) / peak) * (H - 22);
  const pts = water.intake_curve.length ? water.intake_curve : [{ h: nowH ?? 24, ml: total }];
  const lastH = nowH ?? pts[pts.length - 1].h;
  const stepPath = pts.length
    ? `M ${X(pts[0].h)},${y(0)} ` +
      pts.map((p, i) => `L ${X(p.h)},${y(i === 0 ? p.ml : pts[i - 1].ml)} L ${X(p.h)},${y(p.ml)}`).join(" ") +
      ` L ${X(lastH)},${y(pts[pts.length - 1].ml)}`
    : "";
  const deficit = goal - total;
  const src = water.source === "garmin" ? " · Garmin" : water.source === "hae" ? " · Health" : "";
  // 「いつもの今頃」= 予測カーブの現在位置
  const expNow = nowH != null && water.expected_curve?.length
    ? water.expected_curve.reduce((a, p) => (Math.abs(p.h - nowH) < Math.abs(a.h - nowH) ? p : a)).v
    : null;
  const behind = expNow != null && expNow > 0 && total < expNow * 0.6;
  return (
    <svg viewBox={`0 0 ${SUB_W + 12} ${H}`} className="w-full" role="img" aria-label="水分摂取の累積">
      <SubGrid gridTicks={gridTicks} X={X} y0={14} y1={H - 8} />
      <line x1={0} y1={y(goal)} x2={SUB_W} y2={y(goal)} stroke={P.info} strokeWidth={0.8} strokeDasharray="4 3" opacity={0.5} />
      {/* いつものペース(過去の同時刻累積中央値) = 予測。破線で重ねる */}
      {(water.expected_curve?.length ?? 0) > 1 && (
        <polyline points={water.expected_curve!.map((p) => `${X(p.h)},${y(p.v)}`).join(" ")}
          fill="none" stroke={P.act300} strokeWidth={1.4} strokeDasharray="4 3" opacity={0.9} strokeLinejoin="round" />
      )}
      {/* cyan は水分トラック専用の固有色 (colorFor の家事カテゴリと同じ色だが別トラックのため衝突なし) */}
      {stepPath && <path d={`${stepPath} L ${X(lastH)},${y(0)} Z`} fill="#22d3ee" opacity={0.16} />}
      {stepPath && <path d={stepPath} fill="none" stroke="#22d3ee" strokeWidth={1.5} />}
      {water.intake_curve.map((p, i) => (<circle key={i} cx={X(p.h)} cy={y(p.ml)} r={2} fill="#22d3ee" />))}
      {nowH != null && <line x1={X(nowH)} y1={12} x2={X(nowH)} y2={H - 8} stroke={P.risk} strokeWidth={1} />}
      <text x={4} y={9} fontSize={10} fill={behind ? P.act300 : deficit > 500 ? P.act300 : P.inkDim}>
        水分 {total}/{goal}mL{src}
        {expNow != null ? <tspan fill={P.act300}> · いつも今頃{Math.round(expNow)}{behind ? " → 飲もう！" : ""}</tspan> : null}
        {water.sweat_ml > 0 ? ` · 発汗${water.sweat_ml}` : ""}
      </text>
    </svg>
  );
}

function PressureTrack({ curve, nowH, X, gridTicks }: {
  curve: { h: number; hpa: number }[];
  nowH: number | null;
  X: (h: number) => number;
  gridTicks: number[];
}) {
  const H = SUB_H;
  const vals = curve.map((p) => p.hpa);
  const lo = Math.min(...vals) - 1, hi = Math.max(...vals) + 1;
  const y = (hpa: number) => H - 8 - ((hpa - lo) / Math.max(1, hi - lo)) * (H - 22);
  const past = nowH == null ? curve : curve.filter((p) => p.h <= nowH);
  const fut = nowH == null ? [] : curve.filter((p) => p.h >= nowH);
  // 未来3hの変化量 (急降下=片頭痛トリガー)
  const nowHpa = nowH != null && curve.length ? curve.reduce((a, p) => (Math.abs(p.h - nowH) < Math.abs(a.h - nowH) ? p : a)).hpa : (curve.length ? curve[curve.length - 1].hpa : null);
  const lastFut = fut.length ? fut[fut.length - 1].hpa : null;
  const drop = nowHpa != null && lastFut != null ? lastFut - nowHpa : null;
  const warnDrop = drop != null && drop <= -3;
  return (
    <svg viewBox={`0 0 ${SUB_W + 12} ${H}`} className="w-full" role="img" aria-label="気圧(実測+予報)">
      <SubGrid gridTicks={gridTicks} X={X} y0={14} y1={H - 8} />
      {past.length > 1 && <polyline points={past.map((p) => `${X(p.h)},${y(p.hpa)}`).join(" ")} fill="none" stroke={P.inkDim} strokeWidth={1.5} />}
      {fut.length > 1 && <polyline points={fut.map((p) => `${X(p.h)},${y(p.hpa)}`).join(" ")} fill="none" stroke={warnDrop ? P.risk : P.inkDim} strokeWidth={1.5} strokeDasharray="3 3" opacity={0.8} />}
      {nowH != null && <line x1={X(nowH)} y1={12} x2={X(nowH)} y2={H - 8} stroke={P.risk} strokeWidth={1} />}
      <text x={4} y={9} fontSize={10} fill={warnDrop ? P.risk300 : P.inkDim}>
        気圧(実測+予報){nowHpa != null ? ` · 現在${Math.round(nowHpa)}hPa` : ""}{drop != null ? ` · 3h後${drop > 0 ? "+" : ""}${drop.toFixed(1)}${warnDrop ? " ⚠頭痛注意" : ""}` : ""}
      </text>
    </svg>
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
