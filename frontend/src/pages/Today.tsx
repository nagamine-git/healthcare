import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { SubScoreRadar } from "../components/SubScoreRadar";
import { MetricTile } from "../components/MetricTile";
import { AdviceCard } from "../components/AdviceCard";
import { SyncStatus } from "../components/SyncStatus";
import { Sparkline } from "../components/Sparkline";

function formatMinutes(min: number | null): string {
  if (min == null) return "--";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}時間${m.toString().padStart(2, "0")}分`;
}

export function TodayPage() {
  const qc = useQueryClient();
  const today = useQuery({ queryKey: ["today"], queryFn: api.today });
  const scoreSeries = useQuery({
    queryKey: ["timeseries", "score"],
    queryFn: () => api.timeseries("score", 14),
  });
  const weightSeries = useQuery({
    queryKey: ["timeseries", "weight"],
    queryFn: () => api.timeseries("weight", 28),
  });
  const sleepSeries = useQuery({
    queryKey: ["timeseries", "sleep"],
    queryFn: () => api.timeseries("sleep_total_min", 14),
  });
  const hrvSeries = useQuery({
    queryKey: ["timeseries", "hrv"],
    queryFn: () => api.timeseries("hrv", 28),
  });

  const sync = useMutation({
    mutationFn: api.syncGarmin,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  const regenerate = useMutation({
    mutationFn: api.regenerateAdvice,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  const gcalStatus = useQuery({
    queryKey: ["gcal-status"],
    queryFn: api.gcalStatus,
    retry: false,
  });

  if (today.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        読み込み中...
      </div>
    );
  }
  if (today.isError || !today.data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-rose-400">
        取得に失敗しました: {(today.error as Error)?.message}
      </div>
    );
  }

  const data = today.data;
  const score = data.score;
  const reasons = data.sub_reasons ?? {};
  // ideal = そのサブスコアが最大に到達したときの値 (採点ロジックの上限)
  const subs = [
    { label: "睡眠", value: score?.sleep ?? null, ideal: 100, reason: reasons.sleep ?? undefined },
    { label: "自律神経", value: score?.hrv ?? null, ideal: 100, reason: reasons.hrv ?? undefined },
    { label: "エネルギー", value: score?.body_battery ?? null, ideal: 100, reason: reasons.body_battery ?? undefined },
    { label: "運動負荷", value: score?.load ?? null, ideal: 85, reason: reasons.load ?? undefined },
    { label: "体重", value: score?.weight ?? null, ideal: 80, reason: reasons.weight ?? undefined },
    { label: "体脂肪率", value: score?.body_fat ?? null, ideal: 90, reason: reasons.body_fat ?? undefined },
  ];

  const sleep = data.metrics.sleep;
  const hrv = data.metrics.hrv;
  const bb = data.metrics.body_battery;
  const summary = data.metrics.summary;
  const weight = data.metrics.weight;

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-4 sm:p-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-light tracking-wide text-slate-100">
          {data.date}
        </h1>
        <span className="text-xs text-slate-500">Healthcare Dashboard</span>
      </header>

      <AdviceCard
        advice={data.advice}
        onRegenerate={() => regenerate.mutate()}
        onSchedule={api.gcalSchedule}
        gcalConfigured={gcalStatus.data?.configured ?? false}
        pending={regenerate.isPending}
      />

      <SubScoreRadar subs={subs} total={score?.total ?? null} />

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <MetricTile
          label="睡眠"
          value={formatMinutes(sleep?.total_min ?? null)}
          hint={sleep?.sleep_score != null ? `スコア ${Math.round(sleep.sleep_score)}` : undefined}
        />
        <MetricTile
          label="HRV (心拍変動)"
          value={hrv?.last_night_avg != null ? `${Math.round(hrv.last_night_avg)} ms` : "--"}
          hint={hrv?.status ?? undefined}
        />
        <MetricTile
          label="エネルギー残量"
          value={bb?.current != null ? `${Math.round(bb.current)}` : bb?.morning != null ? `${Math.round(bb.morning)}` : "--"}
          hint={
            bb?.current != null && bb?.morning != null
              ? `朝 ${Math.round(bb.morning)} → 現在 ${Math.round(bb.current)}`
              : bb?.morning != null
              ? `朝の値 ${Math.round(bb.morning)}`
              : undefined
          }
        />
        <MetricTile
          label="安静時心拍"
          value={summary?.resting_hr != null ? `${Math.round(summary.resting_hr)} bpm` : "--"}
        />
        <MetricTile
          label="歩数"
          value={summary?.steps != null ? summary.steps.toLocaleString() : "--"}
          hint={summary?.active_kcal != null ? `${Math.round(summary.active_kcal)} kcal` : undefined}
        />
        <MetricTile
          label="体重"
          value={weight?.weight_kg != null ? `${weight.weight_kg.toFixed(1)} kg` : "--"}
          hint={weight?.ts ? `${new Date(weight.ts).toLocaleDateString()} 計測` : undefined}
        />
        <MetricTile
          label="体脂肪率"
          value={weight?.body_fat_pct != null ? `${weight.body_fat_pct.toFixed(1)}%` : "--"}
          hint={weight?.muscle_kg != null ? `除脂肪体重 ${weight.muscle_kg.toFixed(1)} kg` : undefined}
        />
      </section>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Sparkline
          label="総合スコア 14日"
          data={scoreSeries.data?.data ?? []}
          color="#34d399"
        />
        <Sparkline
          label="睡眠時間 14日"
          data={sleepSeries.data?.data ?? []}
          color="#60a5fa"
          formatter={(v) => formatMinutes(v)}
        />
        <Sparkline
          label="HRV 28日"
          data={hrvSeries.data?.data ?? []}
          color="#a78bfa"
          formatter={(v) => `${v.toFixed(0)} ms`}
        />
        <Sparkline
          label="体重 28日"
          data={weightSeries.data?.data ?? []}
          color="#f472b6"
          formatter={(v) => `${v.toFixed(1)} kg`}
        />
      </section>

      <SyncStatus
        sync={data.sync}
        onResync={() => sync.mutate()}
        pending={sync.isPending}
      />
    </main>
  );
}
