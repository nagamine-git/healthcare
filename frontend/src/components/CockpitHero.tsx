import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { DIAGNOSIS, etaLabel, pct } from "../lib/becomingDisplay";
import { kindLabel } from "../lib/labels";
import { Button, Panel, Pill, Stat } from "./ui/cockpit";
import { TopBookHint } from "./TopBookHint";

function go(hash: string) {
  window.location.hash = hash;
}

/** Today の最上部に載るコックピットのヒーロー: 今日の一手(主役)+ becoming 要約。
 * コンディション/人生スコアは StatusStrip に分離。 */
export function CockpitHero() {
  const qc = useQueryClient();
  const becoming = useQuery({ queryKey: ["becoming"], queryFn: api.becoming, retry: false });
  const garden = useQuery({ queryKey: ["garden"], queryFn: api.garden, retry: false });
  const moveMut = useMutation({ mutationFn: () => api.becomingOneMove() });
  const logMut = useMutation({
    mutationFn: (kind: string) => api.gardenLog(kind),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["garden"] });
      qc.invalidateQueries({ queryKey: ["becoming"] });
    },
  });
  const manualKinds = (garden.data?.catalog ?? []).filter((c) => c.source === "manual");
  const loggedToday = new Set(Object.keys(garden.data?.today.contributions ?? {}));
  const weakest = garden.data?.weakest_hint ?? null;
  const effSet = new Set(weakest?.kinds ?? []);
  const hasFocus = effSet.size > 0;
  const effectiveKinds = hasFocus ? manualKinds.filter((c) => effSet.has(c.kind)) : manualKinds;
  const otherKinds = hasFocus ? manualKinds.filter((c) => !effSet.has(c.kind)) : [];
  const readingEffective = !hasFocus || effSet.has("reading");
  const loop = becoming.data?.loop_week;
  const traj = becoming.data?.trajectory;
  const diag = loop ? DIAGNOSIS[loop.diagnosis] : null;

  return (
    <div className="space-y-3">
      {/* 今日やること = 具体の一手(動的)+ 効く行動の記録。1パネルに統合。 */}
      <Panel
        title="今日やること"
        glow="act"
        action={
          <Button variant="primary" disabled={moveMut.isPending} onClick={() => moveMut.mutate()}>
            {moveMut.isPending ? "生成中…" : moveMut.data ? "再生成" : "決める"}
          </Button>
        }
      >
        {/* 1) 今日いちばんの具体タスク */}
        {moveMut.data ? (
          <div className="space-y-1">
            <p className="text-lg font-semibold leading-snug text-ink">
              {moveMut.data.theme && <span className="text-prog-300">{moveMut.data.theme}: </span>}
              {moveMut.data.move}
            </p>
            <p className="text-sm text-act-300">if-then: {moveMut.data.if_then}</p>
            <p className="text-xs text-ink-faint">{moveMut.data.rationale}</p>
          </div>
        ) : (
          <p className="text-sm text-ink-dim">
            「決める」で、いまの伸びしろ
            {weakest?.name && <span className="text-prog-300">「{weakest.name}」</span>}
            に効く今日いちばんの一手が出ます。
          </p>
        )}

        {/* 読書が効く日は具体的な1冊も提案 */}
        {readingEffective && (
          <div className="mt-2">
            <TopBookHint />
          </div>
        )}

        {/* 2) 効く行動を記録(緑=今日効く / 白=その他) */}
        {manualKinds.length > 0 && (
          <div className="mt-3 border-t border-hairline pt-2">
            <p className="telemetry-label">やったら記録(緑=今日効く)</p>
            <div className="mt-1 flex flex-wrap gap-2">
              {effectiveKinds.map((c) => {
                const done = loggedToday.has(c.kind);
                return (
                  <button
                    key={c.kind}
                    disabled={logMut.isPending}
                    onClick={() => logMut.mutate(c.kind)}
                    className={`rounded-full px-3 py-1 text-sm font-medium transition-colors disabled:opacity-50 ${
                      done ? "bg-prog-500 text-void" : "bg-prog-700 text-ink hover:bg-prog-500"
                    }`}
                  >
                    {done ? "✓ " : "+ "}
                    {kindLabel(c.kind)}
                  </button>
                );
              })}
              {otherKinds.map((c) => {
                const done = loggedToday.has(c.kind);
                return (
                  <button
                    key={c.kind}
                    disabled={logMut.isPending}
                    onClick={() => logMut.mutate(c.kind)}
                    className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors disabled:opacity-50 ${
                      done
                        ? "border-prog-700 text-prog-300"
                        : "border-hairline text-ink-faint hover:border-ink-faint hover:text-ink-dim"
                    }`}
                  >
                    {done ? "✓ " : "+ "}
                    {kindLabel(c.kind)}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </Panel>

      {/* 好循環 + ゴールまで(タップで「歩み」へ) */}
      <div className="grid grid-cols-2 gap-3">
        <Panel title="今週の好循環" onClick={() => go("#becoming")}>
          {loop && diag ? (
            <>
              <Pill tone={diag.tone}>{diag.short}</Pill>
              <div className="mt-2 grid grid-cols-3 gap-1 text-center">
                <Stat size="sm" label="動けた" value={pct(loop.capacity_utilization)} />
                <Stat size="sm" label="効く行動" value={pct(loop.action_alignment)} />
                <Stat
                  size="sm"
                  label="近づいた"
                  tone={loop.identity_movement && loop.identity_movement > 0 ? "prog" : "neutral"}
                  value={loop.identity_movement === null ? "—" : loop.identity_movement.toFixed(1)}
                />
              </div>
            </>
          ) : (
            <p className="text-sm text-ink-faint">記録が貯まると表示</p>
          )}
        </Panel>
        <Panel title="ゴールまで" onClick={() => go("#becoming")}>
          {traj ? (
            <>
              <Stat
                size="lg"
                value={etaLabel(traj.eta_days)}
                tone="prog"
                delta={traj.confidence === "low" ? "蓄積中" : undefined}
              />
              {traj.bottleneck_name && (
                <p className="mt-1 text-xs text-ink-dim">
                  伸びしろ: <span className="text-ink">{traj.bottleneck_name}</span>
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-ink-faint">—</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
