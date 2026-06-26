import { useQuery } from "@tanstack/react-query";
import { api, type LifeCapital } from "../lib/api";
import { BarGauge, Panel, Pill, RingGauge } from "../components/ui/cockpit";

function go(hash: string) {
  window.location.hash = hash;
}

export function LifePage({ onBack }: { onBack: () => void }) {
  const q = useQuery({ queryKey: ["life-tree"], queryFn: api.lifeTree });
  const d = q.data;
  const focus = d?.focus_capital;

  return (
    <div className="safe-area-top safe-area-x pb-nav mx-auto max-w-3xl space-y-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold text-ink">人生 — 最適化ツリー</h1>
      {q.isLoading && <p className="text-ink-dim">読み込み中…</p>}
      {q.isError && <p className="text-risk">取得に失敗しました</p>}
      {d && (
        <>
          {/* Layer 0: 目的 + life_score */}
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
              </div>
            </div>
          </Panel>

          {/* Layer 1: 目標 */}
          {d.goal && (
            <Panel title="目標(いまの重点を決める)">
              <p className="text-base font-semibold text-ink">{d.goal.title}</p>
              {d.goal.horizon && <p className="text-xs text-ink-faint">期限: {d.goal.horizon}</p>}
            </Panel>
          )}

          {/* Layer 2: ドメイン木 */}
          <Panel title="ドメイン(資本/状態)">
            {d.breaches.length > 0 && (
              <p className="mb-2 text-xs text-risk">
                ⚠ 維持フロアを割っている領域があります(優先で立て直す)
              </p>
            )}
            <div className="space-y-3">
              {d.capitals.map((c: LifeCapital) => (
                <div key={c.key}>
                  <div className="mb-1 flex items-center gap-2">
                    <span className="text-sm text-ink">{c.label}</span>
                    {c.key === focus && <Pill tone="act">重点</Pill>}
                    {c.breach && <Pill tone="risk">フロア割れ</Pill>}
                    <span className="ml-auto telemetry-num text-xs text-ink-faint">
                      ×{c.weight}
                    </span>
                  </div>
                  <BarGauge
                    label={c.leaves.join(" / ")}
                    value={c.achievement}
                    tone={c.breach ? "risk" : c.key === focus ? "act" : "prog"}
                  />
                </div>
              ))}
            </div>
          </Panel>

          <p className="text-center text-[10px] text-ink-faint">
            目的 → 目標 → ドメイン → 行動。重点に寄せつつ、フロアは守る。
          </p>
        </>
      )}
    </div>
  );
}
