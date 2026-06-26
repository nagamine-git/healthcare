import { useQuery } from "@tanstack/react-query";
import { api, type LifeCapital } from "../lib/api";
import { kindLabel } from "../lib/labels";
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
                label=""
                value={c.achievement}
                tone={c.breach ? "risk" : c.key === focus ? "act" : "prog"}
              />
              {/* 葉(各領域)の達成度を小さく内訳表示 */}
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                {c.leaves.map((leaf) => (
                  <span key={leaf.label} className="text-[10px] text-ink-faint">
                    {leaf.label}
                    <span className="ml-1 telemetry-num text-ink-dim">
                      {leaf.achievement === null ? "—" : Math.round(leaf.achievement)}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[10px] text-ink-faint">
          目標で重点に寄せつつ、各領域の最低ラインは守る。
        </p>
      </Panel>

      {/* 今日の最適配分(F4) */}
      {d.allocation.length > 0 && (
        <Panel title="今日はここに効かせる" glow="act">
          <ol className="space-y-2">
            {d.allocation.map((a, i) => (
              <li key={a.capital} className="text-sm">
                <span className="telemetry-num text-act-300">{i + 1}.</span>{" "}
                <span className="font-semibold text-ink">{a.label}</span>
                <span className="ml-1 text-xs text-ink-faint">— {a.reason}</span>
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {a.kinds.slice(0, 4).map((k) => (
                    <span key={k} className="rounded-full border border-hairline px-1.5 text-[10px] text-ink-faint">
                      {kindLabel(k)}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ol>
        </Panel>
      )}

      {/* 相互関係(辺)— 一言ヒント */}
      {d.edges.length > 0 && (
        <Panel title="領域のつながり">
          <ul className="space-y-1 text-xs text-ink-dim">
            {d.edges.map((e) => (
              <li key={e.from}>・{e.note}</li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
