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

export type ExercisePrescription = {
  name: string;
  weight?: string;
  sets: number;
  reps: string;
  rest_sec?: number;
  rir?: number;
  tempo?: string;
  notes?: string;
};

export type AdviceAction = {
  time_jst: string; // HH:MM (推奨開始時刻)
  until_jst?: string | null; // HH:MM この時刻までに始めれば OK (最終開始期限)
  carryover?: boolean | null; // 期限を過ぎても実行価値が残るか (水分・回復など)
  title: string;
  duration_min: number;
  category:
    | "training"
    | "cardio"
    | "recovery"
    | "mobility"
    | "nutrition"
    | "rest"
    | "focus"
    | "other";
  priority: AdvicePriority;
  intensity?: string;
  why?: string;
  exercises?: ExercisePrescription[];
};

export type AdvicePayload = {
  headline?: string;
  focus: string;
  actions: AdviceAction[];
  rationale: string;
};

export type AdviceFeedback = { done: boolean; rating: number };
export type Advice = {
  comment: string;
  model: string;
  generated_at: string | null;
  payload: AdvicePayload | null;
  feedback?: Record<string, AdviceFeedback>;
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

export type FocusComponents = {
  hrv: number | null;
  body_battery: number | null;
  stress: number | null;
  sleep: number | null;
  circadian: number | null;
  air_quality?: number | null;
  morning_light?: number | null;
};

export type FocusCurvePoint = {
  time: string; // HH:MM
  score: number;
  level: "high" | "mid" | "low" | "unknown";
};

export type FocusWindow = {
  start: string; // HH:MM
  end: string; // HH:MM
  avg_score: number;
};

export type Focus = {
  score: number | null;
  level: "high" | "mid" | "low" | "unknown";
  rationale: string;
  components: FocusComponents;
  curve: FocusCurvePoint[];
  peak_windows: FocusWindow[];
  stress_recent_avg: number | null;
  disclaimer: string;
};

export type CaffeineDecayPoint = {
  time: string; // HH:MM
  residual_mg: number;
  concentration_mg_per_l: number;
};

export type Caffeine = {
  available: boolean;
  reason?: string;
  recommended_mg?: number | null;
  instant_coffee_g?: number | null;
  max_safe_mg?: number;
  min_cognitive_mg?: number;
  hours_until_bedtime?: number;
  bedtime?: string;
  body_weight_kg?: number;
  half_life_h?: number;
  bedtime_residual_if_consumed_mg?: number;
  blood_concentration_at_bedtime_mg_per_l?: number;
  existing_residual_mg?: number;
  decay_curve?: CaffeineDecayPoint[];
  disclaimer?: string;
};

export type CaffeineSource =
  | "instant_coffee"
  | "canned_coffee"
  | "nespresso"
  | "green_tea"
  | "ibuquick"
  | "bufferin_premium"
  | "manual";

export type CaffeineIntake = {
  id: number;
  ts: string;
  ts_jst: string;
  source: string;
  amount: number;
  unit: string;
  mg: number;
  note?: string | null;
};

export type CaffeineIntakeList = {
  items: CaffeineIntake[];
  total_mg: number;
};

export type CaffeinePreset = {
  unit: string;
  default_amount: number;
  mg_per_unit: number;
  default_mg: number;
};

export type CaffeinePresets = Record<CaffeineSource, CaffeinePreset>;

export type MigraineEpisode = {
  id: number;
  started_at: string;
  started_at_jst: string;
  ended_at: string | null;
  ended_at_jst: string | null;
  duration_min: number | null;
  severity: number | null;
  note: string | null;
  active: boolean;
};

export type MigraineList = {
  items: MigraineEpisode[];
  active: MigraineEpisode | null;
  count_30d: number;
};

export type Checkin = {
  date: string;
  mood: number | null;
  energy: number | null;
  stress: number | null;
  soreness: number | null;
  note: string | null;
  /** 各フィールドがサジェスト採用 (true) か能動入力 (false) か */
  from_suggested?: Record<string, boolean>;
  /** 最終記録時刻 (ISO, UTC)。瞬間の体感なので経過時間で stale 判定に使う */
  updated_at?: string | null;
};
export type CheckinSuggested = {
  mood: number | null;
  energy: number | null;
  stress: number | null;
  soreness: number | null;
};
export type DayStorySegment = {
  start_h: number;
  end_h: number;
  label: string;
  confidence: number;
  source: "sleep" | "workout" | "calendar" | "inferred";
};
export type DayStoryInsight = {
  icon: "sit" | "run" | "walk" | "ok";
  tone: "good" | "warn";
  text: string;
  action: string;
};
export type DayStory = {
  window: "day" | "24h";
  date: string | null;
  origin_jst: string;
  span_h: number;
  now_h: number | null;
  summary: string;
  segments: DayStorySegment[];
  insights: DayStoryInsight[];
  stats: {
    steps: number;
    active_kcal: number;
    sleep_h: number | null;
    stress_avg: number | null;
    caffeine_mg: number;
    intensity_min: number;
  };
};

export type TimelinePoint = { h: number; v: number };
export type DayTimelineData = {
  window: "day" | "24h";
  date: string | null;
  origin_jst: string;
  span_h: number;
  now_h: number | null;
  body_battery: TimelinePoint[];
  stress: TimelinePoint[];
  heart_rate: TimelinePoint[];
  resting_hr: number | null;
  steps_binned: { h: number; steps: number }[];
  sleep_blocks: { start_h: number; end_h: number }[];
  workouts: { start_h: number; end_h: number; type: string | null }[];
  caffeine: { h: number; mg: number; source: string }[];
  migraine: { start_h: number; end_h: number | null; severity: number | null }[];
  checkin: {
    h: number;
    mood: number | null;
    energy: number | null;
    stress: number | null;
    soreness: number | null;
  } | null;
  checkin_estimated: { mood: number | null; energy: number | null; stress: number | null; soreness: number | null } | null;
  caffeine_curve: { h: number; mg: number }[];
  caffeine_bedtime_safe_mg: number | null;
  caffeine_alert_floor_mg: number | null;
  caffeine_today_mg: number | null;
  caffeine_daily_limit_mg: number | null;
  pressure_curve: { h: number; hpa: number }[];
  prediction_text: string | null;
  focus_windows: { start_h: number; end_h: number; score: number }[];
  sleep_window: { melatonin_h: number; bedtime_h: number } | null;
  recovery_bands: { start_h: number; end_h: number }[];
  water: {
    intake_curve: { h: number; ml: number }[];
    intake_total_ml: number | null;
    goal_ml: number | null;
    sweat_ml: number;
    source: string | null;
  } | null;
  events: { start_h: number; end_h: number; title: string }[];
};

export type CheckinResponse = { today: Checkin | null; items: Checkin[]; suggested: CheckinSuggested };
export type CheckinUpdate = {
  mood?: number;
  energy?: number;
  stress?: number;
  soreness?: number;
  note?: string;
  clear?: string[];
  /** 送った値のうちサジェスト(推定値)をタップ採用したフィールド名 */
  from_suggested?: string[];
};

export type UserProfileDto = {
  height_cm: number;
  sex: "male" | "female";
  target_weight_kg: number;
  target_body_fat_pct: number;
  body_fat_tolerance_pct: number;
  ffmi_normalized: number | null;
  source: "db" | "default";
};
export type ProfileAssessment = { level: "ok" | "warning" | "blocked"; warnings: string[] };
export type ProfileUpdate = {
  height_cm?: number;
  sex?: "male" | "female";
  target_weight_kg: number;
  target_body_fat_pct: number;
  body_fat_tolerance_pct?: number;
  ffmi_normalized?: number;
};

export type MigraineOnsetProfile = {
  mean_hour: number | null;
  sd_hour: number | null;
  peak_bucket: string | null;
  buckets: { label: string; count: number }[];
};
export type MigraineFactor = {
  key: string;
  label: string;
  direction: string;
  case_mean: number;
  control_mean: number;
  n_case?: number;
  p: number;
  q: number;
  tier?: "strong" | "suggestive" | "trend" | "weak";
};
export type MigraineTriggers = {
  episode_count: number;
  onset_profile: MigraineOnsetProfile;
  status: "accumulating" | "no_data" | "analyzed" | "no_significant_factor" | "has_factors";
  reliability?: "very_low" | "low" | "medium" | "high";
  min_episodes: number;
  remaining?: number;
  factors: MigraineFactor[];
  tested: string[];
};

export type PressurePoint = {
  time: string;
  hpa: number;
};

export type WellbeingAlert = {
  code: string;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  action: string;
};

export type AirQuality = {
  pm2_5: number | null;
  pm10: number | null;
  no2: number | null;
  o3: number | null;
  uv_index: number | null;
  aqi: number | null;
  risk_level: "good" | "moderate" | "unhealthy_sensitive" | "unhealthy";
  risk_reason: string;
  location_label: string;
};

export type MorningLight = {
  score: number | null;
  steps_in_window: number;
  daylight_min?: number | null;
  source?: "apple_daylight" | "steps_proxy" | null;
  window_start_jst: string;
  window_end_jst: string;
  rationale: string;
};

export type AlcoholSource =
  | "beer_glass"
  | "beer_can_500"
  | "wine_glass"
  | "sake_go"
  | "shochu_mizuwari"
  | "highball"
  | "strong_chuhai"
  | "manual";

export type AlcoholIntake = {
  id: number;
  ts: string;
  ts_jst: string;
  source: string;
  amount: number;
  unit: string;
  amount_ml: number | null;
  abv_pct: number | null;
  grams: number;
  note?: string | null;
};

export type AlcoholList = {
  items: AlcoholIntake[];
  total_grams: number;
  drinks_equivalent: number;
};

export type AlcoholPreset = {
  unit: string;
  default_amount: number;
  default_ml: number;
  default_abv: number;
  grams_per_unit: number;
  default_grams: number;
};

export type AlcoholPresets = Record<AlcoholSource, AlcoholPreset>;

export type Pressure = {
  current_hpa: number | null;
  delta_24h_hpa: number | null;
  delta_6h_hpa: number | null;
  min_24h_hpa: number | null;
  max_24h_hpa: number | null;
  forecast_min_24h_hpa: number | null;
  forecast_delta_24h_hpa: number | null;
  risk_level: "calm" | "watch" | "warning" | "severe";
  risk_reason: string;
  location_label: string;
  series: PressurePoint[];
};

export type TonightPlan = {
  wake: string; // HH:MM
  bedtime: string;
  bath: string;
  dinner_cutoff: string;
  target_sleep_min: number;
  estimated_sleep_min: number;
  compressed: boolean;
  notes: string[];
};

export type TodayResponse = {
  date: string;
  last_data_update_at?: string | null;
  tonight_plan?: TonightPlan;
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
  focus?: Focus;
  caffeine?: Caffeine;
  pressure?: Pressure | null;
  air_quality?: AirQuality | null;
  morning_light?: MorningLight;
  alerts?: WellbeingAlert[];
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

export type TrendDirection = "improving" | "stable" | "declining";

export type IdealBand =
  | { type: "band"; lo: number; hi: number }
  | { type: "upper"; good_line: number | null };

export type TrendMetric = {
  label: string;
  unit: string;
  ideal: IdealBand;
  raw_series: TimeseriesPoint[];
  current_raw: number | null;
  achievement: number | null;
  achievement_prev_day_change: number | null;
  achievement_week_over_week: { delta: number; pct: number | null } | null;
  direction: TrendDirection | null;
  regression: { start: TimeseriesPoint; end: TimeseriesPoint } | null;
  /** API 側で計算する補足 (例: "最低 72% (直近)") */
  subtitle?: string | null;
};

export type TrendMetricKey =
  | "sleep" | "hrv" | "energy" | "load" | "weight" | "body_fat"
  | "readiness" | "spo2" | "respiration" | "rhr_night" | "sleep_midpoint";

export type TrendsResponse = {
  granularity: "daily" | "weekly";
  generated_at: string | null;
  /** 生理指標系はデータがある場合のみ含まれる */
  metrics: Partial<Record<TrendMetricKey, TrendMetric>>;
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

export type LifeDomain = {
  key: string;
  label: string;
  achievement: number | null;
  raw_achievement: number | null;
  weight: number;
  detail: string | null;
  /** このドメインが実際に読むデータの最終日 (供給死活監視) */
  last_data_at: string | null;
  stale: boolean;
};
export type LifePreset = { key: string; label: string };
export type LifeResponse = {
  life_score: number | null;
  domains: LifeDomain[];
  /** 記録率: weight>0 のドメインのうち達成度データがある数 */
  coverage: { active: number; total: number };
  presets: LifePreset[];
  generated_at: string;
};

export type LearningCheckField = "read" | "rustlings" | "explained";
export type LearningSection = {
  id: string;
  title: string;
  done: boolean;
  read: boolean;
  rustlings: boolean;
  explained: boolean;
};
export type LearningChapter = {
  chapter: number;
  title: string;
  note: string | null;
  milestone: boolean;
  read: boolean;
  rustlings: boolean;
  explained: boolean;
  complete: boolean;
  sections: LearningSection[];
  section_done: number;
  section_total: number;
};
export type LearningState = {
  chapters: LearningChapter[];
  /** 全章完了なら null */
  current_chapter: number | null;
  done_count: number;
  total: number;
  started_on: string | null;
  weeks_elapsed: number;
  pace: "not_started" | "behind" | "on_track" | "ahead";
  streak_sessions: number;
  last_activity: string | null;
  today: { achievement: number | null; detail: string | null } | null;
  completed: boolean;
  section_done: number;
  section_total: number;
  check_done: number;
  check_total: number;
  projection: LearningProjection | null;
};
export type LearningProjection = {
  started_on: string;
  done_units: number;
  total_units: number;
  pct: number;
  pace_per_week: number;
  pace_recent_per_week: number;
  eta_date: string | null;
  eta_days: number | null;
  eta_normal: string | null;
  eta_best: string | null;
  eta_worst: string | null;
  target_date: string | null;
  on_track: boolean | null;
  goal_status: "safe" | "likely" | "at_risk" | "unlikely" | null;
  confidence: "none" | "low" | "medium" | "high";
  series: { date: string; pct: number }[];
};

export const api = {
  today: (coords?: { lat: number; lon: number } | null) => {
    const q =
      coords && Number.isFinite(coords.lat) && Number.isFinite(coords.lon)
        ? `?lat=${coords.lat}&lon=${coords.lon}`
        : "";
    return request<TodayResponse>(`/api/today${q}`);
  },
  timeseries: (metric: string, days = 28) =>
    request<TimeseriesResponse>(`/api/timeseries?metric=${encodeURIComponent(metric)}&days=${days}`),
  trends: (granularity: "daily" | "weekly" = "daily", days = 28) =>
    request<TrendsResponse>(`/api/trends?granularity=${granularity}&days=${days}`),
  recompute: () => request<unknown>("/admin/recompute", { method: "POST" }),
  syncGarmin: () => request<unknown>("/admin/garmin/sync", { method: "POST" }),
  regenerateAdvice: () => request<unknown>("/admin/llm/regenerate", { method: "POST" }),
  fullRefresh: (regenerateAdvice = true) =>
    request<unknown>(
      `/admin/full-refresh?regenerate_advice=${regenerateAdvice}`,
      { method: "POST" },
    ),
  gcalStatus: () => request<GcalStatus>("/admin/gcal/status"),
  gcalSchedule: () => request<GcalScheduleResult>("/admin/gcal/schedule", { method: "POST" }),
  debugSources: (days = 14) => request<DebugSources>(`/api/debug/sources?days=${days}`),
  caffeinePresets: () => request<CaffeinePresets>("/api/caffeine/presets"),
  caffeineList: (hours = 24) =>
    request<CaffeineIntakeList>(`/api/caffeine?hours=${hours}`),
  caffeineAdd: (
    source: CaffeineSource,
    amount: number,
    opts?: { note?: string; ts_iso?: string },
  ) =>
    request<CaffeineIntake>("/api/caffeine", {
      method: "POST",
      body: JSON.stringify({ source, amount, ...opts }),
    }),
  caffeineDelete: (id: number) =>
    request<{ deleted: number }>(`/api/caffeine/${id}`, { method: "DELETE" }),
  caffeinePatch: (
    id: number,
    patch: { ts_iso?: string; amount?: number; source?: CaffeineSource; note?: string },
  ) =>
    request<CaffeineIntake>(`/api/caffeine/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  migraineList: (days = 30) =>
    request<MigraineList>(`/api/migraine?days=${days}`),
  migraineTriggers: () => request<MigraineTriggers>("/api/migraine/triggers"),
  adviceFeedback: (body: { action_key: string; done?: boolean; rating?: number; category?: string }) =>
    request<{ feedback: Record<string, AdviceFeedback> }>("/api/advice/feedback", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getCheckin: () => request<CheckinResponse>("/api/checkin"),
  timeline: (opts?: { date?: string; window?: "day" | "24h" }) =>
    request<DayTimelineData>(`/api/timeline?${new URLSearchParams({ ...(opts?.date ? { date: opts.date } : {}), window: opts?.window ?? "day" }).toString()}`),
  dayStory: (opts?: { date?: string; window?: "day" | "24h" }) =>
    request<DayStory>(`/api/day-story?${new URLSearchParams({ ...(opts?.date ? { date: opts.date } : {}), window: opts?.window ?? "day" }).toString()}`),
  postCheckin: (body: CheckinUpdate) =>
    request<CheckinResponse>("/api/checkin", { method: "POST", body: JSON.stringify(body) }),
  getProfile: () => request<UserProfileDto>("/api/profile"),
  putProfile: (body: ProfileUpdate) =>
    request<UserProfileDto & { assessment: ProfileAssessment }>("/api/profile", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  migraineStart: (opts?: { severity?: number; note?: string; ts_iso?: string }) =>
    request<MigraineEpisode>("/api/migraine/start", {
      method: "POST",
      body: JSON.stringify(opts ?? {}),
    }),
  migraineEnd: (opts?: { note?: string; ts_iso?: string }) =>
    request<MigraineEpisode>("/api/migraine/end", {
      method: "POST",
      body: JSON.stringify(opts ?? {}),
    }),
  migraineDelete: (id: number) =>
    request<{ deleted: number }>(`/api/migraine/${id}`, { method: "DELETE" }),
  migrainePatch: (
    id: number,
    patch: {
      started_at_iso?: string;
      ended_at_iso?: string;
      severity?: number;
      note?: string;
      clear_ended_at?: boolean;
    },
  ) =>
    request<MigraineEpisode>(`/api/migraine/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  alcoholPresets: () => request<AlcoholPresets>("/api/alcohol/presets"),
  alcoholList: (hours = 168) =>
    request<AlcoholList>(`/api/alcohol?hours=${hours}`),
  alcoholAdd: (
    source: AlcoholSource,
    amount: number,
    opts?: {
      note?: string;
      ts_iso?: string;
      override_ml?: number;
      override_abv_pct?: number;
    },
  ) =>
    request<AlcoholIntake>("/api/alcohol", {
      method: "POST",
      body: JSON.stringify({ source, amount, ...opts }),
    }),
  alcoholDelete: (id: number) =>
    request<{ deleted: number }>(`/api/alcohol/${id}`, { method: "DELETE" }),
  life: () => request<LifeResponse>("/api/life"),
  learningState: () => request<LearningState>("/api/learning/state"),
  learningPlan: (body: { started_on?: string; target_date?: string; clear_started?: boolean; clear_target?: boolean }) =>
    request<LearningState>("/api/learning/plan", { method: "POST", body: JSON.stringify(body) }),
  learningSection: (sectionId: string, field: LearningCheckField, done: boolean, doneAtIso?: string) =>
    request<LearningState>(`/api/learning/section/${sectionId}/check`, {
      method: "POST",
      body: JSON.stringify({ field, done, done_at_iso: doneAtIso }),
    }),
  setLifeWeights: (weights: Record<string, number>) =>
    request<LifeResponse>("/api/life/weights", {
      method: "PUT",
      body: JSON.stringify({ weights }),
    }),
  applyLifePreset: (name: string) =>
    request<LifeResponse>(`/api/life/preset/${name}`, { method: "POST" }),
};
