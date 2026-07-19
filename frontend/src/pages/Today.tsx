import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings as SettingsIcon } from "lucide-react";
import { api } from "../lib/api";
import { OverallScoreHero } from "../components/OverallScoreHero";
import { DayStory } from "../components/DayStory";
import { AdviceCard } from "../components/AdviceCard";
import { CheckinCard } from "../components/CheckinCard";
import { TrendsSection } from "../components/TrendsSection";
import { NutritionPanel } from "../components/NutritionPanel";
import { TonightPlanPanel } from "../components/TonightPlanPanel";
import { CaffeinePanel } from "../components/CaffeinePanel";
import { MigrainePanel } from "../components/MigrainePanel";
import { MedQuickLog } from "../components/MedQuickLog";
import { MigraineTriggerPanel } from "../components/MigraineTriggerPanel";
import { AlcoholPanel } from "../components/AlcoholPanel";
import { EnvironmentPanel } from "../components/EnvironmentPanel";
import { WeatherPanel } from "../components/WeatherPanel";
import { StaleBanner } from "../components/StaleBanner";
import { StatusLamps } from "../components/StatusLamps";
import { WellbeingAlertsBanner } from "../components/WellbeingAlertsBanner";
import { LearningCard } from "../components/LearningCard";
import { LifeSection } from "../components/LifeSection";
import { SettingsTab } from "../components/SettingsTab";
import { PhysiqueGapPlan } from "../components/PhysiqueGapPlan";
import { BodyCompositionPanel } from "../components/BodyCompositionPanel";
import { AtlasTree } from "../components/AtlasTree";
import { FitnessTestPanel, FitnessDueBanner } from "../components/FitnessTestPanel";
import { DistributionPanel } from "../components/DistributionPanel";
import { ActivitySignalCard } from "../components/ActivitySignalCard";
import { ScreenTimePanel } from "../components/ScreenTimePanel";
import { MealPlanner } from "../components/MealPlanner";
import { BodyLoadCard } from "../components/BodyLoadCard";
import { ImputedNotice } from "../components/ImputedNotice";
import { AirgapInsightCard } from "../components/AirgapInsightCard";
import { MentalCheckCard } from "../components/MentalCheckCard";
import { ScheduleCard } from "../components/ScheduleCard";
import { MigraineRiskBanner } from "../components/MigraineRiskBanner";
import { NextActionCard } from "../components/NextActionCard";
import { TrainingStatusStrip } from "../components/TrainingStatusStrip";
import { SleepDriverPanel } from "../components/SleepDriverPanel";
import { SleepInterventionCard } from "../components/SleepInterventionCard";
import { SleepInterventionHistory } from "../components/SleepInterventionHistory";
import { SleepInterventionPanel } from "../components/SleepInterventionPanel";
import { SyncMenu } from "../components/SyncMenu";
import { useEffect, useRef, useState } from "react";
import { SectionHeader, Skeleton } from "../components/ui/cockpit";
import { relativeMinutes, useTickingNow } from "../lib/relativeTime";
import { useGeolocation } from "../lib/geolocation";


type Props = {
  onOpenDebug?: () => void;
};

// ドメイン別タブ。設定は歯車アイコン (タブ外) から開く。
type Tab =
  | "summary" | "sleep" | "migraine" | "physique" | "health"
  | "learning" | "settings";
const TABS: { key: Tab; label: string }[] = [
  { key: "summary", label: "総合" },
  { key: "sleep", label: "睡眠" },
  { key: "migraine", label: "頭痛" },
  { key: "physique", label: "体型" },
  { key: "health", label: "健康" },
  { key: "learning", label: "学習" },
];

// "#tab-health" のようなハッシュで Today 内のタブへ直接飛べる (QuickLogSheet の食事導線等)
function tabFromHash(): Tab | null {
  const m = window.location.hash.match(/^#tab-(\w+)$/);
  const key = m?.[1] as Tab | undefined;
  return key && TABS.some((t) => t.key === key) ? key : null;
}

export function TodayPage({ onOpenDebug }: Props) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>(() => tabFromHash() ?? "summary");
  useEffect(() => {
    const handler = () => {
      const t = tabFromHash();
      if (t) setTab(t);
    };
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
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
      <main className="safe-area-x pb-nav mx-auto max-w-5xl space-y-3">
        <div aria-hidden className="status-bar-scrim" />
        <header className="safe-area-top flex items-center justify-between pb-1">
          <span className="text-sm font-semibold tracking-wider text-ink">Ascend</span>
          <span className="telemetry-label">読み込み中…</span>
        </header>
        <Skeleton className="h-9" />
        <Skeleton className="h-36" />
        <Skeleton className="h-28" />
        <Skeleton className="h-44" />
        <Skeleton className="h-24" />
      </main>
    );
  }
  if (today.isError || !today.data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-risk">
        取得に失敗しました: {(today.error as Error)?.message}
      </div>
    );
  }

  const data = today.data;

  const sleep = data.metrics.sleep;
  const hrv = data.metrics.hrv;
  const bb = data.metrics.body_battery;
  const summary = data.metrics.summary;
  const weight = data.metrics.weight;

  return (
    <main className="safe-area-x pb-nav mx-auto max-w-5xl space-y-4">
      <header className="safe-area-top flex items-center justify-between gap-2 pb-0.5">
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-bold tracking-tight text-ink">Ascend</span>
          {dataRefresh.isPending && <span className="text-[10px] text-prog-300">更新中…</span>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="whitespace-nowrap text-xs tabular-nums text-ink-faint">{data.date}</span>
          <button
            type="button"
            onClick={() => setTab(tab === "settings" ? "summary" : "settings")}
            aria-label="設定"
            title="設定"
            className={`rounded-lg p-1.5 transition-colors ${
              tab === "settings" ? "bg-panel text-ink" : "text-ink-dim hover:text-ink"
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

      {/* ===== 最上部: 総合点ヒーロー (全体マップ総合点に一本化・目標とセット) ===== */}
      <OverallScoreHero focus={data.focus} />

      {/* ===== 「今日」: いまコレ+やること / 今日の予定 / アラート(安全網) を1面に統合 ===== */}
      <div className="space-y-3">
        <SectionHeader label="今日" hint="いまコレ + やること + 予定 + アラート" />
        <NextActionCard />
        <ScheduleCard />
        {(data.alerts?.length ?? 0) > 0 && <WellbeingAlertsBanner alerts={data.alerts} />}
        <MigraineRiskBanner />
      </div>

      {/* ===== メニュー: セクション切替を最上部に固定(横スクロールのセグメント)===== */}
      <div className="sticky top-0 z-20 -mx-5 bg-void/75 px-5 py-2 backdrop-blur-xl">
        <div className="no-scrollbar flex gap-2 overflow-x-auto">
          {TABS.map((t) => (
            <button key={t.key} type="button" onClick={() => setTab(t.key)}
              className={`press shrink-0 rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors ${
                tab === t.key ? "bg-ink text-void" : "bg-hull text-ink-dim hover:text-ink"}`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ============ タブ: 総合 (サマリー) ============ */}
      {tab === "summary" && (
      <div className="space-y-3">
      {/* 状態ダッシュボード(赤黄緑ランプ)を最上部に */}
      <StatusLamps
        alerts={data.alerts}
        pressure={data.pressure}
        igniteSignal={data.last_data_update_at ?? data.date}
      />
      {/* 全体マップ(現状/世の中/目標・伸びしろ順)。旧「全体」タブを統合 */}
      <AtlasTree />

      <StaleBanner
        lastUpdateIso={data.last_data_update_at}
        isRefreshing={dataRefresh.isPending}
        onRefresh={() => dataRefresh.mutate()}
      />

      <div id="weather-section">
        <SectionHeader label="天気" hint="今日の天気・降水確率 + 週間予報" />
        <WeatherPanel />
      </div>
      <div id="alerts-section">
        <SectionHeader label="今日の指針" hint="アラート（安全網）+ 片頭痛リスク + LLM推奨アクション" />
        <div className="space-y-3">
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

      {/* 集中力はトップの総合点ヒーローにチップとして集約 (単独の大パネルは廃止) */}
      <SectionHeader label="いまの状態" hint="主観の調子 + 心の健康 + 環境" />
      <CheckinCard />
      <MentalCheckCard />
      <AirgapInsightCard />
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

      {/* 総合スコア(24hレーダー)は総合点ヒーロー + 各指標トレンドに一本化して廃止 */}
      <SectionHeader label="今日のスコア" hint="各指標のトレンド" />
      <ImputedNotice imputed={data.imputed} />
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
        <SectionHeader label="就寝前の介入 × 睡眠の質" hint="耳栓・アイマスク・鼻呼吸・口テープの効果をn-of-1検証" />
        <SleepInterventionCard />
        <SleepInterventionHistory />
        <SleepInterventionPanel />
        <SectionHeader label="睡眠ドライバー" hint="睡眠の質 × 翌日パフォーマンスの個人分析" />
        <SleepDriverPanel />
      </div>
      )}

      {/* ============ タブ: 頭痛 ============ */}
      {tab === "migraine" && (
      <div className="space-y-3">
        <SectionHeader label="片頭痛" hint="リスク・誘因分析・記録" />
        <MigraineRiskBanner />
        <MedQuickLog />
        <MigrainePanel />
        <MigraineTriggerPanel />
      </div>
      )}

      {/* ============ タブ: 体型 ============ */}
      {tab === "physique" && (
      <div id="physique-gap-section" className="space-y-3">
        <TrainingStatusStrip />
        <SectionHeader label="理想体型へのギャップ" hint="結局何をすべきか — エネルギー収支から逆算" />
        <PhysiqueGapPlan />
        <BodyCompositionPanel />
        <DistributionPanel />
        <BodyLoadCard />
        <FitnessTestPanel />
        <p className="px-1 text-[11px] text-ink-faint">
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
        <SectionHeader label="デジタル" hint="スマホ依存 — スクリーンタイムのスクショ取込" />
        <ScreenTimePanel />
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

// SectionHeader は ui/cockpit へ昇格 (全ページ共通)
