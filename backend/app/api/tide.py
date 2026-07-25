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

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.config import Settings, get_settings
from app.db import session_scope
from app.models import CaffeineIntake, MetricSample, MigraineEpisode
from app.scoring.caffeine import MEDICATION_CAFFEINE_SOURCES

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


# 偏頭痛の未終了エピソードをこの時間まで active とみなす (migraine.py と揃える。
# これを超えたものは終了し忘れの放置データで、残ると新規記録を永久に弾く事故になる)
_ACTIVE_MAX_AGE_H = 48

# ICHD-3: カフェイン配合の複合鎮痛薬は月10日で乱用域 (単純鎮痛薬の15日ではない)
MOH_LIMIT_DAYS = 10


def _moh_days(session) -> int:
    """直近30日で頭痛薬を飲んだ **日数** (JST日付でdistinct。同日複数回は1日)。

    集計方法は ``scoring/wellbeing_alerts._check_moh_risk`` と揃えてある。
    ここで返すのは時計側に「今何日目か」を出すためで、判定そのものはサーバーが持つ。
    """
    lo = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    day_expr = func.date(CaffeineIntake.ts, "+9 hours")
    n = session.execute(
        select(func.count(func.distinct(day_expr))).where(
            CaffeineIntake.ts >= lo,
            CaffeineIntake.source.in_(tuple(MEDICATION_CAFFEINE_SOURCES)),
        )
    ).scalar()
    return int(n or 0)


def _apply_migraine_event(session, ts: datetime, ev: str) -> str:
    """偏頭痛イベントを適用する。**例外を投げないこと** —
    1件の異常で payload 全体が 500 になると、時計が同じ payload を再送し続けて
    同期が永久に詰まる (同一秒2件の不具合と同じ失敗様式)。

    冪等性: 時計は送信失敗をキューに積んで再送するため、同じイベントが複数回届きうる。
    - mig_start: 既に active なエピソードがあれば何もしない (重複作成を防ぐ)
    - mig_end:   active が無ければ何もしない
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=_ACTIVE_MAX_AGE_H)
    active = session.execute(
        select(MigraineEpisode)
        .where(MigraineEpisode.ended_at.is_(None), MigraineEpisode.started_at >= cutoff)
        .order_by(MigraineEpisode.started_at.desc())
    ).scalars().first()

    if ev == "mig_start":
        if active is not None:
            return "skip"
        session.add(MigraineEpisode(started_at=ts, ended_at=None, severity=None, note="TIDE"))
        return "start"
    if ev == "mig_end":
        if active is None:
            return "skip"
        active.ended_at = ts if ts > active.started_at else active.started_at
        return "end"
    return "skip"


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
    ev: str | None = Field(
        default=None,
        description='イベント種別。"mig_start" / "mig_end" のとき偏頭痛エピソードを操作する '
        "(この場合 ml/mg は無視)",
    )


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
    migraine_applied = 0
    skipped = 0

    # ⚠️ 同一 payload 内で ts が衝突しうる (同じ秒に「水」と「珈琲」を続けてタップする等)。
    # MetricSample は (source, metric_key, ts) が UNIQUE なので、素朴に 1 件ずつ add すると
    # 事前の exists チェックは**未 flush の行を見られず**すり抜け、commit 時に IntegrityError で
    # payload 全体が 500 になる。時計は失敗した payload を再送し続けるため、
    # **同じ秒に 2 回タップしただけで同期が永久に詰まる**。
    # 秒単位で合算して 1 ts = 1 行にすることで回避する (合算は意味的にも正しい —
    # その秒に実際に飲んだ総量になる)。カフェインも同じ理由で (ts, source) 単位に合算する。
    water_ml: dict[datetime, float] = {}
    water_kind: dict[datetime, int] = {}
    caffeine_mg: dict[tuple[datetime, str], float] = {}
    caffeine_kind: dict[tuple[datetime, str], int] = {}

    events: list[tuple[datetime, str]] = []

    for e in payload.entries:
        ts = datetime.fromtimestamp(e.t, tz=UTC).replace(tzinfo=None)  # UTC naive で統一
        if e.ev:
            events.append((ts, e.ev))
            continue                      # イベント行は ml/mg を持たない
        if e.ml > 0:
            water_ml[ts] = water_ml.get(ts, 0.0) + float(e.ml)
            water_kind.setdefault(ts, e.k)
        if e.mg > 0:
            key = (ts, TYPE_TO_CAFFEINE_SOURCE.get(e.k, "manual"))
            caffeine_mg[key] = caffeine_mg.get(key, 0.0) + float(e.mg)
            caffeine_kind.setdefault(key, e.k)

    with session_scope() as session:
        for ts, ml in sorted(water_ml.items()):
            exists = session.execute(
                select(MetricSample.id).where(
                    MetricSample.source == SOURCE,
                    MetricSample.metric_key == HYDRATION_METRIC_KEY,
                    MetricSample.ts == ts,
                )
            ).first()
            if exists:
                skipped += 1
                continue
            session.add(
                MetricSample(
                    source=SOURCE,
                    metric_key=HYDRATION_METRIC_KEY,
                    ts=ts,
                    value=ml,
                    unit="mL",
                    raw_json={"type": water_kind[ts], "dev": payload.dev},
                )
            )
            water_added += 1

        for (ts, src), mg in sorted(caffeine_mg.items()):
            dup = session.execute(
                select(CaffeineIntake.id).where(
                    CaffeineIntake.ts == ts,
                    CaffeineIntake.source == src,
                )
            ).first()
            if dup:
                skipped += 1
                continue
            k = caffeine_kind[(ts, src)]
            session.add(
                CaffeineIntake(
                    ts=ts,
                    source=src,
                    amount=1.0,
                    unit="杯" if k in (2, 3) else ("錠" if k == 6 else "mg"),
                    mg=mg,
                    note="TIDE",
                    dose_pct=100.0,
                )
            )
            caffeine_added += 1

        # 偏頭痛イベントは時系列順に適用する (start→end の順序が崩れると active 判定がずれる)
        for ts, ev in sorted(events):
            if _apply_migraine_event(session, ts, ev) == "skip":
                skipped += 1
            else:
                migraine_applied += 1

        moh = _moh_days(session)

    # 時計は "moh" を見て鎮痛薬の記録画面に「今月 n/10 日」を出す。
    # 判定基準はサーバー側 (MOH_LIMIT_DAYS) を正とし、時計はそれを表示するだけにする。
    return {
        "ok": True,
        "w": water_added,
        "c": caffeine_added,
        "s": skipped,
        "m": migraine_applied,
        "moh": moh,
        "mohMax": MOH_LIMIT_DAYS,
    }


class TideWaterOut(BaseModel):
    id: int
    ts: str
    ml: float


class TideCaffeineOut(BaseModel):
    id: int
    ts: str
    mg: float


class TideHealthExportOut(BaseModel):
    water: list[TideWaterOut]
    caffeine: list[TideCaffeineOut]


def _iso_utc(ts: datetime) -> str:
    ts_utc = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
    return ts_utc.isoformat()


@router.get("/api/tide/health-export", response_model=TideHealthExportOut)
def tide_health_export(
    hours: int = Query(default=72, ge=1, le=720),
) -> TideHealthExportOut:
    """TIDE 由来の水分・カフェインを **Apple Health へミラーするための読み出し専用** API。

    Ascend (iOS) がこのエンドポイントを定期的に叩き、TIDE (Garmin ウォッチアプリ) で
    記録された水分・カフェインを HealthKit へ書き込む。ingest (`POST /api/tide/ingest`)
    と対になる、逆方向 (healthcare → Apple Health) のデータフローを担う。

    認証は掛けていない。他の read 系エンドポイントと同じく tailnet 限定運用が前提。
    `POST /api/tide/ingest` の token 認証 (``_verify_token``) はそのまま維持している —
    ここを無認証にしたのは書き込みではなく読み出しのみだから。

    設計上、絶対に崩してはいけない制約:

    - **水分は ``metric_key == HYDRATION_METRIC_KEY`` (= ``tide_hydration_ml``) の
      ``MetricSample`` のみを返す。``dietary_water`` を絶対に含めないこと。**
      ``dietary_water`` は Ascend が Apple Health から読み取って healthcare に送って
      いる値であり、それをここで折り返して Apple Health に書き戻すと
      無限ループ・二重計上になる。
    - **カフェインは ``CaffeineIntake.note == "TIDE"`` のものだけを返す。**
      ``source`` は手動記録 (``app/api/caffeine.py``) と共有される値のため、
      TIDE 由来かどうかの判別には使えない (`ingest_tide` の docstring 参照)。
    - ``id`` は DB の autoincrement PK をそのまま返す。Ascend はこれを HealthKit の
      ``HKMetadataKeySyncIdentifier`` として使い、同じ記録を何度書き込んでも重複しない
      ようにする (冪等な書き込み)。安定した一意値であることが要件。
    """
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)

    with session_scope() as session:
        water_rows = (
            session.execute(
                select(MetricSample)
                .where(
                    MetricSample.source == SOURCE,
                    MetricSample.metric_key == HYDRATION_METRIC_KEY,
                    MetricSample.ts >= since,
                )
                .order_by(MetricSample.ts)
            )
            .scalars()
            .all()
        )
        caffeine_rows = (
            session.execute(
                select(CaffeineIntake)
                .where(CaffeineIntake.note == "TIDE", CaffeineIntake.ts >= since)
                .order_by(CaffeineIntake.ts)
            )
            .scalars()
            .all()
        )

        return TideHealthExportOut(
            water=[
                TideWaterOut(id=r.id, ts=_iso_utc(r.ts), ml=float(r.value or 0.0))
                for r in water_rows
            ],
            caffeine=[
                TideCaffeineOut(id=r.id, ts=_iso_utc(r.ts), mg=r.mg) for r in caffeine_rows
            ],
        )
