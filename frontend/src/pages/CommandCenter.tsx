import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type BecomingLoop, type GardenGridCell, type WellbeingAlert } from "../lib/api";
import { gardenCellStyle } from "../lib/gardenColor";
import { BarGauge, Button, Panel, Pill, RingGauge, Stat } from "../components/ui/cockpit";

const DIAGNOSIS: Record<BecomingLoop["diagnosis"], { short: string; tone: "prog" | "act" | "neutral" }> = {
  flywheel_turning: { short: "回っている", tone: "prog" },
  wasted_capacity: { short: "資本の浪費", tone: "act" },
  spinning: { short: "空回り", tone: "act" },
  building: { short: "構築中", tone: "neutral" },
};

function etaLabel(days: number | null): string {
  if (days === null) return "—";
  if (days >= 60) return `${Math.round(days / 30)}ヶ月`;
  return `${days}日`;
}

function go(hash: string) {
  window.location.hash = hash;
}

export function CommandCenter({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const today = useQuery({ queryKey: ["today"], queryFn: () => api.today(null), retry: false });
  const becoming = useQuery({ queryKey: ["becoming"], queryFn: api.becoming, retry: false });
  const garden = useQuery({ queryKey: ["garden"], queryFn: api.garden, retry: false });
  const moveMut = useMutation({ mutationFn: () => api.becomingOneMove() });

  const score = today.data?.score ?? null;
  const alerts = (today.data?.alerts ?? []).filter((a) => a.severity !== "info");
  const loop = becoming.data?.loop_week;
  const traj = becoming.data?.trajectory;
  const diag = loop ? DIAGNOSIS[loop.diagnosis] : null;

  return (
    <main className="safe-area-x safe-area-bottom mx-auto max-w-2xl space-y-3">
      <div aria-hidden className="status-bar-scrim" />

      {/* トップバー */}
      <header className="safe-area-top flex items-center justify-between pb-1">
        <div className="flex items-baseline gap-2">
          <span className="telemetry-num text-sm font-bold tracking-[0.2em] text-ink">COCKPIT</span>
          <span className="telemetry-label">{today.data?.date ?? ""}</span>
        </div>
        <button
          onClick={onOpenSettings}
          className="telemetry-label hover:text-ink"
          aria-label="設定・詳細"
        >
          詳細 ›
        </button>
      </header>

      {/* アラート(critical/warning のみ) */}
      {alerts.map((a: WellbeingAlert) => (
        <div
          key={a.code}
          className={`rounded-lg border px-3 py-2 text-sm ${
            a.severity === "critical" ? "border-risk/60 text-risk" : "border-act-700 text-act-300"
          }`}
        >
          <span className="font-semibold">{a.title}</span>
          <span className="ml-2 text-ink-dim">{a.action}</span>
        </div>
      ))}

      {/* ===== signature: プライマリ・ディスプレイ ===== */}
      <Panel onClick={() => go("#today")}>
        <div className="flex items-center gap-5">
          <RingGauge value={score?.total ?? null} label="CONDITION" tone="prog" />
          <div className="flex-1 space-y-2.5">
            <BarGauge label="SLEEP" value={score?.sleep ?? null} />
            <BarGauge label="AUTONOMIC" value={score?.hrv ?? null} />
            <BarGauge label="ENERGY" value={score?.body_battery ?? null} />
          </div>
        </div>
        {today.data?.advice?.payload?.headline && (
          <p className="mt-3 border-t border-hairline pt-2 text-sm text-ink-dim">
            {today.data.advice.payload.headline}
          </p>
        )}
      </Panel>

      {/* ===== 今日の一手(amber CTA)===== */}
      <Panel
        title="TODAY'S ONE MOVE"
        glow="act"
        action={
          <Button variant="primary" disabled={moveMut.isPending} onClick={() => moveMut.mutate()}>
            {moveMut.isPending ? "生成中…" : "生成"}
          </Button>
        }
      >
        {moveMut.data ? (
          <div className="space-y-1">
            <p className="text-base font-semibold text-ink">{moveMut.data.move}</p>
            <p className="text-sm text-act-300">if-then: {moveMut.data.if_then}</p>
            <p className="text-xs text-ink-faint">{moveMut.data.rationale}</p>
          </div>
        ) : (
          <p className="text-sm text-ink-faint">
            盲点に効く、今日いちばんの一手を生成します。
          </p>
        )}
      </Panel>

      {/* ===== フライホイール + North Star(横並び)===== */}
      <div className="grid grid-cols-2 gap-3">
        <Panel title="FLYWHEEL" onClick={() => go("#becoming")}>
          {loop && diag ? (
            <>
              <div className="flex items-center gap-2">
                <FlywheelMark turning={loop.diagnosis === "flywheel_turning"} />
                <Pill tone={diag.tone}>{diag.short}</Pill>
              </div>
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

      {/* ===== 庭(行動の積み上げ)===== */}
      <Panel
        title="GARDEN"
        onClick={() => go("#garden")}
        action={
          garden.data ? (
            <span className="telemetry-num text-sm font-bold text-prog-300">
              {garden.data.streak}日連続
            </span>
          ) : undefined
        }
      >
        {garden.data ? (
          <div className="flex gap-[2px]">
            {garden.data.grid.slice(-96).map((c: GardenGridCell) => {
              const style = gardenCellStyle(c.level, c.focus);
              return (
                <div
                  key={c.date}
                  style={style ?? undefined}
                  className={`h-2 w-2 rounded-sm ${style ? "" : "bg-panel"}`}
                />
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-ink-faint">—</p>
        )}
      </Panel>

      {/* ナビ */}
      <nav className="grid grid-cols-4 gap-2 pt-1">
        <NavTile label="今日" hash="#today" />
        <NavTile label="庭" hash="#garden" />
        <NavTile label="Compass" hash="#identity" />
        <NavTile label="becoming" hash="#becoming" />
      </nav>
    </main>
  );
}

function pct(v: number | null): string {
  return v === null ? "—" : `${Math.round(v * 100)}`;
}

function FlywheelMark({ turning }: { turning: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" className={turning ? "flywheel-turning" : ""}>
      <circle cx="9" cy="9" r="7" fill="none" stroke="#243044" strokeWidth="2" />
      <path
        d="M9 2 a7 7 0 0 1 7 7"
        fill="none"
        stroke={turning ? "#10b981" : "#5b6675"}
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function NavTile({ label, hash }: { label: string; hash: string }) {
  return (
    <button
      onClick={() => go(hash)}
      className="rounded-lg border border-hairline bg-hull py-2 text-xs text-ink-dim transition-colors hover:border-ink-faint hover:text-ink"
    >
      {label}
    </button>
  );
}
