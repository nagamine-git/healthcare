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
    llm_model: str = "claude-haiku-4-5"
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
        ]
    )
    # 候補種目 (LLM はこの中から組む)
    user_training_options: list[str] = Field(
        default_factory=lambda: [
            "ラッキング",
            "ランニング",
            "HIIT",
            "ダンベルベンチプレス",
            "ダンベルゴブレットスクワット",
            "ダンベルルーマニアンデッドリフト",
            "ダンベルロー",
            "プッシュアップ",
            "アブローラー (膝つき)",
            "ヒップスラスト",
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
    user_weekly_split_hint: str = (
        "月: HIIT 20分 / 火: 上半身 push / 水: ラッキング Z2 / "
        "木: 上半身 pull + コア / 金: 下半身 / 土: ラッキング ロング / 日: 完全休"
    )

    # --- 栄養目標 ---
    target_protein_g_per_kg: float = 2.0  # recomposition 想定
    target_water_ml_per_kg: float = 35.0
    # 摂取カロリー目標は TDEE (= 当日の active + basal energy 合計、Apple Health から推定) を基準にする

    # --- トレーニング処方の開始重量 (前回実績が無いときの保守的スタート) ---
    # 腰のケガ歴を考慮し、ヒンジ系は 8kg から、全般に控えめに開始。
    # 利用可能な刻みは 2/4/8/12/16/20kg のみ なので、それ以外を絶対に使わない。
    user_starting_weights: dict[str, str] = Field(
        default_factory=lambda: {
            "ダンベルベンチプレス": "8kg×2",
            "ダンベルショルダープレス": "4kg×2",
            "ダンベルロー (片手)": "8kg",
            "ダンベルゴブレットスクワット": "8kg",
            "ダンベルルーマニアンデッドリフト": "8kg×2",
            "ダンベルヒップスラスト": "8kg×2",
            "ダンベルカール": "4kg×2",
            "プッシュアップ (プッシュアップバー)": "自重",
            "アブローラー (膝つき)": "自重",
            "カーフレイズ": "自重 or 8kg×2",
            "ラッキング": "リュックサック 5kg 入り",
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
