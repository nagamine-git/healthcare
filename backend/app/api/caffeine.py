"""カフェイン摂取の手動記録 API。

プリセット (インスタントコーヒー / 缶コーヒー / ネスプレッソ / イブクイック) と
mg 直接入力をサポートする。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import CaffeineIntake

router = APIRouter()


Source = Literal[
    "instant_coffee",
    "canned_coffee",
    "nespresso",
    "green_tea",
    "ibuquick",
    "bufferin_premium",
    "manual",
]


# プリセットごとの「1 単位」とカフェイン量。Auto Mode で実装するための既定値:
# - インスタントコーヒー: 1g あたり 60mg (config: instant_coffee_mg_per_g)
# - 缶コーヒー: 1 本 100mg (BOSS / GEORGIA / WONDA 標準 190g 缶相当)
# - ネスプレッソ: 1 カプセル 70mg (Ristretto 80 / Lungo 60 の中間)
# - イブクイック頭痛薬 (エスエス): **1 錠あたり無水カフェイン 40mg**、用法 1 回 2 錠で 80mg
#   (添付文書: イブプロフェン 100mg / 無水カフェイン 40mg / 他)
# - バファリンプレミアム (ライオン): **1 錠あたり無水カフェイン 40mg**、用法 1 回 2 錠で 80mg
#   (添付文書: イブプロフェン 65mg / アセトアミノフェン 65mg / 無水カフェイン 40mg / 他)
PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "instant_coffee": {"unit": "g", "default_amount": 2.0, "mg_per_unit": 60.0},
    "canned_coffee": {"unit": "本", "default_amount": 1.0, "mg_per_unit": 100.0},
    "nespresso": {"unit": "カプセル", "default_amount": 1.0, "mg_per_unit": 70.0},
    # 緑茶 (煎茶): 浸出液 20mg/100ml (日本食品標準成分表)、湯呑み 1 杯 150ml ≈ 30mg
    "green_tea": {"unit": "杯", "default_amount": 1.0, "mg_per_unit": 30.0},
    "ibuquick": {"unit": "錠", "default_amount": 2.0, "mg_per_unit": 40.0},
    "bufferin_premium": {"unit": "錠", "default_amount": 2.0, "mg_per_unit": 40.0},
    "manual": {"unit": "mg", "default_amount": 0.0, "mg_per_unit": 1.0},
}


class CaffeineIntakeIn(BaseModel):
    source: Source
    amount: float = Field(gt=0, description="量。manual の場合は mg そのもの")
    note: str | None = None
    # 任意で過去時刻を指定可能。省略時は now。
    ts_iso: str | None = None


class CaffeineIntakeOut(BaseModel):
    id: int
    ts: str
    ts_jst: str
    source: str
    amount: float
    unit: str
    mg: float
    note: str | None = None


@router.post("/api/caffeine", response_model=CaffeineIntakeOut)
async def add_caffeine_intake(body: CaffeineIntakeIn) -> CaffeineIntakeOut:
    settings = get_settings()
    if body.source not in PRESET_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"unknown source: {body.source}")

    preset = PRESET_DEFAULTS[body.source]
    # インスタントコーヒーは config から動的に取得 (ユーザーが変更している可能性)
    mg_per_unit = (
        settings.instant_coffee_mg_per_g
        if body.source == "instant_coffee"
        else float(preset["mg_per_unit"])
    )
    mg = body.amount * mg_per_unit

    if body.ts_iso:
        try:
            ts = datetime.fromisoformat(body.ts_iso)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid ts_iso: {exc}") from exc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        ts_utc = ts.astimezone(UTC).replace(tzinfo=None)
    else:
        ts_utc = datetime.now(UTC).replace(tzinfo=None)

    with session_scope() as session:
        row = CaffeineIntake(
            ts=ts_utc,
            source=body.source,
            amount=body.amount,
            unit=preset["unit"],
            mg=mg,
            note=body.note,
        )
        session.add(row)
        session.flush()
        return _to_out(row, settings.app_tz)


@router.get("/api/caffeine")
async def list_caffeine_intakes(hours: int = 24) -> dict[str, Any]:
    """直近 hours 時間の摂取記録を返す。"""
    settings = get_settings()
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    with session_scope() as session:
        rows = session.execute(
            select(CaffeineIntake).where(CaffeineIntake.ts >= since).order_by(CaffeineIntake.ts)
        ).scalars().all()
        return {
            "items": [_to_out(r, settings.app_tz).model_dump() for r in rows],
            "total_mg": sum(r.mg for r in rows),
        }


class CaffeineIntakePatch(BaseModel):
    """編集可能フィールド。指定されたものだけ更新する。

    amount を変えると、source の mg_per_unit を使って mg も再計算する。
    mg を直接指定したい場合は source="manual" + amount=mg にする (上書きできる)。
    """

    ts_iso: str | None = None
    amount: float | None = Field(default=None, gt=0)
    source: Source | None = None
    note: str | None = None


@router.patch("/api/caffeine/{intake_id}", response_model=CaffeineIntakeOut)
async def patch_caffeine_intake(
    intake_id: int, body: CaffeineIntakePatch
) -> CaffeineIntakeOut:
    settings = get_settings()
    with session_scope() as session:
        row = session.get(CaffeineIntake, intake_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")

        if body.ts_iso is not None:
            try:
                ts = datetime.fromisoformat(body.ts_iso)
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail=f"invalid ts_iso: {exc}"
                ) from exc
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            row.ts = ts.astimezone(UTC).replace(tzinfo=None)

        new_source = body.source or row.source
        if body.source is not None:
            row.source = body.source
            row.unit = PRESET_DEFAULTS[body.source]["unit"]

        if body.amount is not None:
            row.amount = body.amount
            mg_per_unit = (
                settings.instant_coffee_mg_per_g
                if new_source == "instant_coffee"
                else float(PRESET_DEFAULTS[new_source]["mg_per_unit"])
            )
            row.mg = body.amount * mg_per_unit

        if body.note is not None:
            row.note = body.note or None  # 空文字は None に正規化

        session.flush()
        return _to_out(row, settings.app_tz)


@router.delete("/api/caffeine/{intake_id}")
async def delete_caffeine_intake(intake_id: int) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(CaffeineIntake, intake_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        session.delete(row)
        return {"deleted": intake_id}


@router.get("/api/caffeine/presets")
async def caffeine_presets() -> dict[str, Any]:
    """フロントエンドが利用するプリセット情報を返す。"""
    settings = get_settings()
    out: dict[str, Any] = {}
    for key, info in PRESET_DEFAULTS.items():
        mg_per_unit = (
            settings.instant_coffee_mg_per_g
            if key == "instant_coffee"
            else info["mg_per_unit"]
        )
        out[key] = {
            "unit": info["unit"],
            "default_amount": info["default_amount"],
            "mg_per_unit": mg_per_unit,
            "default_mg": float(info["default_amount"]) * float(mg_per_unit),
        }
    return out


def current_residual_mg(
    now_jst: datetime,
    half_life_h: float,
    *,
    absorption_half_life_h: float | None = None,
) -> float:
    """摂取記録から現時点での体内残量を計算する (1次吸収/消失 Bateman)。

    過去 18 時間 (≒半減期5hで3.5回 = 残量 ~9%) の摂取を対象に減衰合計。
    「今日のJST 0時以降」だと深夜に飲んだカフェインが日付をまたいだ瞬間に
    残量から消えてしまうため、ローリング窓で見る。

    ここで返すのは「就寝時の安全計算に効く確定済み (committed) 残量」。摂取直後は
    まだ血漿に移行していない (Bateman では ~0) が、就寝までには必ず吸収され寄与する
    ため、未吸収ぶんも満額カウントする (= 安全側)。これは終末相の
    ``absorption_factor × half_life_decay`` に等しく、吸収済みの過去用量では
    Bateman の体内量と一致する。
    """
    from app.scoring.caffeine import absorption_factor, half_life_decay

    factor = absorption_factor(half_life_h, absorption_half_life_h)
    now_utc = now_jst.astimezone(UTC)
    start_utc = (now_utc - timedelta(hours=18)).replace(tzinfo=None)

    total = 0.0
    with session_scope() as session:
        rows = session.execute(
            select(CaffeineIntake).where(CaffeineIntake.ts >= start_utc)
        ).scalars().all()
        for r in rows:
            # naive UTC → aware
            ts_utc = r.ts.replace(tzinfo=UTC) if r.ts.tzinfo is None else r.ts
            elapsed_h = (now_jst.astimezone(UTC) - ts_utc).total_seconds() / 3600
            if elapsed_h < 0:
                continue
            total += half_life_decay(r.mg, elapsed_h, half_life_h=half_life_h)
    return total * factor


def _to_out(row: CaffeineIntake, tz_name: str) -> CaffeineIntakeOut:
    tz = ZoneInfo(tz_name)
    ts_utc = row.ts.replace(tzinfo=UTC) if row.ts.tzinfo is None else row.ts
    ts_jst = ts_utc.astimezone(tz)
    # 当日なら HH:MM のみ、それ以前は MM/DD HH:MM
    now_jst = datetime.now(tz)
    same_day = ts_jst.date() == now_jst.date()
    ts_label = (
        ts_jst.strftime("%H:%M") if same_day else ts_jst.strftime("%m/%d %H:%M")
    )
    return CaffeineIntakeOut(
        id=row.id,
        ts=ts_utc.isoformat(),
        ts_jst=ts_label,
        source=row.source,
        amount=row.amount,
        unit=row.unit,
        mg=row.mg,
        note=row.note,
    )
