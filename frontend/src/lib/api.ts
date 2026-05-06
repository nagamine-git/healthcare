export type SubScores = {
  total: number | null;
  sleep: number | null;
  hrv: number | null;
  body_battery: number | null;
  load: number | null;
  weight: number | null;
  body_fat: number | null;
  version?: string;
  computed_at?: string | null;
};

export type SleepMetric = {
  total_min: number | null;
  deep_min: number | null;
  rem_min: number | null;
  light_min: number | null;
  awake_min: number | null;
  sleep_score: number | null;
  source: string;
};

export type HrvMetric = {
  last_night_avg: number | null;
  weekly_avg: number | null;
  status: string | null;
};

export type BodyBatteryMetric = {
  max: number | null;
  min: number | null;
  morning: number | null;
  end_of_day: number | null;
  current: number | null;
  current_ts: string | null;
};

export type SummaryMetric = {
  steps: number | null;
  active_kcal: number | null;
  resting_hr: number | null;
  vo2max: number | null;
  training_status: string | null;
};

export type WeightMetric = {
  weight_kg: number | null;
  body_fat_pct: number | null;
  muscle_kg: number | null;
  ts: string | null;
};

export type AdvicePriority = "critical" | "high" | "mid" | "low";

export type AdviceAction = {
  time_jst: string; // HH:MM
  title: string;
  duration_min: number;
  category:
    | "training"
    | "cardio"
    | "recovery"
    | "mobility"
    | "nutrition"
    | "rest"
    | "other";
  priority: AdvicePriority;
  intensity?: string;
  why?: string;
};

export type AdvicePayload = {
  headline?: string;
  focus: string;
  actions: AdviceAction[];
  rationale: string;
};

export type Advice = {
  comment: string;
  model: string;
  generated_at: string | null;
  payload: AdvicePayload | null;
};

export type SyncStatus = {
  last_synced_at: string | null;
  last_error: string | null;
};

export type SubReasons = Partial<Record<
  "sleep" | "hrv" | "body_battery" | "load" | "weight" | "body_fat",
  string | null
>>;

export type DataSources = Partial<Record<
  "sleep" | "hrv" | "body_battery" | "summary" | "weight",
  string | null
>>;

export type NutritionField = {
  value: number | null;
  estimated: boolean;
  today_actual: number | null;
  avg_14d: number | null;
};

export type TargetRange = {
  min: number | null;
  ideal: number | null;
  max: number | null;
  unit: string;
  /** "range": min-max 内が良い / "minimum": ideal 以上が良い / "exact": ideal 一点 */
  kind: "range" | "minimum" | "exact" | "baseline_relative";
};

export type Nutrition = {
  tdee: NutritionField & {
    bmr?: number;
    active_kcal_today?: number | null;
    active_kcal_avg_14d?: number | null;
  };
  kcal_intake: NutritionField;
  protein_g: NutritionField;
  fat_g: NutritionField;
  carb_g: NutritionField;
  water_ml: NutritionField;
  fiber_g?: NutritionField;
  sugar_g?: NutritionField;
  sodium_mg?: NutritionField;
  targets: {
    kcal_intake: TargetRange | null;
    protein_g: TargetRange;
    fat_g: TargetRange;
    carb_g: TargetRange;
    water_ml: TargetRange;
    fiber_g?: TargetRange;
    sugar_g?: TargetRange;
    sodium_mg?: TargetRange;
  };
  logged_today: boolean;
};

export type SubContextEntry = {
  current: number | null;
  target: TargetRange;
  /** 任意の追加メトリクス */
  weekly_avg?: number | null;
  morning?: number | null;
  acute?: number | null;
  chronic?: number | null;
  acwr?: number | null;
};

export type SubContext = {
  sleep?: SubContextEntry;
  hrv?: SubContextEntry;
  body_battery?: SubContextEntry;
  load?: SubContextEntry;
  weight?: SubContextEntry;
  body_fat?: SubContextEntry;
};

export type TodayResponse = {
  date: string;
  score: SubScores | null;
  sub_reasons?: SubReasons;
  data_sources?: DataSources;
  sub_context?: SubContext;
  metrics: {
    sleep: SleepMetric | null;
    hrv: HrvMetric | null;
    body_battery: BodyBatteryMetric | null;
    summary: SummaryMetric | null;
    weight: WeightMetric | null;
  };
  nutrition?: Nutrition;
  advice: Advice | null;
  sync: Record<string, SyncStatus>;
};

export type TimeseriesPoint = { date: string; value: number | null };
export type TimeseriesResponse = {
  metric: string;
  from: string;
  to: string;
  data: TimeseriesPoint[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as T;
}

export type GcalStatus = { configured: boolean; reason?: string };
export type GcalScheduleResult = {
  date: string;
  created: Array<{
    id: string;
    htmlLink: string;
    summary: string;
    start: string;
    end: string;
  }>;
};

export type DebugSources = {
  window_days: number;
  sync: Record<string, { last_synced_at: string | null; last_error: string | null }>;
  sleep: Array<Record<string, unknown>>;
  hrv: Array<Record<string, unknown>>;
  body_battery_daily: Array<Record<string, unknown>>;
  body_battery_samples: Array<Record<string, unknown>>;
  workouts: Array<Record<string, unknown>>;
  daily_summary: Array<Record<string, unknown>>;
  weights: Array<Record<string, unknown>>;
  daily_score: Array<Record<string, unknown>>;
  metric_summary: Array<{ source: string; metric_key: string; count: number; latest: string | null }>;
  metric_recent: Array<Record<string, unknown>>;
  llm_comments: Array<Record<string, unknown>>;
};

export const api = {
  today: () => request<TodayResponse>("/api/today"),
  timeseries: (metric: string, days = 28) =>
    request<TimeseriesResponse>(`/api/timeseries?metric=${encodeURIComponent(metric)}&days=${days}`),
  recompute: () => request<unknown>("/admin/recompute", { method: "POST" }),
  syncGarmin: () => request<unknown>("/admin/garmin/sync", { method: "POST" }),
  regenerateAdvice: () => request<unknown>("/admin/llm/regenerate", { method: "POST" }),
  gcalStatus: () => request<GcalStatus>("/admin/gcal/status"),
  gcalSchedule: () => request<GcalScheduleResult>("/admin/gcal/schedule", { method: "POST" }),
  debugSources: (days = 14) => request<DebugSources>(`/api/debug/sources?days=${days}`),
};
