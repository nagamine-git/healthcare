import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BecomingLoop } from "../lib/api";

const DIAGNOSIS: Record<BecomingLoop["diagnosis"], { label: string; tone: string }> = {
  flywheel_turning: {
    label: "フライホイールが回っています(動けた日に攻め、努力が盲点に向き、実際に前進)",
    tone: "text-emerald-400",
  },
  wasted_capacity: {
    label: "資本の浪費:コンディションが良い日に攻められていません",
    tone: "text-amber-400",
  },
  spinning: {
    label: "空回り:努力はしているが前進していません(行動の選択を見直す)",
    tone: "text-amber-400",
  },
  building: { label: "構築中:データを貯めています", tone: "text-slate-400" },
};

function pct(v: number | null): string {
  return v === null ? "—" : `${Math.round(v * 100)}%`;
}

function etaLabel(days: number | null): string {
  if (days === null) return "—(データ不足/到達経路が未確定)";
  if (days >= 60) return `約${Math.round(days / 30)}ヶ月`;
  return `約${days}日`;
}

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

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <button onClick={onBack} className="text-sm text-slate-400">
        ← 戻る
      </button>
      <h1 className="text-xl font-bold">becoming — 三層フライホイール</h1>
      {q.isLoading && <p>読み込み中…</p>}
      {q.isError && <p className="text-red-400">取得に失敗しました</p>}
      {q.data && loop && traj && (
        <>
          {/* フライホイール */}
          <div className="rounded-lg bg-slate-900 p-4">
            <p className="mb-3 text-sm text-slate-400">今週のフライホイール</p>
            <div className="grid grid-cols-3 gap-2 text-center">
              <Metric label="資本活用率" sub="動けた日に攻めたか" value={pct(loop.capacity_utilization)} />
              <Metric label="行動整合度" sub="努力が盲点に向いたか" value={pct(loop.action_alignment)} />
              <Metric
                label="前進量"
                sub="実際に近づいたか"
                value={loop.identity_movement === null ? "—" : loop.identity_movement.toFixed(1)}
              />
            </div>
            <p className={`mt-3 text-sm ${DIAGNOSIS[loop.diagnosis].tone}`}>
              {DIAGNOSIS[loop.diagnosis].label}
            </p>
          </div>

          {/* 今日の一手 */}
          <div className="rounded-lg bg-slate-900 p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm text-slate-400">今日の一手(盲点ねらい)</p>
              <button
                disabled={moveMut.isPending}
                onClick={() => moveMut.mutate()}
                className="rounded-full bg-emerald-700 px-3 py-1 text-xs hover:bg-emerald-600 disabled:opacity-50"
              >
                {moveMut.isPending ? "生成中…" : "生成"}
              </button>
            </div>
            {moveMut.data ? (
              <div className="space-y-1 text-sm">
                <p className="font-semibold">{moveMut.data.move}</p>
                <p className="text-emerald-300">if-then: {moveMut.data.if_then}</p>
                <p className="text-xs text-slate-500">{moveMut.data.rationale}</p>
                {moveMut.data.fallback && (
                  <p className="text-xs text-slate-600">(LLM未設定のため定型提案)</p>
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-500">「生成」で今日の高レバレッジな一手を作ります</p>
            )}
          </div>

          {/* North Star */}
          <div className="rounded-lg bg-slate-900 p-4">
            <p className="mb-2 text-sm text-slate-400">North Star — 理想プロファイル到達予測</p>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-bold text-emerald-400">{etaLabel(traj.eta_days)}</span>
              {traj.confidence === "low" && (
                <span className="text-xs text-amber-400">低信頼(スナップショット蓄積中)</span>
              )}
            </div>
            {traj.bottleneck_name && (
              <p className="mt-1 text-sm">
                <span className="text-slate-400">ボトルネック: </span>
                <span className="font-semibold">{traj.bottleneck_name}</span>
              </p>
            )}
            {traj.per_dimension.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-slate-400">
                {traj.per_dimension
                  .slice()
                  .sort(
                    (a, b) =>
                      (b.time_to_target_days ?? Infinity) - (a.time_to_target_days ?? Infinity),
                  )
                  .slice(0, 5)
                  .map((d) => (
                    <li key={d.id} className="flex justify-between">
                      <span>{d.name ?? d.id}</span>
                      <span className="tabular-nums">
                        {d.current === null ? "—" : Math.round(d.current)}/{d.target}
                        {d.time_to_target_days !== null && ` · ${etaLabel(d.time_to_target_days)}`}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </div>

          <button
            disabled={backfillMut.isPending}
            onClick={() => backfillMut.mutate()}
            className="text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
          >
            {backfillMut.isPending ? "取り込み中…" : "履歴を再構築(過去のコンディション・庭を取り込む)"}
          </button>
        </>
      )}
    </div>
  );
}

function Metric({ label, sub, value }: { label: string; sub: string; value: string }) {
  return (
    <div className="rounded bg-slate-800/60 p-2">
      <div className="text-lg font-bold text-emerald-400">{value}</div>
      <div className="text-[11px] text-slate-300">{label}</div>
      <div className="text-[9px] text-slate-500">{sub}</div>
    </div>
  );
}
