import { useQuery } from "@tanstack/react-query";
import { api, type SubScores } from "../lib/api";
import { BarGauge, Panel, RingGauge } from "./ui/cockpit";

function go(hash: string) {
  window.location.hash = hash;
}

/**
 * 状態カード: 「今日(身体)」と「人生(目的への前進)」を1枚にコンパクト集約。
 * 視覚言語を変える(今日=リング=瞬間の計器 / 人生=進捗バー=長期の軌跡)ことで
 * 大リング2つの双子感を解消し、主役(今日やること)を引き立てる。
 */
export function StatusStrip({ score, headline }: { score: SubScores | null; headline?: string }) {
  const life = useQuery({ queryKey: ["life-tree"], queryFn: api.lifeTree });
  const d = life.data;
  const lifeScore = d?.life_score ?? null;
  const overall = d?.purpose.overall ?? null;
  const archetype = d?.purpose.archetype_name ?? null;
  const focusLabel =
    d?.capitals.find((c) => c.key === d.focus_capital)?.label ?? null;
  const lifeFrac = lifeScore === null ? 0 : Math.max(0, Math.min(1, lifeScore / 100));

  return (
    <Panel title="状態 — 今日(身体) / 人生(目的)">
      {/* 今日(身体): リング=瞬間の計器 */}
      <button onClick={() => go("#today")} className="flex w-full items-center gap-4 text-left">
        <RingGauge value={score?.total ?? null} label="今日" tone="prog" size={92} />
        <div className="flex-1 space-y-2">
          <BarGauge label="SLEEP" value={score?.sleep ?? null} />
          <BarGauge label="AUTONOMIC" value={score?.hrv ?? null} />
          <BarGauge label="ENERGY" value={score?.body_battery ?? null} />
        </div>
      </button>

      {headline && (
        <p className="mt-2 text-sm text-ink-dim">{headline}</p>
      )}

      {/* 人生(目的への前進): 進捗バー=長期の軌跡 */}
      <button
        onClick={() => go("#life")}
        className="mt-3 block w-full border-t border-hairline pt-3 text-left"
      >
        <div className="flex items-baseline justify-between">
          <span className="telemetry-label">人生 — {archetype ?? "目的"} へ</span>
          <span className="telemetry-num text-lg font-bold text-prog-300">
            {lifeScore === null ? "—" : Math.round(lifeScore)}
          </span>
        </div>
        <div className="mt-1 h-1.5 rounded-full bg-hairline">
          <div
            className="h-1.5 rounded-full bg-prog-500"
            style={{ width: `${lifeFrac * 100}%`, transition: "width 600ms ease-out" }}
          />
        </div>
        <p className="mt-1 text-[11px] text-ink-faint">
          {overall !== null ? `理想への接近度 ${Math.round(overall)}%` : "—"}
          {focusLabel && <span> ・ 伸びしろ {focusLabel}</span>}
        </p>
      </button>
    </Panel>
  );
}
