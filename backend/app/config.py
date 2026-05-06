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

    # 利用可能な機材 (LLM 用)
    user_equipment: list[str] = Field(
        default_factory=lambda: [
            "プッシュアップバー (小型)",
            "アブローラー",
            "フラットベンチ",
            "ダンベル (2/4/8/12/16/20kg に調節可)",
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
