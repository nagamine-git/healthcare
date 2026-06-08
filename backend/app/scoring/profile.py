"""UI 設定の個人プロファイルと env デフォルトを統合する resolve 層。

config.py (env) はデフォルト/例プロファイルを持ち、UI で上書きした値は
user_profile テーブル (単一行) に入る。採点・アラート・LLM・栄養はこの
resolve_profile() を経由して「有効なプロファイル」を読む。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.db import session_scope
from app.models import UserProfile


@dataclass(frozen=True)
class ResolvedProfile:
    height_cm: float
    sex: str
    target_weight_kg: float
    target_body_fat_pct: float
    body_fat_tolerance_pct: float
    ffmi_normalized: float | None
    source: str  # "db" | "default"


def resolve_profile() -> ResolvedProfile:
    """DB 上書きを env デフォルトにマージした有効プロファイルを返す。

    フィールド単位でフォールバックする (DB 行はあるが特定フィールドが NULL なら
    そのフィールドだけ settings を使う)。
    """
    s = get_settings()
    with session_scope() as session:
        row = session.get(UserProfile, 1)
        if row is None:
            return ResolvedProfile(
                height_cm=s.user_height_cm,
                sex=s.user_sex,
                target_weight_kg=s.target_weight_kg,
                target_body_fat_pct=s.target_body_fat_pct,
                body_fat_tolerance_pct=s.body_fat_tolerance_pct,
                ffmi_normalized=None,
                source="default",
            )
        return ResolvedProfile(
            height_cm=row.height_cm if row.height_cm is not None else s.user_height_cm,
            sex=row.sex or s.user_sex,
            target_weight_kg=row.target_weight_kg
            if row.target_weight_kg is not None else s.target_weight_kg,
            target_body_fat_pct=row.target_body_fat_pct
            if row.target_body_fat_pct is not None else s.target_body_fat_pct,
            body_fat_tolerance_pct=row.body_fat_tolerance_pct
            if row.body_fat_tolerance_pct is not None else s.body_fat_tolerance_pct,
            ffmi_normalized=row.ffmi_normalized,
            source="db",
        )
