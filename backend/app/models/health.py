from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MetricSample(Base):
    """Long-format time-series for fine-grained metrics."""

    __tablename__ = "metric_sample"
    __table_args__ = (UniqueConstraint("source", "metric_key", "ts", name="uq_metric_sample"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # garmin | hae
    metric_key: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SleepSession(Base):
    __tablename__ = "sleep_session"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    total_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rem_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    light_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    awake_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_overnight_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class HrvDaily(Base):
    __tablename__ = "hrv_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_night_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    weekly_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    baseline_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_high: Mapped[float | None] = mapped_column(Float, nullable=True)


class BodyBattery(Base):
    __tablename__ = "body_battery"

    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    charged: Mapped[float | None] = mapped_column(Float, nullable=True)
    drained: Mapped[float | None] = mapped_column(Float, nullable=True)


class BodyBatteryDaily(Base):
    __tablename__ = "body_battery_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_of_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    morning_value: Mapped[float | None] = mapped_column(Float, nullable=True)


class Workout(Base):
    __tablename__ = "workout"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class HighlightReview(Base):
    """今日のハイライトの各イベントへの AI 評価 (タップで生成・永続化)。

    評価軸は「目標体型に対してベストな努力か・改善点は何か」。イベントは
    クライアント表示から決まる (date, event_key="HH:MM|ラベル") で一意化する。
    """

    __tablename__ = "highlight_review"
    __table_args__ = (UniqueConstraint("date", "event_key", name="uq_highlight_review"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    event_key: Mapped[str] = mapped_column(String(160))
    text: Mapped[str] = mapped_column(String(400))
    tone: Mapped[str] = mapped_column(String(10), default="info")
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EquipmentItem(Base):
    """自宅トレ器具 (LLM のトレ処方が使ってよい機材)。空なら settings からシード。"""

    __tablename__ = "equipment_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class ScreenTimeSample(Base):
    """iOS スクリーンタイムのスクショ取込 (スマホ依存トラッキング)。

    period_type=day|week の複合PK。daily_min は「1日あたり分」(Day=当日合計 /
    Week=日平均) で横断比較の基準。categories/top_apps は分単位の JSON。
    """

    __tablename__ = "screen_time_sample"
    __table_args__ = (
        UniqueConstraint("period_type", "period_start", name="uq_screen_time_sample"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_type: Mapped[str] = mapped_column(String(8))       # day | week
    period_start: Mapped[date] = mapped_column(Date, index=True)
    daily_min: Mapped[float] = mapped_column(Float)           # 1日あたり分 (比較基準)
    total_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    categories: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {name: minutes}
    top_apps: Mapped[list | None] = mapped_column(JSON, nullable=True)    # [{name, minutes}]
    source: Mapped[str] = mapped_column(String(16), default="screenshot")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AirgapDaily(Base):
    """Airgap アプリ (スマホデトックス) からの日次 push (1日=1行 upsert)。

    score はセッション実績 + 浪費分から Airgap 側で算出した 0-100。
    waste_min は FamilyControls 計測が有効なときのみ (nil=未計測)。
    """

    __tablename__ = "airgap_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    completed_min: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    goal_min: Mapped[int] = mapped_column(Integer, default=60)
    waste_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waste_limit_min: Mapped[int] = mapped_column(Integer, default=60)
    sessions: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkoutReview(Base):
    """ワークアウトへの AI 一言評価 (ユーザーのタップで生成し、以後は保存済みを表示)。

    自動生成はしない (LLM コストはタップ時の1回だけ)。tone: good|caution|info。
    """

    __tablename__ = "workout_review"

    workout_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workout.id", ondelete="CASCADE"), primary_key=True
    )
    text: Mapped[str] = mapped_column(String(400))
    tone: Mapped[str] = mapped_column(String(10), default="info")
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WeightSample(Base):
    __tablename__ = "weight_sample"

    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    muscle_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32))


class DailySummary(Base):
    __tablename__ = "daily_summary"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class DailyScore(Base):
    __tablename__ = "daily_score"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    sleep_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_sub: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    version: Mapped[str] = mapped_column(String(16))
    computed_at: Mapped[datetime] = mapped_column(DateTime)


class LlmComment(Base):
    __tablename__ = "llm_comment"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str] = mapped_column(String(2000))
    # 構造化版 (tool_use の input そのまま): {focus, actions: [...], rationale}
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class MigraineEpisode(Base):
    """偏頭痛エピソード。「痛くなった→治った」を 1 件として記録する。

    ended_at が None のものは active (現在進行中)。
    severity は 1-10 の主観強度 (省略可)。トリガー記録のため note を任意。
    """

    __tablename__ = "migraine_episode"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC naive
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AlcoholIntake(Base):
    """アルコール摂取の手動記録。

    grams は純アルコール量 (g)。これは飲料種類 × 量 × ABV × 0.8 で算出する。
    Pietilä 2018: 純アルコール 10g (約 1 drink) で深い睡眠 -20%、HRV -10〜15%。

    source 例: "beer" (中ジョッキ 350ml × 5% × 0.8 = 14g)、"wine"、"sake"、"shochu"、
    "highball"、"manual" (g 直接入力)。
    """

    __tablename__ = "alcohol_intake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    amount_ml: Mapped[float | None] = mapped_column(Float, nullable=True)
    abv_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    grams: Mapped[float] = mapped_column(Float)  # 純アルコール g
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class CaffeineIntake(Base):
    """ユーザーが手動で記録したカフェイン摂取イベント。

    source は摂取源の分類 (instant_coffee / canned_coffee / nespresso / ibuquick / manual)。
    amount は元の量 (g, 本, 錠, mg) の数値、unit はその単位文字列。
    mg は **実際のカフェイン量** (推奨計算で使う、source から自動算出 or 手動入力)。
    """

    __tablename__ = "caffeine_intake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC naive
    source: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16))
    mg: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class SourceSync(Base):
    __tablename__ = "source_sync"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cursor_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DomainWeight(Base):
    """ライフドメインの重み (ユーザーが調整。プリセット適用 or スライダー)。"""

    __tablename__ = "domain_weight"

    domain: Mapped[str] = mapped_column(String(32), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class UserProfile(Base):
    """UI から設定する個人プロファイルの上書き (単一行、id=1 固定)。

    値が NULL のフィールドは config.py (env) のデフォルトにフォールバックする。
    目標体型シルエットで設定した体重・体脂肪率を保持する。
    """

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_tolerance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ffmi_normalized: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- 個人差ファクター (計算直結。NULL は config デフォルトにフォールバック) ---
    # 生年月日。設定されていれば年齢は都度ここから算出する (age 列より優先)。
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)  # birth_date 無し時のみ使用
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Karvonen 用上書き
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 実測上書き (無ければ式)
    # カフェイン消失半減期に効く CYP1A2 修飾因子 (トグル)
    caffeine_smoker: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    caffeine_oral_contraceptives: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    caffeine_pregnant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 感受性 "high"|"normal"|"low" → 目標 mg/kg。half_life override は直接 2-12h を指定
    caffeine_sensitivity: Mapped[str | None] = mapped_column(String(8), nullable=True)
    caffeine_half_life_override_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 睡眠
    wake_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM"
    sleep_need_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chronotype: Mapped[str | None] = mapped_column(String(12), nullable=True)  # morning|intermediate|evening
    # 栄養 (per kg 目標)
    protein_g_per_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_ml_per_kg: Mapped[float | None] = mapped_column(Float, nullable=True)


class FoodItem(Base):
    """ユーザーが登録する頻用食品マスタ (マクロ付き、再利用可能)。

    LLM が食品名+量からマクロを推定し、ユーザーが確認/微修正して保存する。
    1 単位 (unit_label, 例 "1個"/"1杯"/"100g") あたりの栄養。
    """

    __tablename__ = "food_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    kcal: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    fat_g: Mapped[float] = mapped_column(Float, default=0.0)
    carb_g: Mapped[float] = mapped_column(Float, default=0.0)
    unit_label: Mapped[str] = mapped_column(String(20), default="1食")
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 主食/主菜/間食/飲料/タンパク源
    is_protein_source: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MealPattern(Base):
    """「普段の食事パターン」: スロット (朝/昼/夜/間食) × 食品 × 量 × 頻度。

    「朝は A・B・C をよく食べる」= slot=breakfast の行が3つ。頻度で期待値を重み付け。
    記録が無い日の摂取推定の土台になる。
    """

    __tablename__ = "meal_pattern"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot: Mapped[str] = mapped_column(String(12))  # breakfast|lunch|dinner|snack
    food_id: Mapped[int] = mapped_column(ForeignKey("food_item.id", ondelete="CASCADE"))
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    frequency: Mapped[str] = mapped_column(String(10), default="daily")  # daily|often|sometimes
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdviceFeedback(Base):
    """LLM 助言アクションへの完了・評価フィードバック (日 × アクション)。

    「測るが効いたか検証しない」を閉じるための outcome ループ。
    action_key はアクションのタイトル (その日の助言内で一意)。
    done=完了したか、rating=有用度 (-1/0/+1)。LLM に還元して提案を学習する。
    """

    __tablename__ = "advice_feedback"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    action_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    done: Mapped[bool] = mapped_column(default=False)
    rating: Mapped[int] = mapped_column(Integer, default=0)  # -1 / 0 / +1
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class SubjectiveCheckin(Base):
    """日次の主観チェックイン (JST 日付ごと、1 日 1 行)。

    客観データ (HRV/睡眠 等) が代理する「実際どう感じるか」の結果変数。
    全項目 optional。mood/energy は高いほど良い、stress/soreness は高いほど悪い。
    """

    __tablename__ = "subjective_checkin"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    mood: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    soreness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 各フィールドがサジェスト(推定値)のタップ採用か能動入力かの記録
    # 例: {"mood": true, "energy": false}。採用値は機器推定にアンカーされる
    # ため、客観↔主観の乖離分析では能動入力と区別して扱う
    from_suggested: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class MentalScreening(Base):
    """PHQ-2 + GAD-2 の超短縮メンタルスクリーニング (1 回 = 1 行)。

    臨床検証済みの4項目 (各 0-3、過去2週間の頻度)。PHQ-2 はうつ、GAD-2 は不安の
    一次スクリーニング。合算 PHQ-4 (0-12) で全体の苦痛度を段階化する。
    医療機器ではなく、専門家受診の目安を示す保守的な自己観察ツール。
    """

    __tablename__ = "mental_screening"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    date: Mapped[date] = mapped_column(Date, index=True)  # JST 日付 (間隔判定用)
    # PHQ-2 (うつ): 興味喪失 / 抑うつ気分。GAD-2 (不安): 神経過敏 / 心配制御不能。各 0-3。
    phq2_1: Mapped[int] = mapped_column(Integer)
    phq2_2: Mapped[int] = mapped_column(Integer)
    gad2_1: Mapped[int] = mapped_column(Integer)
    gad2_2: Mapped[int] = mapped_column(Integer)
    phq2: Mapped[int] = mapped_column(Integer)  # 0-6
    gad2: Mapped[int] = mapped_column(Integer)  # 0-6
    phq4: Mapped[int] = mapped_column(Integer)  # 0-12
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class SleepInterventionLog(Base):
    """就寝前の介入 (耳栓/アイマスク/鼻ストリップ/口テープ) の夜次ログ。

    date = その夜 (起床日基準、SleepSession.date と一致)。値は
    True=着けた / False=外した / None=未記録。効果分析は「着けた夜 vs 外した夜」を
    並べ替え検定で比較するため、未記録(None)と「外した(False)」を明確に区別する。
    """

    __tablename__ = "sleep_intervention_log"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    earplugs: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    eyemask: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nose_strip: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mouth_tape: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SpeechSession(Base):
    """speech-coach から取り込む日次の発話練習サマリ (JST 日付ごと)。"""

    __tablename__ = "speech_session"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_pace: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_pitch: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_clarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_filler: Mapped[float | None] = mapped_column(Float, nullable=True)


class ExternalDomainEntry(Base):
    """外部ライフドメイン (学習・仕事 等) の日次達成度を取り込む汎用テーブル。"""

    __tablename__ = "external_domain_entry"

    domain: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    achievement: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class LearningChapterProgress(Base):
    """The Rust Book 完走プランの章別進捗。

    1 章のクリア条件は 3 点セット (読了 / Rustlings / 口頭説明)。
    「読んだだけでわかったふり」を構造的に防ぐため、3 つ揃って初めて
    completed とみなす。カリキュラム定義 (章タイトル・山場) はコードに
    持ち、このテーブルは進捗タイムスタンプだけを永続化する。
    """

    __tablename__ = "learning_chapter_progress"

    chapter: Mapped[int] = mapped_column(Integer, primary_key=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rustlings_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    explained_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 理解度チェックの累計得点 (フリーワード+50/4択+20/2択+10)。None は 0 とみなす。
    quiz_points: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # フリーワードで理解度80%以上に達した時刻 (選択式だけでの逃げ切りを防ぐ品質フロア)。
    free_word_passed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LearningSectionProgress(Base):
    """The Book の節 (subsection, 例 "4.2") 単位の進捗。

    クリア条件の 3 点セット (読了 / Rustlings / 説明できた) を節ごとに持つ。
    「読んだだけでわかったふり」を構造的に防ぐ設計を最下層 (節) に下ろしたもの。
    旧 done_at カラムは migration で read_at へ引き継ぐ (互換)。
    """

    __tablename__ = "learning_section_progress"

    section_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rustlings_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    explained_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LearningPlanMeta(Base):
    """完走プランのメタ情報 (シングルトン id=1)。

    started_on: 手動で記録する学習開始日 (未設定なら最初のチェック日を使う)。
    target_date: 目標完了日 (任意)。予測と突き合わせて間に合うか判定する。
    """

    __tablename__ = "learning_plan_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class PushSubscription(Base):
    """Web Push の購読 (ブラウザ/PWA ごとの送信先)。

    PushManager.subscribe() が返す endpoint + 鍵 (p256dh / auth) を保存する。
    endpoint がデバイス単位で一意なので主キーにする (再購読で UPSERT)。
    """

    __tablename__ = "push_subscription"

    endpoint: Mapped[str] = mapped_column(String(512), primary_key=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    ua: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NotificationLog(Base):
    """送信済み通知の記録 (冪等性のため)。

    engine が生成する dedup_key を主キーにし、同じ通知を二重送信しない。
    1 日 1 行〜数行のペースなので肥大しないが、古い行は定期的に掃除してよい。
    """

    __tablename__ = "notification_log"

    dedup_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)


class FitnessTestResult(Base):
    """自宅フィットネスチェックの測定結果 (test_key × 実施日で 1 行、UPSERT)。

    テスト定義・基準値・プロトコルはコード (scoring/fitness_test.py) に持ち、
    このテーブルは結果だけを永続化する (Learning のカリキュラム/進捗分離と同じ)。
    value は主指標 (回 / kg / 点)。detail_json は握力の左右別など補助情報。
    """

    __tablename__ = "fitness_test_result"
    __table_args__ = (
        UniqueConstraint("test_key", "performed_on", name="uq_fitness_test"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_key: Mapped[str] = mapped_column(String(24), index=True)  # push_up|grip|chair_stand|srt
    performed_on: Mapped[date] = mapped_column(Date, index=True)  # JST 日付
    value: Mapped[float] = mapped_column(Float)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Compass: 価値観 × マインドセットの自己理解・ギャップ・介入
# 次元定義 (枠組み定数) は scoring/identity/dimensions.py に持ち、これらの
# テーブルは「理想プロファイル・現在地・測定結果・作品・内省ログ」だけを永続化する
# (Learning のカリキュラム/進捗分離と同じ思想)。
# ---------------------------------------------------------------------------


class IdentityArchetype(Base):
    """理想プロファイル (なりたい型)。シングルトン id=1、UI/CLI から差し替え可能。

    target_profile: {dimension_id: 0-100} の目標値。weights: {dimension_id: 重み}。
    値は personal/aspirational target なので、未設定なら config の既定にフォールバックする。
    """

    __tablename__ = "identity_archetype"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IdentityDimensionScore(Base):
    """次元ごとの現在地 (最新値のみ)。

    sjt_baseline: 直近 SJT 本測のベースライン (0-100)。
    current_estimate: ベースライン + 意思決定ログ観測の EWMA 合成 (0-100)。
    components: 内訳 (観測履歴の要約など) を JSON で保持しデバッグ可能にする。
    """

    __tablename__ = "identity_dimension_score"

    dimension_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sjt_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    components: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IdentityAssessment(Base):
    """SJT 本測 1 セッションの結果 (会話履歴はフロント保持、サーバは結果のみ)。

    result: {dimension_id: 0-100} の推定。kind は将来の測定種別拡張用 ("sjt" 等)。
    """

    __tablename__ = "identity_assessment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), default="sjt")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class IdentityDecisionLog(Base):
    """日々の意思決定ログ。短文を LLM が次元 × 信号 (-1..+1) に紐づける。

    inferred: [{"dimension_id": str, "signal": float, "rationale": str}] を JSON で保持。
    現在地の EWMA 補正に観測として供給する。
    """

    __tablename__ = "identity_decision_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    text: Mapped[str] = mapped_column(String(1000))
    inferred: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MediaItem(Base):
    """介入に使う作品 (映画/TV/マンガ/本)。

    映画/TV は IMDb CSV 取り込み (source="imdb", ext_id=tt...)、マンガ/本は手動登録。
    dimension_tags: {dimension_id: 0-1 確信度} で「効く次元」を保持 (手タグ + LLM 拡張)。
    """

    __tablename__ = "media_item"
    __table_args__ = (UniqueConstraint("source", "ext_id", name="uq_media_item_source_ext"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), index=True)  # imdb | manual
    ext_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # IMDb const tt...
    kind: Mapped[str] = mapped_column(String(8))  # film | tv | manga | book
    title: Mapped[str] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dimension_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tag_source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # curated | llm
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MediaLog(Base):
    """作品ごとの状態と「作品 → 内省 → 実行意図」ループの記録。

    status: watchlist (未消化) | seen (消化済み)。
    intention: 観た後に生成した if-then の小さな実行意図。
    intention_done / intention_rating: 完遂と有用度 (-1/0/+1)。AdviceFeedback と同型の
    outcome ループで再測定へ還元する。dimension_id は紐づく主次元。
    """

    __tablename__ = "media_log"

    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_item.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(12), default="watchlist")
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # IMDb 個人評価等
    seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dimension_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reflection: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    intention: Mapped[str | None] = mapped_column(String(500), nullable=True)
    intention_done: Mapped[bool] = mapped_column(Boolean, default=False)
    intention_rating: Mapped[int] = mapped_column(Integer, default=0)  # -1 / 0 / +1
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GoodActionLog(Base):
    """個別の良い行動イベント(手動ワンタップ & 自動取込)。"""

    __tablename__ = "good_action_log"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_good_action_dedup"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC naive
    kind: Mapped[str] = mapped_column(String(32), index=True)  # meditation|journaling|...
    source: Mapped[str] = mapped_column(String(16))  # manual|apple_health|github|garmin
    value: Mapped[float] = mapped_column(Float, default=1.0)
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 自動取込の冪等用
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class GardenDaily(Base):
    """日次の草1マス。冪等 upsert(再計算可能)。"""

    __tablename__ = "garden_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    intensity: Mapped[float] = mapped_column(Float, default=0.0)
    level: Mapped[int] = mapped_column(Integer, default=0)  # 0-4
    contributions: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {kind: weighted}
    streak_len: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GithubContributionDaily(Base):
    """GitHub の日次コミット数。"""

    __tablename__ = "github_contribution_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    commit_count: Mapped[int] = mapped_column(Integer, default=0)
    repo_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GardenConfig(Base):
    """GitHub 連携の認証情報(シングルトン id=1)。UI から設定。"""

    __tablename__ = "garden_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    github_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    github_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JournalEntry(Base):
    """手書きジャーナルのデジタル控え(写真→文字起こし or 手入力)。日付ごとに1件 upsert。"""

    __tablename__ = "journal_entry"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    text: Mapped[str] = mapped_column(String(8000), default="")
    source: Mapped[str] = mapped_column(String(16), default="text")  # image|text
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HealthCheckup(Base):
    """健康診断結果(テキスト/画像から抽出)。values は [{key,value,unit,flag}]。"""

    __tablename__ = "health_checkup"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # image|text|manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BodyCompositionSample(Base):
    """体組成計(BIA)スクショから取り込む、HealthKit 標準に無い指標。

    体重/体脂肪率は Apple Health 経由で別途取得済み。ここは標準で取れない
    骨格筋量・内臓脂肪レベル・基礎代謝(BMR)のみを手動スクショ OCR で保持する。
    日付ごとに 1 件 upsert(再アップロードで重複させない)。
    """

    __tablename__ = "body_composition_sample"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    skeletal_muscle_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    skeletal_muscle_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    visceral_fat_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmr_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="image")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AssetHolding(Base):
    """資産バケット(MoneyForward から転記)。目標配分に対する売買リバランスに使う。

    target_weight>0 のものが配分対象(定期/仮想通貨/積立 等)。reserve/現金は 0。
    """

    __tablename__ = "asset_holding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(32), default="other")
    value_jpy: Mapped[float] = mapped_column(Float, default=0.0)
    target_weight: Mapped[float] = mapped_column(Float, default=0.0)  # 0=配分対象外
    risk_tier: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 手動上書き(空=自動判定)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RoiCandidate(Base):
    """購入/サブスク/支出の ROI 候補。儲かるか(価値/コスト)を概算しランキングする。"""

    __tablename__ = "roi_candidate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cost_jpy: Mapped[float] = mapped_column(Float, default=0.0)  # 価格(サブスクは1期間額)
    period: Mapped[str] = mapped_column(String(12), default="onetime")  # month|year|onetime
    monthly_use_days: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_time_saved_h: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_revenue_jpy: Mapped[float] = mapped_column(Float, default=0.0)
    resale_jpy: Mapped[float] = mapped_column(Float, default=0.0)  # 資産性(売る時いくら)
    status: Mapped[str] = mapped_column(String(16), default="considering")  # considering|owning|canceled
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinanceState(Base):
    """資産/ROI 計算のグローバル設定(単一行 id=1)。"""

    __tablename__ = "finance_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    reserve_jpy: Mapped[float] = mapped_column(Float, default=0.0)  # 生活防衛資金(確保額)
    reserve_months: Mapped[int] = mapped_column(Integer, default=6)  # 防衛資金=月支出×この月数
    wage_jpy_per_h: Mapped[float] = mapped_column(Float, default=2000.0)  # 時間削減の換算時給
    risk_tolerance: Mapped[int] = mapped_column(Integer, default=3)  # 1(保守)〜7(積極)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CashflowTx(Base):
    """入出金履歴(MoneyForward CSV)。月支出の算出・防衛資金・ランウェイに使う。

    id は MF の取引 ID(再アップロードで重複しない)。counted=計算対象, is_transfer=振替。
    """

    __tablename__ = "cashflow_tx"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    amount_jpy: Mapped[float] = mapped_column(Float)  # +収入 / -支出
    major_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    minor_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[str | None] = mapped_column(String(300), nullable=True)
    counted: Mapped[bool] = mapped_column(Boolean, default=True)
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)


class LifeProfile(Base):
    """資産アドバイス用の生活状況(単一行 id=1)。NULL は「未入力」として素直に扱う。

    総資産(AssetHolding)/入出金(CashflowTx)から取れない文脈 — 世帯・住居・負債・制度枠 —
    をユーザーが入力し、finance_advisor が「なんで増えないか」の診断と最善手に使う。
    """

    __tablename__ = "life_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # 世帯
    partner: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    children: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dependents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 住居
    housing: Mapped[str | None] = mapped_column(String(8), nullable=True)  # rent|own
    housing_cost_jpy: Mapped[float | None] = mapped_column(Float, nullable=True)  # 月の家賃 or 返済
    # 収入
    monthly_income_jpy: Mapped[float | None] = mapped_column(Float, nullable=True)  # 手取り月収の上書き
    monthly_expense_jpy: Mapped[float | None] = mapped_column(Float, nullable=True)  # 月支出(収支スクショ由来)
    income_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # employee|self_employed|mixed
    # 負債
    debt_balance_jpy: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_rate_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 加重平均金利
    # 制度枠
    nisa_monthly_jpy: Mapped[float | None] = mapped_column(Float, nullable=True)
    ideco_monthly_jpy: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PerfIssue(Base):
    """パフォーマンス問題の記録(エラー / 低速レスポンス / 低速クエリ)。

    (kind, label) で集約。count を加算、max_duration_ms を更新。修正PRの起票元。
    """

    __tablename__ = "perf_issue"
    __table_args__ = (UniqueConstraint("kind", "label", name="uq_perf_kind_label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # error | slow_request | slow_query
    label: Mapped[str] = mapped_column(String(255))  # endpoint or 正規化SQL
    count: Mapped[int] = mapped_column(Integer, default=0)
    max_duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[str | None] = mapped_column(String(800), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)  # 修正PRで対応済み
    first_ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Goal(Base):
    """中期目標(Layer 1)。capital_weights でドメインの重点ウェイトを駆動する。"""

    __tablename__ = "goal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    horizon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    capital_weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metric: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BecomingSnapshot(Base):
    """三層(身体・行動・アイデンティティ)の日次スナップショット。

    アイデンティティのトレンドを出すための履歴の素。condition/garden は過去も
    バックフィルできるが、dim_estimates は履歴が無いので前向き(これから)のみ。
    """

    __tablename__ = "becoming_snapshot"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    condition: Mapped[float | None] = mapped_column(Float, nullable=True)
    garden_focus: Mapped[float | None] = mapped_column(Float, nullable=True)
    garden_intensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_proximity: Mapped[float | None] = mapped_column(Float, nullable=True)
    dim_estimates: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# Foreign keys not strictly needed for SQLite single-user, kept simple intentionally.
_ = ForeignKey  # silence unused import if not referenced elsewhere
