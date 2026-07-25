"""TIDE (Garmin ウォッチアプリ) からの水分・カフェイン取り込み API。

TIDE は Instinct 3 上で動く Connect IQ アプリで、水分とカフェインをワンタップで記録する。
時計側はオフラインでも完結し、記録した瞬間 (または後でバックグラウンドから) ここへ POST する。

設計上の要点:

- **冪等性**: 時計側は送信失敗をキューに積んで再送するため、同じエントリが複数回届きうる。
  水分は ``MetricSample`` の UniqueConstraint (source, metric_key, ts) が重複を弾く。
  カフェインは ts + source の一致で既存行を探して skip する。

- **カフェインは既存の ``CaffeineIntake`` に流す**。これにより偏頭痛のトリガー分析
  (``scoring/migraine_triggers.py``) や就寝前アドバイスに追加実装なしで合流する。
  鎮痛薬由来 (TIDE の種別 6) は ``ibuquick`` として記録し、
  ``MEDICATION_CAFFEINE_SOURCES`` による除外・MOH 判定が効くようにする。

- **ループ防止**: 水分は ``metric_key="tide_hydration_ml"`` (source="tide") に書く。
  Garmin Connect へ書き戻すと ``garmin_sync`` が ``garmin_hydration_ml`` として
  読み戻して二重計上になるため、**Garmin Connect への書き込みは行わない**。
  Apple Health への反映は Ascend iOS 側が担当する (write-only ミラー)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import session_scope
from app.models import CaffeineIntake, MetricSample

router = APIRouter()

HYDRATION_METRIC_KEY = "tide_hydration_ml"
SOURCE = "tide"

# TIDE の種別 ID → (healthcare の CaffeineIntake.source, 単位ラベル)
# 時計側のプリセット順と一致させること (garmin-tide の Model.PRESET_ML / PRESET_MG)。
#   0=水(小) 1=水(大) 2=珈琲 3=茶 4=エナジー 5=酒 6=鎮痛薬
TYPE_TO_CAFFEINE_SOURCE: dict[int, str] = {
    2: "drip_coffee",
    3: "green_tea",
    4: "manual",      # エナジードリンク。healthcare 側に専用プリセットが無いため manual 扱い
    6: "ibuquick",    # 鎮痛薬。MOH 判定と偏頭痛分析の除外対象に載せるため専用ソースにする
}


def _verify_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.tide_ingest_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TIDE_INGEST_TOKEN is not configured.",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required.")
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")


class TideEntry(BaseModel):
    """時計 1 タップぶんの記録。キー名は BLE 経由の転送量を抑えるため短くしてある。"""

    t: int = Field(description="epoch 秒 (UTC)")
    k: int = Field(description="種別 ID (0=水小 1=水大 2=珈琲 3=茶 4=エナジー 5=酒 6=鎮痛薬)")
    ml: int = Field(default=0, ge=0, le=5000, description="水分 mL")
    mg: int = Field(default=0, ge=0, le=1000, description="カフェイン mg")


class TidePayload(BaseModel):
    dev: str = Field(default="tide", max_length=64)
    entries: list[TideEntry] = Field(default_factory=list, max_length=50)


@router.post("/api/tide/ingest", status_code=status.HTTP_200_OK)
def ingest_tide(payload: TidePayload, _: None = Depends(_verify_token)) -> dict[str, Any]:
    """TIDE からの記録を取り込む。

    レスポンスは意図的に小さく保つ。Connect IQ のレスポンスサイズ上限は機種依存かつ
    非公開で、数十 KB で ``-402``/``-403`` になる報告があるため。
    """
    water_added = 0
    caffeine_added = 0
    skipped = 0

    with session_scope() as session:
        for e in payload.entries:
            ts = datetime.fromtimestamp(e.t, tz=UTC).replace(tzinfo=None)  # UTC naive で統一

            if e.ml > 0:
                exists = session.execute(
                    select(MetricSample.id).where(
                        MetricSample.source == SOURCE,
                        MetricSample.metric_key == HYDRATION_METRIC_KEY,
                        MetricSample.ts == ts,
                    )
                ).first()
                if exists:
                    skipped += 1
                else:
                    session.add(
                        MetricSample(
                            source=SOURCE,
                            metric_key=HYDRATION_METRIC_KEY,
                            ts=ts,
                            value=float(e.ml),
                            unit="mL",
                            raw_json={"type": e.k, "dev": payload.dev},
                        )
                    )
                    water_added += 1

            if e.mg > 0:
                src = TYPE_TO_CAFFEINE_SOURCE.get(e.k, "manual")
                dup = session.execute(
                    select(CaffeineIntake.id).where(
                        CaffeineIntake.ts == ts,
                        CaffeineIntake.source == src,
                    )
                ).first()
                if dup:
                    skipped += 1
                else:
                    session.add(
                        CaffeineIntake(
                            ts=ts,
                            source=src,
                            amount=1.0,
                            unit="杯" if e.k in (2, 3) else ("錠" if e.k == 6 else "mg"),
                            mg=float(e.mg),
                            note="TIDE",
                            dose_pct=100.0,
                        )
                    )
                    caffeine_added += 1

    return {"ok": True, "w": water_added, "c": caffeine_added, "s": skipped}
