import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Compass as CompassIcon, Settings as SettingsIcon } from "lucide-react";
import { api, type GardenGridCell } from "../lib/api";
import { gardenCellStyle } from "../lib/gardenColor";
import { SubScoreRadar } from "../components/SubScoreRadar";
import { DayStory } from "../components/DayStory";
import { AdviceCard } from "../components/AdviceCard";
import { CheckinCard } from "../components/CheckinCard";
import { TrendsSection } from "../components/TrendsSection";
import { NutritionPanel } from "../components/NutritionPanel";
import { TonightPlanPanel } from "../components/TonightPlanPanel";
import { FocusPanel } from "../components/FocusPanel";
import { CaffeinePanel } from "../components/CaffeinePanel";
import { MigrainePanel } from "../components/MigrainePanel";
import { MigraineTriggerPanel } from "../components/MigraineTriggerPanel";
import { AlcoholPanel } from "../components/AlcoholPanel";
import { EnvironmentPanel } from "../components/EnvironmentPanel";
import { WeatherPanel } from "../components/WeatherPanel";
import { StaleBanner } from "../components/StaleBanner";
import { StatusLamps } from "../components/StatusLamps";
import { WellbeingAlertsBanner } from "../components/WellbeingAlertsBanner";
import { DayPrediction } from "../components/DayPrediction";
import { LearningCard } from "../components/LearningCard";
import { LifeSection } from "../components/LifeSection";
import { SettingsTab } from "../components/SettingsTab";
import { PhysiqueGapPlan } from "../components/PhysiqueGapPlan";
import { FitnessTestPanel, FitnessDueBanner } from "../components/FitnessTestPanel";
import { DistributionPanel } from "../components/DistributionPanel";
import { ActivitySignalCard } from "../components/ActivitySignalCard";
import { MealPlanner } from "../components/MealPlanner";
import { BodyLoadCard } from "../components/BodyLoadCard";
import { ImputedNotice } from "../components/ImputedNotice";
import { MigraineRiskBanner } from "../components/MigraineRiskBanner";
import { SleepDriverPanel } from "../components/SleepDriverPanel";
import { SyncMenu } from "../components/SyncMenu";
import { useEffect, useRef, useState } from "react";
import { TodaySummary } from "../components/TodaySummary";
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

// ドメイン別タブ。設定は歯車アイコン (タブ外) から開く。
type Tab = "summary" | "sleep" | "migraine" | "physique" | "health" | "learning" | "settings";
const TABS: { key: Tab; label: string }[] = [
  { key: "summary", label: "総合" },
  { key: "sleep", label: "睡眠" },
  { key: "migraine", label: "頭痛" },
  { key: "physique", label: "体型" },
  { key: "health", label: "健康" },
  { key: "learning", label: "学習" },
];

export function TodayPage({ onOpenDebug }: Props) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("summary");
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
  const adviceFeedback = useMutation({
    mutationFn: api.adviceFeedback,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["today"] }),
  });
  // データのみ更新 (Garmin同期+スコア再計算)。LLM助言は再生成しない=無駄遣い防止。
  // 助言は朝の cron + 明示「アドバイス再生成」でのみ作る (遅延動作)。
  const dataRefresh = useMutation({
    mutationFn: () => api.fullRefresh(false),
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
  const gardenQ = useQuery({ queryKey: ["garden"], queryFn: api.garden, retry: false });

  // ページ open 時、データが古ければ自動でフル更新
  // (last_data_update が 30 分以上前 / 未取得)
  const autoRefreshTriggeredRef = useRef(false);
  useEffect(() => {
    if (autoRefreshTriggeredRef.current) return;
    if (!today.data) return;
    const last = today.data.last_data_update_at;
    const stale =
      !last || Date.now() - new Date(last).getTime() > 30 * 60_000;
    if (stale && !dataRefresh.isPending) {
      autoRefreshTriggeredRef.current = true;
      dataRefresh.mutate();  // 自動更新はデータのみ (LLM助言は焼かない)
    }
  }, [today.data, dataRefresh]);

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
    <main className="safe-area-x safe-area-bottom mx-auto max-w-5xl space-y-6">
      <header className="safe-area-top flex items-center justify-between pb-2">
        <div className="flex items-baseline gap-3">
          <span className="text-xs tracking-wider text-slate-300">Healthcare</span>
          <span className="text-[10px] tabular-nums text-slate-500">
            最終更新 {relativeMinutes(data.last_data_update_at, now)}
            {dataRefresh.isPending && <span className="ml-1 text-emerald-400">(更新中…)</span>}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs tabular-nums text-slate-500">{data.date}</span>
          <button
            type="button"
            onClick={() => (window.location.hash = "#identity")}
            aria-label="Compass"
            title="Compass (価値観×マインドセット)"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:text-slate-200"
          >
            <CompassIcon size={16} />
          </button>
          <button
            type="button"
            onClick={() => (window.location.hash = "#garden")}
            aria-label="理想の庭"
            title="理想の庭 (ゲーミフィケーション)"
            className="rounded-lg p-1.5 text-base leading-none text-slate-400 transition-colors hover:text-slate-200"
          >
            🌱
          </button>
          <button
            type="button"
            onClick={() => setTab(tab === "settings" ? "summary" : "settings")}
            aria-label="設定"
            title="設定"
            className={`rounded-lg p-1.5 transition-colors ${
              tab === "settings" ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <SettingsIcon size={16} />
          </button>
          <SyncMenu
            lastSyncedLabel={
              data.sync.garmin?.last_synced_at
                ? `Garmin: ${relativeMinutes(data.sync.garmin.last_synced_at, now)}`
                : undefined
            }
            items={[
              {
                label: "更新",
                description: "Garmin 同期 + スコア再計算 (LLM助言は焼かない)",
                onClick: () => dataRefresh.mutate(),
                pending: dataRefresh.isPending,
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
                label: "Compass (価値観×マインド)",
                description: "理想とのギャップと作品による介入",
                onClick: () => (window.location.hash = "#identity"),
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

      {/* ===== ファーストビュー: 計器盤ランプ + 今の要点サマリ (常設) ===== */}
      <StatusLamps
        alerts={data.alerts}
        pressure={data.pressure}
        igniteSignal={data.last_data_update_at ?? data.date}
      />
      <TodaySummary
        total={score?.total ?? null}
        headline={data.advice?.payload?.headline}
        subs={[
          { label: "睡眠", value: score?.sleep ?? null },
          { label: "自律神経", value: score?.hrv ?? null },
          { label: "エネルギー", value: score?.body_battery ?? null },
        ]}
      />
      <StaleBanner
        lastUpdateIso={data.last_data_update_at}
        isRefreshing={dataRefresh.isPending}
        onRefresh={() => dataRefresh.mutate()}
      />

      {gardenQ.data && (
        <button
          type="button"
          onClick={() => (window.location.hash = "#garden")}
          className="w-full rounded-xl bg-slate-900/70 p-3 text-left transition-colors hover:bg-slate-900"
        >
          <div className="mb-2 flex items-baseline justify-between">
            <span className="text-xs tracking-wider text-slate-400">🌱 理想の庭</span>
            <span className="text-sm font-bold text-emerald-400">
              {gardenQ.data.streak}日連続
            </span>
          </div>
          <div className="flex gap-[2px]">
            {gardenQ.data.grid.slice(-84).map((c: GardenGridCell) => {
              const style = gardenCellStyle(c.level, c.focus);
              return (
                <div
                  key={c.date}
                  style={style ?? undefined}
                  className={`h-2 w-2 rounded-sm ${style ? "" : "bg-slate-800"}`}
                />
              );
            })}
          </div>
        </button>
      )}

      {/* ===== タブナビ (sticky) ===== */}
      <div className="sticky top-0 z-20 -mx-1 bg-slate-950/80 py-1 backdrop-blur">
        <div className="flex gap-1 rounded-xl bg-slate-900/70 p-1">
          {TABS.map((t) => (
            <button key={t.key} type="button" onClick={() => setTab(t.key)}
              className={`flex-1 rounded-lg py-1.5 text-[12px] font-medium transition-colors ${
                tab === t.key ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:text-slate-200"}`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ============ タブ: 総合 (サマリー) ============ */}
      {tab === "summary" && (
      <div className="space-y-3">
      <div id="weather-section">
        <SectionHeader label="天気" hint="今日の天気・降水確率 + 週間予報" />
        <WeatherPanel />
      </div>
      <div id="alerts-section">
        <SectionHeader label="今日の指針" hint="アラート（安全網）+ 片頭痛リスク + LLM推奨アクション" />
        <div className="space-y-3">
          <DayPrediction />
          <WellbeingAlertsBanner alerts={data.alerts} />
          <MigraineRiskBanner />
          <FitnessDueBanner onOpen={() => setTab("physique")} />
          <AdviceCard
            advice={data.advice}
            onRegenerate={() => regenerate.mutate()}
            onSchedule={api.gcalSchedule}
            onFeedback={(patch) => adviceFeedback.mutate(patch)}
            gcalConfigured={gcalStatus.data?.configured ?? false}
            pending={regenerate.isPending}
          />
        </div>
      </div>

      <div id="timeline-section">
        <SectionHeader label="今日の流れ" hint="直近24h / 今日を切替・予測込み" />
        <DayStory />
      </div>

      <SectionHeader label="いまの状態" hint="主観の調子 + 集中力 + 環境" />
      <CheckinCard />
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

      <SectionHeader label="今日のスコア" hint="24 時間の振り返り + トレンド" />
      <ImputedNotice imputed={data.imputed} />
      <SubScoreRadar subs={subs} total={score?.total ?? null} />
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
      </div>
      )}

      {/* ============ タブ: 睡眠 ============ */}
      {tab === "sleep" && (
      <div className="space-y-3">
        <SectionHeader label="今夜の計画" hint="起床から逆算した就寝・入浴・夕食の目安" />
        <TonightPlanPanel plan={data.tonight_plan} />
        <SectionHeader label="睡眠ドライバー" hint="睡眠の質 × 翌日パフォーマンスの個人分析" />
        <SleepDriverPanel />
      </div>
      )}

      {/* ============ タブ: 頭痛 ============ */}
      {tab === "migraine" && (
      <div className="space-y-3">
        <SectionHeader label="片頭痛" hint="リスク・誘因分析・記録" />
        <MigraineRiskBanner />
        <MigrainePanel />
        <MigraineTriggerPanel />
      </div>
      )}

      {/* ============ タブ: 体型 ============ */}
      {tab === "physique" && (
      <div id="physique-gap-section" className="space-y-3">
        <SectionHeader label="理想体型へのギャップ" hint="結局何をすべきか — エネルギー収支から逆算" />
        <PhysiqueGapPlan />
        <DistributionPanel />
        <BodyLoadCard />
        <FitnessTestPanel />
        <p className="px-1 text-[11px] text-slate-500">
          目標体型・体組成は歯車（設定）の身体セクションで調整できます。
        </p>
      </div>
      )}

      {/* ============ タブ: 健康 (栄養/嗜好品) ============ */}
      {tab === "health" && (
      <div className="space-y-3">
        <SectionHeader label="栄養" hint="カロリー収支・マクロ・食事プラン" />
        <NutritionPanel nutrition={data.nutrition} />
        <MealPlanner />
        <SectionHeader label="嗜好品の記録" hint="カフェイン / アルコール" />
        <CaffeinePanel caffeine={data.caffeine} />
        <AlcoholPanel />
        <SectionHeader label="活動・外出" hint="Garmin / iPhone を相互補完して推測 (欠損は不明)" />
        <ActivitySignalCard />
      </div>
      )}

      {/* ============ タブ: 学習 ============ */}
      {tab === "learning" && (
      <div className="space-y-3">
      <div id="life-section">
        <SectionHeader label="ライフスコア" hint="理想への総合接近度 + 重み調整" />
        <LifeSection />
      </div>
      <div id="learning-section">
        <SectionHeader label="学習" hint="The Book 完走プラン — 読了 / Rustlings / 説明できた の3点クリア" />
        <LearningCard />
      </div>
      </div>
      )}

      {/* ============ 設定 (歯車アイコンから) ============ */}
      {tab === "settings" && (
      <div className="space-y-3">
        <SectionHeader label="個人差ファクター" hint="計算に効く体質・生活パラメータを自己最適化" />
        <SettingsTab
          current={
            weight?.weight_kg != null && weight?.body_fat_pct != null
              ? { weight: weight.weight_kg, bf: weight.body_fat_pct }
              : null
          }
        />
      </div>
      )}

    </main>
  );
}

function SectionHeader({ label, hint }: { label: string; hint?: string }) {
  return (
    <div className="mb-3 mt-2 flex items-baseline gap-3 border-b border-slate-800 pb-1.5">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </h2>
      {hint && <span className="text-[10px] text-slate-500">{hint}</span>}
    </div>
  );
}
