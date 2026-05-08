from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_tz: str = "Asia/Tokyo"
    app_data_dir: Path = Path("/data")
    app_log_level: str = "INFO"

    db_path: Path | None = None

    anthropic_api_key: str | None = None
    # tool_use の安定性と料金のバランスで Sonnet 既定。Haiku だと focus/rationale が
    # 混線したり XML 疑似タグの混入が起きやすかったため格上げ。.env で上書き可。
    llm_model: str = "claude-sonnet-4-6"
    llm_max_regenerations_per_day: int = 3

    garmin_email: str | None = None
    garmin_password: str | None = None
    garmin_token_dir: Path | None = None

    hae_ingest_token: str | None = None

    baseline_window_days: int = 28
    morning_bb_hour_local: int = 6

    score_weight_sleep: float = 3.0
    score_weight_hrv: float = 2.0
    score_weight_bb: float = 2.0
    score_weight_load: float = 2.0
    score_weight_weight: float = 1.0
    score_weight_body_fat: float = 1.0

    score_version: str = "v2"

    # --- ユーザープロファイル (LLM プロンプトと採点で使用) ---
    user_age: int = 31
    user_sex: str = "male"  # "male" | "female"
    user_height_cm: float = 165.0
    target_weight_kg: float = 56.5
    target_body_fat_pct: float = 14.0
    body_fat_tolerance_pct: float = 1.5

    # 利用可能な機材 (LLM 用)。ダンベル重量は **これ以外の刻みは存在しない**。
    user_equipment: list[str] = Field(
        default_factory=lambda: [
            "ダンベル (2 / 4 / 8 / 12 / 16 / 20 kg のいずれか。10kg や 6kg などの中間サイズは持っていない)",
            "アブローラー",
            "フラットベンチ",
            "プッシュアップバー (小型・2 つ)",
            "リュックサック (中身の重さで負荷調整可、ラッキング用)",
            "トレーニングマット",
            "木刀 (素振り用)",
            "VR ヘッドセット (Meta Quest 系、VR boxing 等のフィットネスアプリ可)",
        ]
    )
    # 候補種目 (LLM はこの中から組む)
    user_training_options: list[str] = Field(
        default_factory=lambda: [
            # 有酸素 / コンディショニング
            "ランニング (Z2 / Z3)",
            "ジョグ (Z1 リカバリー)",
            "ラッキング (リュック歩行)",
            "HIIT (Tabata / EMOM、週 1-2 回上限)",
            "ウォーキング (回復日)",
            "VR boxing (Quest 等、有酸素 + 全身協調)",
            # 木刀素振り (蹲踞姿勢、剣道系)
            "木刀素振り: 大素振り",
            "木刀素振り: 正面打ち",
            "木刀素振り: 面切り返し",
            "木刀素振り: 小手面胴切り返し",
            "木刀素振り: 股割り素振り (低姿勢、下半身強化)",
            # ダンベル筋トレ
            "ダンベルベンチプレス",
            "ダンベルショルダープレス",
            "ダンベルロー (片手)",
            "ダンベルゴブレットスクワット",
            "ダンベルルーマニアンデッドリフト (12kg 上限)",
            "ダンベルヒップスラスト",
            "ダンベルカール",
            "ダンベルランジ",
            # 自重
            "プッシュアップ (プッシュアップバー)",
            "アブローラー (膝つき)",
            "アブローラー (立位、上級)",
            "カーフレイズ (自重 / ダンベル加重)",
            "プランク",
            # モビリティ / 回復
            "動的ストレッチ (股関節 / 胸郭 / 肩)",
            "静的ストレッチ",
            "ボックスブレシング (呼吸法、副交感神経 ON)",
        ]
    )
    user_injury_notes: list[str] = Field(
        default_factory=lambda: [
            "16kg のダンベルデッドリフトで腰を痛めた経験あり。腰に高負荷をかけるヒンジ系は 12kg 以下、フォーム最優先。",
        ]
    )
    user_priority: str = (
        "仕事のパフォーマンス > 健康 > 魅力的な体型。"
        "睡眠とストレス管理を犠牲にしない範囲で目標体組成に近づけたい。"
    )
    # 曜日固定はしない。直近 7-14 日の workout 履歴 + コンディションから
    # 「最も足りないモダリティ」を LLM が動的に選ぶ。週次目標分布だけ与える。
    # 科学的根拠: WHO 2020 (中強度有酸素 ≥ 150min/週 + 筋トレ 2 日/週)、
    # all-cause mortality は有酸素+筋トレ併用で -40% (Stamatakis 2018 BMJ)。
    # Z2 は時間より頻度の方が ROI 高い (ミトコンドリア生合成のメタ解析)。
    user_weekly_target_hint: str = (
        "週次目標分布 (曜日固定しない、直近履歴から動的に決める):\n"
        "- 筋トレ: 3 セッション/週 (push / pull / legs を回す。連日同部位は避け、48h 以上空ける)\n"
        "- Z2 有酸素: 3 セッション/週 (ラッキング / ジョグ / ウォーキング / VR boxing。"
        "頻度 > 時間。1 回 30-60 分で OK)\n"
        "- HIIT または ロング Z2: 1 セッション/週 (Tabata 1 本 or 60-90 分のロングラッキング)\n"
        "- 完全休 or 軽モビリティ: 1 セッション/週\n"
        "選択ロジック: ``recent_workouts_14d`` の直近 7 日を見て **最も不足しているモダリティ** "
        "を本日の候補にする。例: 直近 7 日が筋トレ 4・Z2 cardio 0 なら今日は Z2 を最優先。"
        "コンディションが悪ければ Z2 → ウォーキング、休息に格下げ。"
    )

    # --- 栄養目標 ---
    target_protein_g_per_kg: float = 2.0  # recomposition 想定
    target_water_ml_per_kg: float = 35.0
    # 摂取カロリー目標は TDEE (= 当日の active + basal energy 合計、Apple Health から推定) を基準にする

    # --- 睡眠リズム目標 ---
    target_wake_time: str = "06:30"  # 平日想定の起床時刻 (HH:MM, JST)
    target_sleep_min: int = 480  # 8h を ideal とする (推奨 7-9h)
    bath_to_bed_lead_min: int = 90  # 入浴〜就寝の理想ラグ (深部体温↑→↓ で入眠促進)
    dinner_to_bed_lead_min: int = 180  # 夕食〜就寝の理想ラグ (消化負荷を避ける)

    # --- トレーニング処方の開始重量 (前回実績が無いときの保守的スタート) ---
    # 腰のケガ歴を考慮し、ヒンジ系は 8kg から、全般に控えめに開始。
    # 利用可能な刻みは 2/4/8/12/16/20kg のみ なので、それ以外を絶対に使わない。
    # ダンベル系のみ "持っている刻み" の中の保守スタート値を列挙する。
    # 有酸素・ラッキング・木刀・VR boxing 等の時間・距離・reps は履歴 (recent_workouts_14d /
    # recent_training_prescriptions_21d) から LLM が動的算出するため、ここには持たない。
    user_starting_weights: dict[str, str] = Field(
        default_factory=lambda: {
            "ダンベルベンチプレス": "8kg×2",
            "ダンベルショルダープレス": "4kg×2",
            "ダンベルロー (片手)": "8kg",
            "ダンベルゴブレットスクワット": "8kg",
            "ダンベルルーマニアンデッドリフト": "8kg×2",
            "ダンベルヒップスラスト": "8kg×2",
            "ダンベルカール": "4kg×2",
            "ダンベルランジ": "4kg×2",
            "プッシュアップ (プッシュアップバー)": "自重",
            "アブローラー (膝つき)": "自重",
            "カーフレイズ": "自重 or 8kg×2",
        }
    )
    # 漸進性ルール: ダンベルが飛び石 (2→4→8→12→16→20) なので
    # 「次の刻み」へジャンプ。+2kg ではなく次の利用可能サイズへ。
    user_progression_rule: str = (
        "double progression: 同一重量で目標 reps 上限 + RIR 1-2 を 2 セッション連続で達成できたら "
        "**次に利用可能な重量** へ進む (例: 8kg → 12kg、12kg → 16kg)。達成できなければ重量維持して "
        "reps を 1 ずつ伸ばすか RIR を改善する。中間サイズ (10kg / 6kg 等) は存在しない。"
    )

    scheduler_enabled: bool = True
    scheduler_garmin_cron: str = "5 * * * *"
    scheduler_recompute_cron: str = "15 * * * *"
    scheduler_morning_advice_cron: str = "30 6 * * *"
    scheduler_baseline_cron: str = "0 3 * * *"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path
        return self.app_data_dir / "healthcare.sqlite3"

    def resolved_garmin_token_dir(self) -> Path:
        if self.garmin_token_dir is not None:
            return self.garmin_token_dir
        return self.app_data_dir / "garmin_tokens"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
