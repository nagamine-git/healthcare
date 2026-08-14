"""寝室の環境 (温度・湿度・CO2) を MetricSample に記録するジョブ。

⚠️ 既存の外気温ドライバー (`surface_temperature_c`) は**残す**。寝室データが貯まるまでの
繋ぎとして機能し、貯まった後も「外気温では説明できない室温の効果」を切り分けられる。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import session_scope
from app.integrations.switchbot import read_bedroom
from app.jobs import blocking_job
from app.logging import get_logger
from app.models import MetricSample

logger = get_logger(__name__)

# 睡眠ドライバー側と共有するキー名 (ここを変えるなら sleep_drivers も直すこと)
TEMP_KEY = "bedroom_temp_c"
HUMIDITY_KEY = "bedroom_humidity_pct"
CO2_KEY = "bedroom_co2_ppm"

_UNITS = {TEMP_KEY: "degC", HUMIDITY_KEY: "%", CO2_KEY: "ppm"}


@blocking_job
def bedroom_env_job() -> dict[str, Any]:
    """寝室メーターを1点サンプリングして保存する。"""
    reading = read_bedroom()
    if reading is None:
        return {"status": "skipped", "reason": "not_configured_or_failed"}

    # ⚠️ 分単位に丸める。SwitchBot は呼んだ瞬間の値を返すので、丸めないと
    # ts が毎回ずれて upsert が効かず、同じ分の点が積み上がる。
    ts = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    values = {
        TEMP_KEY: reading.temp_c,
        HUMIDITY_KEY: reading.humidity_pct,
        CO2_KEY: reading.co2_ppm,
    }
    payload = [
        {"source": "switchbot", "metric_key": k, "ts": ts, "value": v, "unit": _UNITS[k]}
        for k, v in values.items()
        if v is not None  # 取れなかった項目は書かない (0 で埋めない)
    ]
    if not payload:
        return {"status": "empty"}

    with session_scope() as session:
        stmt = sqlite_insert(MetricSample).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[MetricSample.source, MetricSample.metric_key, MetricSample.ts],
            set_={"value": stmt.excluded.value},
        )
        session.execute(stmt)

    out = {"status": "ok", "written": len(payload), **{k: v for k, v in values.items()}}
    logger.info("bedroom_env_recorded", **out)
    return out
