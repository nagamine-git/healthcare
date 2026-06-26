import { useQuery } from "@tanstack/react-query";
import { api, type LifeCapital } from "../lib/api";
import { BarGauge, Panel, Pill, RingGauge } from "./ui/cockpit";

function go(hash: string) {
  window.location.hash = hash;
}

/** 目的→目標→ドメイン木(Life Optimization OS の中核ビュー)。home と #life で共用。 */
export function LifeTreePanel() {
  const q = useQuery({ queryKey: ["life-tree"], queryFn: api.lifeTree });
  const d = q.data;
  if (!d) return null;
  const focus = d.focus_capital;

  return (
    <div className="space-y-3">
      {/* 目的 + 人生スコア */}
      <Panel onClick={() => go("#identity")}>
        <div className="flex items-center gap-5">
          <RingGauge value={d.life_score} label="LIFE SCORE" tone="prog" />
          <div className="flex-1">
            <span className="telemetry-label">目的(北極星)</span>
            <p className="mt-0.5 text-sm font-semibold text-ink">
              {d.purpose.archetype_name ?? "—"}
            </p>
            {d.purpose.overall !== null && (
              <p className="mt-1 text-xs text-ink-dim">
                理想への接近度 {Math.round(d.purpose.overall)}%
              </p>
            )}
            {d.goal && (
              <p className="mt-1 text-xs text-act-300">
                目標: {d.goal.title}
                {d.goal.horizon ? `(${d.goal.horizon})` : ""}
              </p>
            )}
          </div>
        </div>
      </Panel>

      {/* ドメイン木 */}
      <Panel title="人生のドメイン(資本/状態)">
        {d.breaches.length > 0 && (
          <p className="mb-2 text-xs text-risk">
            ⚠ 最低ラインを割っている領域があります(優先で立て直す)
          </p>
        )}
        <div className="space-y-3">
          {d.capitals.map((c: LifeCapital) => (
            <div key={c.key}>
              <div className="mb-1 flex items-center gap-2">
                <span className="text-sm text-ink">{c.label}</span>
                {c.key === focus && <Pill tone="act">重点</Pill>}
                {c.breach && <Pill tone="risk">要立て直し</Pill>}
                <span className="ml-auto telemetry-num text-xs text-ink-faint">×{c.weight}</span>
              </div>
              <BarGauge
                label={c.leaves.join(" / ")}
                value={c.achievement}
                tone={c.breach ? "risk" : c.key === focus ? "act" : "prog"}
              />
            </div>
          ))}
        </div>
        <p className="mt-3 text-[10px] text-ink-faint">
          目標で重点に寄せつつ、各領域の最低ラインは守る。
        </p>
      </Panel>
    </div>
  );
}
