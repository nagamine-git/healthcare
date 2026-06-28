import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LifeCapital } from "../lib/api";
import { kindLabel } from "../lib/labels";
import { BarGauge, Panel, Pill, Skeleton } from "./ui/cockpit";

function go(hash: string) {
  window.location.hash = hash;
}

/** 目的→目標→ドメイン木(Life Optimization OS の中核ビュー)。home と #life で共用。 */
export function LifeTreePanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["life-tree"], queryFn: api.lifeTree });
  const garden = useQuery({ queryKey: ["garden"], queryFn: api.garden, retry: false });
  const logMut = useMutation({
    mutationFn: (kind: string) => api.gardenLog(kind),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["life-tree"] });
      qc.invalidateQueries({ queryKey: ["garden"] });
      qc.invalidateQueries({ queryKey: ["today"] });
    },
  });
  const manualSet = new Set(
    (garden.data?.catalog ?? []).filter((c) => c.source === "manual").map((c) => c.kind),
  );
  const loggedToday = new Set(Object.keys(garden.data?.today.contributions ?? {}));
  const d = q.data;
  if (!d) return <Skeleton className="h-44" />;
  const focus = d.focus_capital;

  return (
    <div className="space-y-3">
      {/* 目標(目的への接近度・人生スコアは StatusStrip に集約。ここは目標の詳細のみ) */}
      {d.goal && (
        <Panel onClick={() => go("#identity")}>
          <span className="telemetry-label">目標 — {d.purpose.archetype_name ?? "目的"} へ</span>
          <p className="mt-0.5 text-sm text-act-300">
            {d.goal.title}
            {d.goal.horizon ? `(${d.goal.horizon})` : ""}
          </p>
        </Panel>
      )}

      {/* ドメイン木 */}
      <Panel title="人生のドメイン(資本/状態)">
        {d.breaches.length > 0 && (
          <p className="mb-2 text-xs text-risk">
            ⚠ 最低ラインを割っている領域あり。下の「→ 立て直す」をタップで記録/実行。
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
              {/* 立て直しの具体策: 手動行動はタップで記録、自動計測は実行を促す */}
              {c.breach && c.kinds.length > 0 && (
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] text-risk">→ 立て直す:</span>
                  {c.kinds.map((k) => {
                    const manual = manualSet.has(k);
                    const done = loggedToday.has(k);
                    if (!manual) {
                      return (
                        <span
                          key={k}
                          className="rounded-full border border-hairline px-2 py-0.5 text-[11px] text-ink-faint"
                        >
                          {kindLabel(k)}
                          <span className="ml-1 text-ink-faint/60">(自動計測)</span>
                        </span>
                      );
                    }
                    return (
                      <button
                        key={k}
                        disabled={logMut.isPending}
                        onClick={() => logMut.mutate(k)}
                        className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors disabled:opacity-50 ${
                          done ? "bg-prog-500 text-void" : "bg-prog-700 text-ink hover:bg-prog-500"
                        }`}
                      >
                        {done ? "✓ " : "+ "}
                        {kindLabel(k)}
                      </button>
                    );
                  })}
                </div>
              )}
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
                <div className="mt-0.5 flex flex-wrap gap-1.5">
                  {a.kinds.slice(0, 4).map((k) => {
                    const manual = manualSet.has(k);
                    const done = loggedToday.has(k);
                    if (!manual) {
                      return (
                        <span key={k} className="rounded-full border border-hairline px-2 py-0.5 text-[10px] text-ink-faint">
                          {kindLabel(k)}<span className="ml-1 text-ink-faint/60">(自動)</span>
                        </span>
                      );
                    }
                    return (
                      <button
                        key={k}
                        disabled={logMut.isPending}
                        onClick={(e) => { e.stopPropagation(); logMut.mutate(k); }}
                        className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors disabled:opacity-50 ${
                          done ? "bg-prog-500 text-void" : "bg-prog-700 text-ink hover:bg-prog-500"
                        }`}
                      >
                        {done ? "✓ " : "+ "}{kindLabel(k)}
                      </button>
                    );
                  })}
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
