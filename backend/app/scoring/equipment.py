"""器具の解決 (DB優先・settings フォールバック)。トレ処方の機材制約を動的化する。"""

from __future__ import annotations

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


def resolve_equipment() -> list[str]:
    """available な器具名リスト。DB が空なら settings.user_equipment からシードして返す。"""
    s = get_settings()
    try:
        from sqlalchemy import select

        from app.db import session_scope
        from app.models import EquipmentItem

        with session_scope() as db:
            rows = db.execute(
                select(EquipmentItem).order_by(EquipmentItem.sort, EquipmentItem.id)
            ).scalars().all()
            if not rows:
                for i, name in enumerate(s.user_equipment):
                    db.add(EquipmentItem(name=name, available=True, sort=i))
                db.flush()
                return list(s.user_equipment)
            return [r.name for r in rows if r.available]
    except Exception as exc:  # DB未初期化等でもプロンプトを止めない
        logger.info("equipment_resolve_failed", error=str(exc))
        return list(s.user_equipment)
