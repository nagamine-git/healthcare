import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type SubScores } from "../lib/api";
import { DIAGNOSIS, etaLabel, pct } from "../lib/becomingDisplay";
import { KIND_LABEL } from "../lib/labels";
import { BarGauge, Button, Panel, Pill, RingGauge, Stat } from "./ui/cockpit";

function go(hash: string) {
  window.location.hash = hash;
}

/** Today の最上部に載るコックピットのヒーロー: プライマリ・ディスプレイ + 今日の一手 + becoming 要約。 */
export function CockpitHero({ score, headline }: { score: SubScores | null; headline?: string }) {
  const becoming = useQuery({ queryKey: ["becoming"], queryFn: api.becoming, retry: false });
  const moveMut = useMutation({ mutationFn: () => api.becomingOneMove() });
  const loop = becoming.data?.loop_week;
  const traj = becoming.data?.trajectory;
  const diag = loop ? DIAGNOSIS[loop.diagnosis] : null;

  return (
    <div className="space-y-3">
      {/* 今日の一手(=結局これをやる。最上部・最も目立たせる) */}
      <Panel
        title="今日やること"
        glow="act"
        action={
          <Button variant="primary" disabled={moveMut.isPending} onClick={() => moveMut.mutate()}>
            {moveMut.isPending ? "生成中…" : moveMut.data ? "再生成" : "決める"}
          </Button>
        }
      >
        {moveMut.data ? (
          <div className="space-y-1">
            <p className="text-lg font-semibold leading-snug text-ink">{moveMut.data.move}</p>
            <p className="text-sm text-act-300">if-then: {moveMut.data.if_then}</p>
            <p className="text-xs text-ink-faint">{moveMut.data.rationale}</p>
          </div>
        ) : (
          <p className="text-sm text-ink-dim">
            「決める」を押すと、盲点に効く今日いちばんの一手が出ます。
          </p>
        )}
        {/* 手札: 他に取りうる行動(控えめに)。タップで記録画面へ。 */}
        <div className="mt-3 border-t border-hairline pt-2">
          <span className="telemetry-label">他の手札</span>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {Object.entries(KIND_LABEL).map(([kind, label]) => (
              <button
                key={kind}
                onClick={() => go("#garden")}
                className="rounded-full border border-hairline px-2 py-0.5 text-[11px] text-ink-faint transition-colors hover:border-ink-faint hover:text-ink-dim"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </Panel>

      {/* プライマリ・ディスプレイ(コンディション) */}
      <Panel onClick={() => go("#today")}>
        <div className="flex items-center gap-5">
          <RingGauge value={score?.total ?? null} label="CONDITION" tone="prog" />
          <div className="flex-1 space-y-2.5">
            <BarGauge label="SLEEP" value={score?.sleep ?? null} />
            <BarGauge label="AUTONOMIC" value={score?.hrv ?? null} />
            <BarGauge label="ENERGY" value={score?.body_battery ?? null} />
          </div>
        </div>
        {headline && (
          <p className="mt-3 border-t border-hairline pt-2 text-sm text-ink-dim">{headline}</p>
        )}
      </Panel>

      {/* フライホイール + North Star */}
      <div className="grid grid-cols-2 gap-3">
        <Panel title="FLYWHEEL" onClick={() => go("#becoming")}>
          {loop && diag ? (
            <>
              <Pill tone={diag.tone}>{diag.short}</Pill>
              <div className="mt-2 grid grid-cols-3 gap-1 text-center">
                <Stat size="sm" label="活用" value={pct(loop.capacity_utilization)} />
                <Stat size="sm" label="整合" value={pct(loop.action_alignment)} />
                <Stat
                  size="sm"
                  label="前進"
                  tone={loop.identity_movement && loop.identity_movement > 0 ? "prog" : "neutral"}
                  value={loop.identity_movement === null ? "—" : loop.identity_movement.toFixed(1)}
                />
              </div>
            </>
          ) : (
            <p className="text-sm text-ink-faint">構築中</p>
          )}
        </Panel>
        <Panel title="NORTH STAR" onClick={() => go("#becoming")}>
          {traj ? (
            <>
              <Stat
                size="lg"
                value={etaLabel(traj.eta_days)}
                tone="prog"
                delta={traj.confidence === "low" ? "低信頼(蓄積中)" : undefined}
              />
              {traj.bottleneck_name && (
                <p className="mt-1 text-xs text-ink-dim">
                  壁: <span className="text-ink">{traj.bottleneck_name}</span>
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
