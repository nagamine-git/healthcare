import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { api, type AtlasNode } from "../lib/api";
import { Panel, Skeleton } from "./ui/cockpit";
import { P } from "../lib/palette";

function fmt(v: number | null, unit: string): string {
  if (v == null) return "—";
  return `${v}${unit}`;
}

function popText(p: AtlasNode["population"], unit: string): string {
  if (!p) return "—";
  if (p.median != null) return `中央 ${p.median}${unit}`;
  if (p.percentile != null) return `${Math.round(p.percentile)}%ile`;
  if (p.range) {
    const [lo, hi] = p.range;
    if (lo != null && hi != null) return `基準 ${lo}–${hi}`;
    if (hi != null) return `基準 ≤${hi}`;
    if (lo != null) return `基準 ≥${lo}`;
  }
  return "—";
}

function currentTone(n: AtlasNode): string {
  const ref = n.target ?? n.population?.median ?? null;
  if (n.current == null || ref == null || n.direction === "none") return "text-ink";
  if (n.direction === "up") return n.current >= ref ? "text-prog-300" : "text-act-300";
  if (n.direction === "down") return n.current <= ref ? "text-prog-300" : "text-act-300";
  return "text-ink";
}

/** リーフの時系列を折れ線で。目標があれば参照線を引く(トレンドが一番効く可視化)。 */
function Sparkline({ n }: { n: AtlasNode }) {
  return (
    <div className="mt-1 h-12">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={n.series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <Tooltip
            contentStyle={{ background: "#1a2230", border: "1px solid #243044", borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: "#9aa7b8" }}
            formatter={(v: number) => [`${v}${n.unit}`, n.label]}
          />
          {n.target != null && <ReferenceLine y={n.target} stroke={P.act} strokeDasharray="3 3" />}
          <Line type="monotone" dataKey="value" stroke={P.prog} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

type OnWeight = (key: string, weight: number) => void;

/** 優先の重み ×0〜×5 (0.5刻み)。既定 ×1.0。末端まで設定可。 */
function WeightStepper({ w, onSet }: { w: number; onSet: (v: number) => void }) {
  const clamp = (v: number) => Math.max(0, Math.min(5, Math.round(v * 2) / 2));
  const tone = w === 1 ? "text-ink-faint" : w > 1 ? "text-act-300" : "text-ink-dim";
  return (
    <div className="flex shrink-0 items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <span className="text-[9px] text-ink-faint">優先</span>
      <button onClick={() => onSet(clamp(w - 0.5))}
        className="grid h-5 w-5 place-items-center rounded bg-panel text-ink-dim active:scale-95">−</button>
      <span className={`w-9 text-center text-[11px] tabular-nums ${tone}`}>×{w.toFixed(1)}</span>
      <button onClick={() => onSet(clamp(w + 0.5))}
        className="grid h-5 w-5 place-items-center rounded bg-panel text-ink-dim active:scale-95">＋</button>
    </div>
  );
}

function MetricRow({ n, onWeight }: { n: AtlasNode; onWeight?: OnWeight }) {
  return (
    <div className="py-1.5">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm text-ink">{n.label}</span>
        <div className="flex shrink-0 items-center gap-3 text-right">
          <div className="w-16">
            <div className="telemetry-label text-[9px]">現状</div>
            <div className={`telemetry-num text-sm font-semibold ${currentTone(n)}`}>{fmt(n.current, n.unit)}</div>
          </div>
          <div className="w-16">
            <div className="telemetry-label text-[9px]">世の中</div>
            <div className="telemetry-num text-xs text-ink-dim">{popText(n.population, n.unit)}</div>
          </div>
          <div className="w-16">
            <div className="telemetry-label text-[9px]">目標</div>
            <div className="telemetry-num text-xs text-ink-dim">{fmt(n.target, n.unit)}</div>
          </div>
        </div>
      </div>
      {n.series.length >= 2 && <Sparkline n={n} />}
      {onWeight && (
        <div className="mt-0.5 flex justify-end">
          <WeightStepper w={n.weight ?? 1} onSet={(v) => onWeight(n.key, v)} />
        </div>
      )}
    </div>
  );
}

/** ドメイン直下の子が 0-100 score を持つなら、現状/中央値/目標 をレーダーで一望。 */
function DomainRadar({ children }: { children: AtlasNode[] }) {
  const data = children
    .filter((c) => c.score != null)
    .map((c) => ({
      axis: c.label,
      現状: c.score as number,
      中央値: c.score_pop ?? null,
      目標: 100, // 正規化上、目標=満点(外周)
    }));
  if (data.length < 3) return null;
  const hasPop = data.some((d) => d.中央値 != null);
  return (
    <div className="h-52">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} outerRadius="65%">
          <PolarGrid stroke="#243044" />
          <PolarAngleAxis dataKey="axis" tick={{ fill: "#9aa7b8", fontSize: 10 }} />
          <Radar name="目標" dataKey="目標" stroke={P.act} fill="none" strokeDasharray="3 3" />
          {hasPop && (
            <Radar name="中央値" dataKey="中央値" stroke="#9aa7b8" fill="#9aa7b8" fillOpacity={0.12} connectNulls />
          )}
          <Radar name="現状" dataKey="現状" stroke={P.prog} fill={P.prog} fillOpacity={0.35} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Tooltip
            contentStyle={{ background: "#1a2230", border: "1px solid #243044", borderRadius: 8, fontSize: 11 }}
            formatter={(v: number, name: string) => [Math.round(v), name]}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

function DomainSection({ n, onWeight }: { n: AtlasNode; onWeight?: OnWeight }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-hairline first:border-t-0">
      {/* ネストボタン回避: トグルは label 部のみ、重みステッパーは兄弟 */}
      <div className="flex w-full items-center gap-2 py-2">
        <button onClick={() => setOpen((o) => !o)} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <span className="text-ink-faint">{open ? "▾" : "▸"}</span>
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">{n.label}</span>
          {n.score != null && (
            <span className="telemetry-num text-sm font-bold text-prog-300" title="ドメイン総合点 (0-100)">
              {Math.round(n.score)}
            </span>
          )}
        </button>
        {onWeight && <WeightStepper w={n.weight ?? 1} onSet={(v) => onWeight(n.key, v)} />}
      </div>
      {open && (
        <div className="ml-4 border-l border-hairline pl-2">
          <DomainRadar children={n.children} />
          {n.children.map((c) =>
            c.children.length > 0
              ? <DomainSection key={c.key} n={c} onWeight={onWeight} />
              : <MetricRow key={c.key} n={c} onWeight={onWeight} />,
          )}
        </div>
      )}
    </div>
  );
}

/** 全体マップ: 総合点→ドメイン→指標。現状/世の中/目標 + レーダー(バランス)+ 折れ線(推移)。 */
export function AtlasTree() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["atlas"], queryFn: api.atlas, retry: false });
  const weightMut = useMutation({
    mutationFn: ({ key, weight }: { key: string; weight: number }) => api.atlasSetWeight(key, weight),
    onSuccess: (d) => qc.setQueryData(["atlas"], d),
  });
  const onWeight: OnWeight = (key, weight) => weightMut.mutate({ key, weight });
  if (!q.data) return <Skeleton className="h-64" />;
  const root = q.data.tree;
  return (
    <Panel title="全体マップ — 現状 / 世の中 / 目標">
      <div className="flex items-baseline justify-between border-b border-hairline pb-2">
        <span className="text-sm font-bold text-ink">{root.label}</span>
        <span className="telemetry-num text-2xl font-bold text-prog-300">
          {root.current == null ? "—" : Math.round(root.current)}
          <span className="ml-1 text-xs text-ink-faint">/ 100</span>
        </span>
      </div>
      {root.series.length >= 2 && <Sparkline n={root} />}
      {/* ドメイン別バランス(常時表示の第二階層レーダー) */}
      <DomainRadar children={root.children} />
      <div className="mt-1">
        {root.children.map((c) => (
          <DomainSection key={c.key} n={c} onWeight={onWeight} />
        ))}
      </div>
      <p className="mt-2 text-[10px] text-ink-faint">
        ▸ で内訳を開く。レーダー=バランス、折れ線=推移(琥珀線=目標)。世の中=中央値/パーセンタイル/健診基準。
      </p>
    </Panel>
  );
}
