import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AtlasNode } from "../lib/api";
import { Panel, Skeleton } from "./ui/cockpit";

function fmt(v: number | null, unit: string): string {
  if (v == null) return "—";
  return `${v}${unit}`;
}

/** 「世の中」列: 中央値 / パーセンタイル / 基準範囲 を出し分け。 */
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

/** 現状の色: 目標/中央値に対して良い向きかで淡く色付け(direction 基準)。 */
function currentTone(n: AtlasNode): string {
  const ref = n.target ?? n.population?.median ?? null;
  if (n.current == null || ref == null || n.direction === "none") return "text-ink";
  if (n.direction === "up") return n.current >= ref ? "text-prog-300" : "text-act-300";
  if (n.direction === "down") return n.current <= ref ? "text-prog-300" : "text-act-300";
  return "text-ink"; // band は単純比較しない
}

function MetricRow({ n }: { n: AtlasNode }) {
  return (
    <div className="flex items-center gap-2 py-1.5">
      <span className="min-w-0 flex-1 truncate text-sm text-ink">{n.label}</span>
      <div className="flex shrink-0 items-center gap-3 text-right">
        <div className="w-16">
          <div className="telemetry-label text-[9px]">現状</div>
          <div className={`telemetry-num text-sm font-semibold ${currentTone(n)}`}>
            {fmt(n.current, n.unit)}
          </div>
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
  );
}

function DomainSection({ n }: { n: AtlasNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-hairline first:border-t-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 py-2 text-left"
      >
        <span className="text-ink-faint">{open ? "▾" : "▸"}</span>
        <span className="flex-1 text-sm font-semibold text-ink">{n.label}</span>
        {n.current != null && (
          <span className="telemetry-num text-sm text-prog-300">
            {fmt(n.current, n.unit)}
            {n.target != null && <span className="ml-1 text-[10px] text-ink-faint">/ {n.target}</span>}
          </span>
        )}
        <span className="telemetry-label text-[10px] text-ink-faint">{n.children.length}</span>
      </button>
      {open && (
        <div className="ml-4 border-l border-hairline pl-2">
          {n.children.map((c) =>
            c.children.length > 0 ? <DomainSection key={c.key} n={c} /> : <MetricRow key={c.key} n={c} />,
          )}
        </div>
      )}
    </div>
  );
}

/** 全体マップ: 総合点→ドメイン→指標。各リーフを 現状/世の中/目標 で統一表示。3階層以下は開閉。 */
export function AtlasTree() {
  const q = useQuery({ queryKey: ["atlas"], queryFn: api.atlas, retry: false });
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
      <div className="mt-1">
        {root.children.map((c) => (
          <DomainSection key={c.key} n={c} />
        ))}
      </div>
      <p className="mt-2 text-[10px] text-ink-faint">
        ▸ をタップで内訳を開く。世の中=母集団中央値/パーセンタイル/健診基準。— は未取得。
      </p>
    </Panel>
  );
}
