import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { DIAGNOSIS, etaLabel, pct } from "../lib/becomingDisplay";
import { Button, Panel, Pill, Stat } from "../components/ui/cockpit";

export function BecomingPage({ onBack }: { onBack: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["becoming"], queryFn: api.becoming });
  const moveMut = useMutation({ mutationFn: () => api.becomingOneMove() });
  const backfillMut = useMutation({
    mutationFn: () => api.becomingBackfill(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["becoming"] }),
  });

  const loop = q.data?.loop_week;
  const traj = q.data?.trajectory;
  const diag = loop ? DIAGNOSIS[loop.diagnosis] : null;

  return (
    <div className="safe-area-top mx-auto max-w-3xl space-y-4 px-4 pb-4">
      <button onClick={onBack} className="telemetry-label hover:text-ink">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold text-ink">becoming — 三層フライホイール</h1>
      {q.isLoading && <p className="text-ink-dim">読み込み中…</p>}
      {q.isError && <p className="text-risk">取得に失敗しました</p>}
      {q.data && loop && traj && diag && (
        <>
          <Panel title="今週のフライホイール">
            <div className="grid grid-cols-3 gap-2 text-center">
              <Stat size="sm" label="資本活用率" tone="prog" value={`${pct(loop.capacity_utilization)}%`} />
              <Stat size="sm" label="行動整合度" tone="prog" value={`${pct(loop.action_alignment)}%`} />
              <Stat
                size="sm"
                label="前進量"
                tone={loop.identity_movement && loop.identity_movement > 0 ? "prog" : "neutral"}
                value={loop.identity_movement === null ? "—" : loop.identity_movement.toFixed(1)}
              />
            </div>
            <p className="mt-3 text-xs text-ink-faint">活用=動けた日に攻めたか / 整合=盲点に向いたか / 前進=実際に近づいたか</p>
            <div className="mt-2">
              <Pill tone={diag.tone}>{diag.long}</Pill>
            </div>
          </Panel>

          <Panel
            title="今日の一手(盲点ねらい)"
            glow="act"
            action={
              <Button variant="primary" disabled={moveMut.isPending} onClick={() => moveMut.mutate()}>
                {moveMut.isPending ? "生成中…" : "生成"}
              </Button>
            }
          >
            {moveMut.data ? (
              <div className="space-y-1 text-sm">
                <p className="font-semibold text-ink">{moveMut.data.move}</p>
                <p className="text-act-300">if-then: {moveMut.data.if_then}</p>
                <p className="text-xs text-ink-faint">{moveMut.data.rationale}</p>
                {moveMut.data.fallback && (
                  <p className="text-xs text-ink-faint">(LLM未設定のため定型提案)</p>
                )}
              </div>
            ) : (
              <p className="text-sm text-ink-faint">「生成」で今日の高レバレッジな一手を作ります</p>
            )}
          </Panel>

          <Panel title="North Star — 理想プロファイル到達予測" onClick={undefined}>
            <div className="flex items-baseline justify-between">
              <span className="telemetry-num text-3xl font-bold text-prog-300">
                {traj.eta_days === null ? "—" : etaLabel(traj.eta_days)}
              </span>
              {traj.confidence === "low" && (
                <span className="text-xs text-act-300">低信頼(蓄積中)</span>
              )}
            </div>
            {traj.eta_days === null && (
              <p className="mt-1 text-xs text-ink-faint">到達経路が未確定(データ蓄積中)</p>
            )}
            {traj.bottleneck_name && (
              <p className="mt-1 text-sm text-ink-dim">
                ボトルネック: <span className="font-semibold text-ink">{traj.bottleneck_name}</span>
              </p>
            )}
            {traj.per_dimension.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-ink-dim">
                {traj.per_dimension
                  .slice()
                  .sort((a, b) => (b.time_to_target_days ?? Infinity) - (a.time_to_target_days ?? Infinity))
                  .slice(0, 5)
                  .map((d) => (
                    <li key={d.id} className="flex justify-between">
                      <span>{d.name ?? d.id}</span>
                      <span className="telemetry-num">
                        {d.current === null ? "—" : Math.round(d.current)}/{d.target}
                        {d.time_to_target_days !== null && ` · ${etaLabel(d.time_to_target_days)}`}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </Panel>

          <button
            disabled={backfillMut.isPending}
            onClick={() => backfillMut.mutate()}
            className="text-xs text-ink-faint hover:text-ink-dim disabled:opacity-50"
          >
            {backfillMut.isPending ? "取り込み中…" : "履歴を再構築(過去のコンディション・庭を取り込む)"}
          </button>
        </>
      )}
    </div>
  );
}
