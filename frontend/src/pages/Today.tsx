import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { SubScoreRadar } from "../components/SubScoreRadar";
import { AdviceCard } from "../components/AdviceCard";
import { TrendsSection } from "../components/TrendsSection";
import { NutritionPanel } from "../components/NutritionPanel";
import { TonightPlanPanel } from "../components/TonightPlanPanel";
import { FocusPanel } from "../components/FocusPanel";
import { CaffeinePanel } from "../components/CaffeinePanel";
import { MigrainePanel } from "../components/MigrainePanel";
import { AlcoholPanel } from "../components/AlcoholPanel";
import { EnvironmentPanel } from "../components/EnvironmentPanel";
import { StaleBanner } from "../components/StaleBanner";
import { StatusLamps } from "../components/StatusLamps";
import { WellbeingAlertsBanner } from "../components/WellbeingAlertsBanner";
import { LifeSection } from "../components/LifeSection";
import { SyncMenu } from "../components/SyncMenu";
import { useEffect, useRef } from "react";
import { relativeMinutes, useTickingNow } from "../lib/relativeTime";
import { useGeolocation } from "../lib/geolocation";

function formatMinutes(min: number | null): string {
  if (min == null) return "--";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}時間${m.toString().padStart(2, "0")}分`;
}

function fmtNum(v: number | null | undefined): string {
  return v == null ? "--" : String(Math.round(v));
}


type Props = {
  onOpenDebug?: () => void;
};

export function TodayPage({ onOpenDebug }: Props) {
  const qc = useQueryClient();
  const geo = useGeolocation();
  const coords = geo.coords;
  const today = useQuery({
    queryKey: ["today", coords?.lat ?? null, coords?.lon ?? null],
    queryFn: () =>
      api.today(coords ? { lat: coords.lat, lon: coords.lon } : null),
  });

  const sync = useMutation({
    mutationFn: api.syncGarmin,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  const recompute = useMutation({
    mutationFn: api.recompute,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  const regenerate = useMutation({
    mutationFn: api.regenerateAdvice,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  const fullRefresh = useMutation({
    mutationFn: () => api.fullRefresh(true),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  const schedule = useMutation({
    mutationFn: api.gcalSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  const gcalStatus = useQuery({
    queryKey: ["gcal-status"],
    queryFn: api.gcalStatus,
    retry: false,
  });

  // ページ open 時、データが古ければ自動でフル更新
  // (last_data_update が 30 分以上前 / 未取得)
  const autoRefreshTriggeredRef = useRef(false);
  useEffect(() => {
    if (autoRefreshTriggeredRef.current) return;
    if (!today.data) return;
    const last = today.data.last_data_update_at;
    const stale =
      !last || Date.now() - new Date(last).getTime() > 30 * 60_000;
    if (stale && !fullRefresh.isPending) {
      autoRefreshTriggeredRef.current = true;
      fullRefresh.mutate();
    }
  }, [today.data, fullRefresh]);

  // 1 分ごとに「最終更新 N 分前」を再描画するため tick を取る
  const now = useTickingNow();

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
  const ctx = data.sub_context ?? {};
  const fmtSleep = ctx.sleep && ctx.sleep.current != null
    ? `${formatMinutes(ctx.sleep.current)} (推奨 ${formatMinutes(ctx.sleep.target.min ?? 420)}–${formatMinutes(ctx.sleep.target.max ?? 540)})`
    : undefined;
  const fmtHrv = ctx.hrv?.current != null ? `${Math.round(ctx.hrv.current)} ms` : undefined;
  const fmtBb =
    ctx.body_battery && (ctx.body_battery.current != null || ctx.body_battery.morning != null)
      ? `現在 ${fmtNum(ctx.body_battery.current)} (朝 ${fmtNum(ctx.body_battery.morning)})`
      : undefined;
  const fmtLoad = ctx.load?.acwr != null
    ? `ACWR ${ctx.load.acwr.toFixed(2)} (推奨 ${ctx.load.target.min}–${ctx.load.target.max})`
    : undefined;
  const fmtWeight = ctx.weight && ctx.weight.current != null
    ? `${ctx.weight.current.toFixed(1)} kg / 推奨 ${(ctx.weight.target.min ?? 0).toFixed(1)}–${(ctx.weight.target.max ?? 0).toFixed(1)} kg`
    : undefined;
  const fmtBf = ctx.body_fat && ctx.body_fat.current != null
    ? `${ctx.body_fat.current.toFixed(1)}% / 推奨 ${(ctx.body_fat.target.min ?? 0).toFixed(1)}–${(ctx.body_fat.target.max ?? 0).toFixed(1)}%`
    : undefined;

  const subs = [
    { label: "睡眠", value: score?.sleep ?? null, ideal: 100, reason: reasons.sleep ?? undefined, realWorld: fmtSleep },
    { label: "自律神経", value: score?.hrv ?? null, ideal: 100, reason: reasons.hrv ?? undefined, realWorld: fmtHrv },
    { label: "エネルギー", value: score?.body_battery ?? null, ideal: 100, reason: reasons.body_battery ?? undefined, realWorld: fmtBb },
    { label: "運動負荷", value: score?.load ?? null, ideal: 85, reason: reasons.load ?? undefined, realWorld: fmtLoad },
    { label: "体重", value: score?.weight ?? null, ideal: 80, reason: reasons.weight ?? undefined, realWorld: fmtWeight },
    { label: "体脂肪率", value: score?.body_fat ?? null, ideal: 90, reason: reasons.body_fat ?? undefined, realWorld: fmtBf },
  ];

  const sleep = data.metrics.sleep;
  const hrv = data.metrics.hrv;
  const bb = data.metrics.body_battery;
  const summary = data.metrics.summary;
  const weight = data.metrics.weight;

  return (
    <main className="safe-area-x safe-area-bottom mx-auto max-w-5xl space-y-6 px-4 pb-8 sm:px-8">
      <header className="safe-area-top flex items-center justify-between pb-2 pt-3">
        <div className="flex items-baseline gap-3">
          <span className="text-xs tracking-wider text-slate-300">Healthcare</span>
          <span className="text-[10px] tabular-nums text-slate-500">
            最終更新 {relativeMinutes(data.last_data_update_at, now)}
            {fullRefresh.isPending && <span className="ml-1 text-emerald-400">(更新中…)</span>}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs tabular-nums text-slate-500">{data.date}</span>
          <SyncMenu
            lastSyncedLabel={
              data.sync.garmin?.last_synced_at
                ? `Garmin: ${relativeMinutes(data.sync.garmin.last_synced_at, now)}`
                : undefined
            }
            items={[
              {
                label: "全部更新",
                description: "Garmin 同期 + スコア再計算 + アドバイス再生成",
                onClick: () => fullRefresh.mutate(),
                pending: fullRefresh.isPending,
              },
              {
                label: "Garmin だけ再取得",
                description: "Garmin Connect から最新データを取得",
                onClick: () => sync.mutate(),
                pending: sync.isPending,
              },
              {
                label: "スコア再計算",
                description: "本日のサブスコアと総合を更新",
                onClick: () => recompute.mutate(),
                pending: recompute.isPending,
              },
              {
                label: "アドバイス再生成",
                description: "Claude に最新データで助言を作り直してもらう",
                onClick: () => regenerate.mutate(),
                pending: regenerate.isPending,
              },
              {
                label: gcalStatus.data?.configured ? "Calendar に追加" : "Calendar 未連携",
                description: "推奨アクションを Google Calendar にイベント化",
                onClick: () => gcalStatus.data?.configured && schedule.mutate(),
                pending: schedule.isPending,
                hidden: !gcalStatus.data?.configured,
              },
              {
                label: "Debug ビュー",
                description: "ソース別の生データを確認",
                onClick: () => onOpenDebug?.(),
                hidden: !onOpenDebug,
              },
            ]}
          />
        </div>
      </header>

      {/* ===== 🚥 計器盤ランプ (ファーストビューの状態一覧) ===== */}
      <StatusLamps
        alerts={data.alerts}
        pressure={data.pressure}
        igniteSignal={data.last_data_update_at ?? data.date}
      />

      <StaleBanner
        lastUpdateIso={data.last_data_update_at}
        isRefreshing={fullRefresh.isPending}
        onRefresh={() => fullRefresh.mutate()}
      />

      {/* ===== ⚠️ アラート ===== */}
      <div id="alerts-section">
        <WellbeingAlertsBanner alerts={data.alerts} />
      </div>

      {/* ===== 🌱 ライフスコア (自己目標管理) ===== */}
      <div id="life-section">
        <SectionHeader label="ライフスコア" hint="理想への総合接近度 + 重み調整" />
        <LifeSection />
      </div>

      {/* ===== 🎯 今日のアクション ===== */}
      <SectionHeader label="今日のアクション" hint="LLM が状況を統合して 3 件まで" />
      <AdviceCard
        advice={data.advice}
        onRegenerate={() => regenerate.mutate()}
        onSchedule={api.gcalSchedule}
        gcalConfigured={gcalStatus.data?.configured ?? false}
        pending={regenerate.isPending}
      />

      {/* ===== 📊 今の状態 ===== */}
      <SectionHeader label="いまの状態" hint="リアルタイムの集中力 + 環境" />
      <FocusPanel focus={data.focus} />
      <EnvironmentPanel
        pressure={data.pressure}
        airQuality={data.air_quality}
        morningLight={data.morning_light}
        geo={{
          coords: geo.coords,
          busy: geo.busy,
          error: geo.error,
          denied: geo.denied,
          onRequest: geo.request,
          onClear: geo.clear,
        }}
      />

      {/* ===== 📈 今日のスコア (24h 振り返り) ===== */}
      <SectionHeader label="今日のスコア" hint="24 時間の振り返り" />
      <SubScoreRadar subs={subs} total={score?.total ?? null} />

      {/* ===== 📈 トレンド (理想への接近度 + 今の各メトリクス) ===== */}
      <div id="trends-section">
      <TrendsSection
        hints={{
          sleep: sleep?.sleep_score != null ? `スコア ${Math.round(sleep.sleep_score)}` : undefined,
          hrv: hrv?.status ?? undefined,
          energy:
            bb?.current != null && bb?.morning != null
              ? `朝 ${Math.round(bb.morning)} → 現在 ${Math.round(bb.current)}`
              : bb?.morning != null
              ? `朝の値 ${Math.round(bb.morning)}`
              : undefined,
          weight: weight?.ts ? `${new Date(weight.ts).toLocaleDateString()} 計測` : undefined,
          body_fat:
            weight?.muscle_kg != null ? `除脂肪体重 ${weight.muscle_kg.toFixed(1)} kg` : undefined,
        }}
        extras={[
          {
            label: "歩数",
            value: summary?.steps != null ? summary.steps.toLocaleString() : "--",
            hint: summary?.active_kcal != null ? `${Math.round(summary.active_kcal)} kcal` : undefined,
          },
          {
            label: "安静時心拍",
            value: summary?.resting_hr != null ? `${Math.round(summary.resting_hr)} bpm` : "--",
          },
        ]}
      />
      </div>

      <NutritionPanel nutrition={data.nutrition} />
      <TonightPlanPanel plan={data.tonight_plan} />

      {/* ===== 📝 記録 (折りたたみ可) ===== */}
      <SectionHeader label="記録" hint="飲んだ/痛くなった時に開いて入力" />
      <CaffeinePanel caffeine={data.caffeine} />
      <MigrainePanel />
      <AlcoholPanel />

    </main>
  );
}

function SectionHeader({ label, hint }: { label: string; hint?: string }) {
  return (
    <div className="mt-2 flex items-baseline gap-3 border-b border-slate-800 pb-1">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </h2>
      {hint && <span className="text-[10px] text-slate-600">{hint}</span>}
    </div>
  );
}
