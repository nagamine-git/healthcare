import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

/**
 * 今日の流れ: 1日 (0-24h JST) を 1 本のマルチトラック帯で可視化する。
 * - 上段ストリップ: カレンダー予定 / ワークアウト
 * - メイン: Body Battery (面) + ストレス (線)、睡眠帯・頭痛帯をオーバーレイ
 * - 下段: カフェイン摂取 (mg でサイズ)、チェックイン時点、現在線
 * 「いつ何が起きて、エネルギーがどう動いたか」の因果を一目で読むための図。
 */

const W = 960; // 40px / hour
const H = 168;
const CHART_TOP = 32;
const CHART_BOTTOM = 132;
const X = (h: number) => Math.max(0, Math.min(24, h)) * 40;
const Y = (v: number) => CHART_BOTTOM - (Math.max(0, Math.min(100, v)) / 100) * (CHART_BOTTOM - CHART_TOP);

const WORKOUT_LABEL: Record<string, string> = {
  strength_training: "筋トレ",
  breathwork: "呼吸",
  walking: "歩行",
  running: "ラン",
};

export function DayTimeline() {
  const q = useQuery({
    queryKey: ["timeline"],
    queryFn: () => api.timeline(),
    refetchInterval: 5 * 60_000,
  });
  const d = q.data;
  if (q.isLoading) return <div className="text-sm text-slate-400">読み込み中...</div>;
  if (!d) return <div className="text-sm text-rose-400">タイムライン取得に失敗しました</div>;

  const hasData = d.body_battery.length > 0 || d.stress.length > 0 || d.sleep;
  if (!hasData) {
    return (
      <div className="rounded-2xl bg-slate-900/40 p-4 text-xs text-slate-500">
        まだ今日のデータがありません (同期待ち)
      </div>
    );
  }

  const bbPts = d.body_battery.map((p) => `${X(p.h)},${Y(p.v)}`).join(" ");
  const bbArea =
    d.body_battery.length > 1
      ? `M ${X(d.body_battery[0].h)},${CHART_BOTTOM} L ${d.body_battery
          .map((p) => `${X(p.h)},${Y(p.v)}`)
          .join(" L ")} L ${X(d.body_battery[d.body_battery.length - 1].h)},${CHART_BOTTOM} Z`
      : null;
  const stressPts = d.stress.map((p) => `${X(p.h)},${Y(p.v)}`).join(" ");

  return (
    <div className="rounded-2xl bg-slate-900/40 p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="今日のタイムライン">
        {/* 時間グリッド (3h ごと) + ラベル */}
        {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
          <g key={h}>
            <line x1={X(h)} y1={10} x2={X(h)} y2={CHART_BOTTOM} stroke="#1e293b" strokeWidth={h % 6 === 0 ? 1 : 0.5} />
            {h % 6 === 0 && (
              <text x={X(h)} y={H - 4} fontSize={11} fill="#64748b" textAnchor="middle">
                {h}
              </text>
            )}
          </g>
        ))}

        {/* 睡眠帯 (チャート全高、藍) */}
        {d.sleep && (
          <rect
            x={X(d.sleep.start_h)}
            y={CHART_TOP}
            width={X(d.sleep.end_h) - X(d.sleep.start_h)}
            height={CHART_BOTTOM - CHART_TOP}
            fill="#6366f1"
            opacity={0.14}
          >
            <title>睡眠</title>
          </rect>
        )}

        {/* 頭痛帯 (ロゼ、進行中は現在まで) */}
        {d.migraine.map((m, i) => (
          <rect
            key={i}
            x={X(m.start_h)}
            y={CHART_TOP}
            width={Math.max(4, X(m.end_h ?? d.now_h ?? 24) - X(m.start_h))}
            height={CHART_BOTTOM - CHART_TOP}
            fill="#f43f5e"
            opacity={0.12}
          >
            <title>頭痛{m.severity != null ? ` 強度${m.severity}/10` : ""}</title>
          </rect>
        ))}

        {/* カレンダー予定ストリップ */}
        {d.events.map((e, i) => (
          <rect key={i} x={X(e.start_h)} y={12} width={Math.max(3, X(e.end_h) - X(e.start_h))} height={8}
                rx={2} fill="#475569" opacity={0.8}>
            <title>{e.title}</title>
          </rect>
        ))}

        {/* ワークアウトストリップ */}
        {d.workouts.map((w, i) => (
          <rect key={i} x={X(w.start_h)} y={22} width={Math.max(3, X(w.end_h) - X(w.start_h))} height={8}
                rx={2} fill="#34d399" opacity={0.9}>
            <title>{WORKOUT_LABEL[w.type ?? ""] ?? w.type ?? "運動"}</title>
          </rect>
        ))}

        {/* Body Battery 面 + 線 */}
        {bbArea && <path d={bbArea} fill="#34d399" opacity={0.15} />}
        {d.body_battery.length > 0 && (
          <polyline points={bbPts} fill="none" stroke="#34d399" strokeWidth={2} strokeLinejoin="round" />
        )}

        {/* ストレス線 */}
        {d.stress.length > 1 && (
          <polyline points={stressPts} fill="none" stroke="#f59e0b" strokeWidth={1.2} opacity={0.75} />
        )}

        {/* カフェイン摂取 (mg でサイズ) */}
        {d.caffeine.map((c, i) => (
          <circle key={i} cx={X(c.h)} cy={142} r={3 + Math.min(5, c.mg / 30)} fill="#a78bfa">
            <title>{`カフェイン ${Math.round(c.mg)}mg (${c.source})`}</title>
          </circle>
        ))}

        {/* チェックイン時点 */}
        {d.checkin && (
          <g transform={`translate(${X(d.checkin.h)},142)`}>
            <rect x={-4} y={-4} width={8} height={8} transform="rotate(45)" fill="#e2e8f0">
              <title>{`チェックイン 気分${d.checkin.mood ?? "-"} 活力${d.checkin.energy ?? "-"}`}</title>
            </rect>
          </g>
        )}

        {/* 現在線 */}
        {d.now_h != null && (
          <g>
            <line x1={X(d.now_h)} y1={8} x2={X(d.now_h)} y2={CHART_BOTTOM + 16} stroke="#f43f5e" strokeWidth={1.5} />
            <circle cx={X(d.now_h)} cy={8} r={3} fill="#f43f5e" />
          </g>
        )}
      </svg>

      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
        <span><span className="text-indigo-400">■</span> 睡眠</span>
        <span><span className="text-emerald-400">━</span> Body Battery</span>
        <span><span className="text-amber-400">━</span> ストレス</span>
        <span><span className="text-emerald-400">▬</span> 運動</span>
        <span><span className="text-slate-400">▬</span> 予定</span>
        <span><span className="text-violet-400">●</span> カフェイン</span>
        <span><span className="text-rose-400">│</span> いま</span>
        {d.migraine.length > 0 && <span><span className="text-rose-400">■</span> 頭痛</span>}
      </div>
    </div>
  );
}
