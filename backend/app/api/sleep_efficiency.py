"""「時間あたりの回復効率」API (読み取り専用)。

薄いだけ: `sleep_drivers._collect()` で行を作り、`sleep_drivers.analyze()` の結果 (要因分析)
と合わせて `scoring/sleep_efficiency.py:analyze_recovery_efficiency` に委譲するだけ。
統計ロジックは一切ここに書かない。

⚠️ `sleep_drivers._collect()` / `analyze()` はどちらも内部で `session_scope()` を開いて
plain dict のみを返す (ORM オブジェクトを外へ持ち出さない)。このファイル自体は
session_scope を一切使わないため detach の心配はない。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.scoring import sleep_drivers
from app.scoring.sleep_efficiency import analyze_recovery_efficiency
from app.scoring.timewindow import app_today

router = APIRouter()


@router.get("/api/sleep/efficiency")
async def get_sleep_efficiency() -> dict[str, Any]:
    """睡眠時間ではなく効率・深睡眠が翌日の回復を左右することを示す分析。"""
    target = app_today()
    rows = sleep_drivers._collect(target)
    driver = sleep_drivers.analyze(target)
    return analyze_recovery_efficiency(rows, driver_quality=driver.get("quality"))
