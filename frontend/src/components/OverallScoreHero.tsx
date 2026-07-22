import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import { api, type Focus } from "../lib/api";
import { Panel, Skeleton } from "./ui/cockpit";
import { P } from "../lib/palette";

/**
 * アプリ最上部の「総合点 × 目標」ヒーロー。全体マップ (atlas) の総合点に一本化。
 *
 * 可視化の考え方 (Few / Tufte): 数字を主役にし、単独の装飾ゲージにしない。
 * 値だけでは意味を持たないため 4 つの文脈を必ず添える —
 *   ① 目標 (理想=100 までの残り) ② 推移 (7 日スパークライン) ③ 規範 (世の中=中央値)
 *   ④ 変化 (前日比)。リング進捗は「あと何点」の部分-全体感の補助に留める。
 */
function statusOf(v: number): { label: string; color: string } {
  if (v >= 75) return { label: "好調", color: P.prog300 };
  if (v >= 60) return { label: "おおむね順調", color: P.prog };
  if (v >= 45) return { label: "並", color: P.act };
  return { label: "要ケア", color: P.risk };
}

function Ring({ value, goal, color }: { value: number; goal?: number | null; color: string }) {
  const r = 40;
  const c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, value / 100));
  // 目標ティック: リング上の goal/100 位置に刻み (達成すると本線色、未達は琥珀)
  let tick = null;
  if (goal != null) {
    const a = (goal / 100) * 2 * Math.PI - Math.PI / 2;
    const cos = Math.cos(a);
    const sin = Math.sin(a);
    tick = (
      <line
        x1={52 + (r - 6) * cos} y1={52 + (r - 6) * sin}
        x2={52 + (r + 6) * cos} y2={52 + (r + 6) * sin}
        stroke={value >= goal ? color : P.act} strokeWidth="3" strokeLinecap="round"
      />
    );
  }
  return (
    <svg width="104" height="104" viewBox="0 0 104 104" className="shrink-0">
      <circle cx="52" cy="52" r={r} fill="none" stroke={P.hairline} strokeWidth="8" />
      <circle
        cx="52" cy="52" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
        strokeDasharray={`${c * frac} ${c}`} transform="rotate(-90 52 52)"
      />
      {tick}
      <text x="52" y="50" textAnchor="middle" dominantBaseline="central"
            fill={P.ink} fontSize="30" fontWeight="700" className="telemetry-num">
        {Math.round(value)}
      </text>
      <text x="52" y="70" textAnchor="middle" fill={P.inkFaint} fontSize="10">/ 100</text>
    </svg>
  );
}

export function OverallScoreHero({ focus }: { focus?: Focus }) {
  const q = useQuery({ queryKey: ["atlas"], queryFn: api.atlas, retry: false });
  if (!q.data) return <Skeleton className="h-32" />;
  const root = q.data.tree;
  const current = root.current;
  if (current == null) return null;

  const st = statusOf(current);
  const median = root.population?.median ?? null;
  const series = root.series ?? [];
  const goal = root.dynamic_goal ?? null; // 「ギリギリ達成できる」動的目標
  const goalVal = goal ?? 100;
  const remain = Math.max(0, Math.round(goalVal) - Math.round(current));
  const achieved = current >= goalVal;
  const prev = series.length >= 2 ? series[series.length - 2].value : null;
  const dayDelta = prev != null ? Math.round(current) - Math.round(prev) : null;

  const focusScore = focus?.score != null ? Math.round(focus.score) : null;
  const peak = focus?.peak_windows?.[0];
  const peakLabel = peak ? `${peak.start}–${peak.end}` : null;

  return (
    <Panel title="総合点 — 現状と目標">
      <div className="flex items-center gap-4">
        <Ring value={current} goal={goal} color={st.color} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="shrink-0 whitespace-nowrap text-sm font-semibold"
                  style={{ color: st.color }}>{st.label}</span>
            {focusScore != null && (
              <span className="shrink-0 whitespace-nowrap rounded-full bg-hull px-2 py-0.5 text-[11px] text-ink-dim">
                集中 {focusScore}
              </span>
            )}
          </div>
          {series.length >= 2 && (
            <div className="mt-1 h-10">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series} margin={{ top: 4, right: 2, bottom: 0, left: 0 }}>
                  <Tooltip
                    contentStyle={{ background: P.panel, border: `1px solid ${P.hairline}`,
                                    borderRadius: 8, fontSize: 11 }}
                    labelStyle={{ color: P.inkDim }}
                    formatter={(v: number) => [`${Math.round(v)}`, "総合点"]}
                  />
                  {median != null && <ReferenceLine y={median} stroke={P.inkFaint} strokeDasharray="3 3" />}
                  <Line type="monotone" dataKey="value" stroke={st.color} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-ink-faint">
            {goal != null ? (
              achieved ? (
                <span style={{ color: P.prog300 }}>今日の目標 {Math.round(goal)} 達成 ✓</span>
              ) : (
                <span>
                  <span className="text-ink-dim">今日の目標 {Math.round(goal)}</span> · あと {remain}
                </span>
              )
            ) : (
              <span>目標まで あと {remain}</span>
            )}
            {median != null && <span>世の中 {Math.round(median)}</span>}
            {dayDelta != null && dayDelta !== 0 && (
              <span style={{ color: dayDelta > 0 ? P.prog300 : P.act300 }}>
                前日比 {dayDelta > 0 ? "+" : ""}{dayDelta}
              </span>
            )}
            {peakLabel && <span>ピーク {peakLabel}</span>}
          </div>
        </div>
      </div>
    </Panel>
  );
}
