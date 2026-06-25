"""Compass (価値観 × マインドセット) の API。

集約 GET /api/identity と、SJT・意思決定ログ・IMDb 取込・作品タグ・内省→実行意図・
フィードバックの POST 群。ビジネスロジックは scoring/identity と llm/identity に置き、
ここは薄く保つ (session_scope + Pydantic)。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import session_scope
from app.llm import identity as llm_identity
from app.models.health import (
    IdentityAssessment,
    IdentityDecisionLog,
    MediaItem,
    MediaLog,
)
from app.scoring.identity import store
from app.scoring.identity.dimensions import DIMENSIONS
from app.scoring.timewindow import app_today

router = APIRouter()


def _catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": d.id,
            "layer": d.layer,
            "name": d.name_ja,
            "description": d.description,
            "research_basis": d.research_basis,
        }
        for d in DIMENSIONS
    ]


# ---------------------------------------------------------------------------
# 集約 read
# ---------------------------------------------------------------------------
@router.get("/api/identity")
async def get_identity() -> dict[str, Any]:
    with session_scope() as session:
        report = store.build_gap_report(session)
        recommendations = store.recommend_media(session)

        # 直近の意思決定ログ。
        recent_logs = [
            {
                "id": r.id,
                "date": r.date.isoformat(),
                "text": r.text,
                "inferred": (r.inferred or {}).get("signals", []),
            }
            for r in session.execute(
                select(IdentityDecisionLog)
                .order_by(IdentityDecisionLog.created_at.desc())
                .limit(10)
            ).scalars()
        ]

        # 進行中/完了した実行意図 (内省ループの outcome)。
        intentions = [
            {
                "media_item_id": log.media_item_id,
                "title": item.title if item else None,
                "dimension_id": log.dimension_id,
                "intention": log.intention,
                "done": log.intention_done,
                "rating": log.intention_rating,
                "seen_at": log.seen_at.isoformat() if log.seen_at else None,
            }
            for log, item in session.execute(
                select(MediaLog, MediaItem)
                .join(MediaItem, MediaItem.id == MediaLog.media_item_id)
                .where(MediaLog.intention.is_not(None))
                .order_by(MediaLog.updated_at.desc())
                .limit(10)
            ).all()
        ]

        # ライブラリ統計。
        total_media = session.execute(select(MediaItem)).scalars().all()
        seen = sum(
            1
            for r in session.execute(
                select(MediaLog).where(MediaLog.status == "seen")
            ).scalars()
        )
        untagged = sum(1 for m in total_media if not (m.dimension_tags or {}))

        return {
            "date": app_today().isoformat(),
            "catalog": _catalog(),
            "report": report,
            "recommendations": recommendations,
            "recent_logs": recent_logs,
            "intentions": intentions,
            "library": {
                "total": len(total_media),
                "seen": seen,
                "untagged": untagged,
            },
        }


# ---------------------------------------------------------------------------
# SJT (状況判断テスト)
# ---------------------------------------------------------------------------
class SjtTurnIn(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/api/identity/sjt")
async def sjt_turn(body: SjtTurnIn) -> dict[str, Any]:
    """SJT を 1 ターン進める (会話履歴はフロント保持)。"""
    return await llm_identity.sjt_turn(body.messages)


class SjtCommitIn(BaseModel):
    result: dict[str, float] = Field(..., description="{dimension_id: 0-100} の本測結果")


@router.post("/api/identity/sjt/commit")
async def sjt_commit(body: SjtCommitIn) -> dict[str, Any]:
    """SJT 本測の結果を保存し、現在地を再計算する。"""
    with session_scope() as session:
        session.add(
            IdentityAssessment(kind="sjt", result=body.result, created_at=datetime.utcnow())
        )
        session.flush()
        store.recompute_dimension_scores(session)
        return store.build_gap_report(session)


# ---------------------------------------------------------------------------
# 意思決定ログ
# ---------------------------------------------------------------------------
class DecisionLogIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    date: str | None = None


@router.post("/api/identity/decision-log")
async def post_decision_log(body: DecisionLogIn) -> dict[str, Any]:
    """意思決定ログを記録し、LLM で次元推定 → 現在地を再計算する。"""
    signals = await llm_identity.infer_decision_log(body.text)
    d = date_type.fromisoformat(body.date) if body.date else app_today()
    with session_scope() as session:
        session.add(
            IdentityDecisionLog(
                date=d, text=body.text, inferred={"signals": signals},
                created_at=datetime.utcnow(),
            )
        )
        session.flush()
        store.recompute_dimension_scores(session)
        return {"inferred": signals, "report": store.build_gap_report(session)}


# ---------------------------------------------------------------------------
# IMDb 取込
# ---------------------------------------------------------------------------
class ImdbImportIn(BaseModel):
    csv: str = Field(..., description="IMDb エクスポート CSV の中身")
    list_kind: str = Field(..., pattern="^(ratings|watchlist)$")


@router.post("/api/identity/imdb-import")
async def imdb_import(body: ImdbImportIn) -> dict[str, Any]:
    """IMDb の ratings.csv / watchlist.csv を取り込む。"""
    from app.ingest.imdb_import import import_media, parse_imdb_csv

    items = parse_imdb_csv(body.csv, list_kind=body.list_kind)
    with session_scope() as session:
        counts = import_media(session, items)
    return {"status": "ok", **counts}


# ---------------------------------------------------------------------------
# 作品: 手動登録・次元タグ付け
# ---------------------------------------------------------------------------
class ManualMediaIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    kind: str = Field(..., pattern="^(film|tv|manga|book)$")
    year: int | None = Field(default=None, ge=1800, le=2200)
    overview: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="watchlist", pattern="^(watchlist|seen)$")


@router.post("/api/identity/media")
async def add_manual_media(body: ManualMediaIn) -> dict[str, Any]:
    """マンガ・本などを手動登録し、LLM で次元タグを付ける。"""
    tags = await llm_identity.tag_media_dimensions(
        title=body.title, kind=body.kind, year=body.year, overview=body.overview
    )
    with session_scope() as session:
        item = MediaItem(
            source="manual",
            kind=body.kind,
            title=body.title,
            year=body.year,
            metadata_json={"overview": body.overview} if body.overview else None,
            dimension_tags=tags or None,
            tag_source="llm" if tags else None,
        )
        session.add(item)
        session.flush()
        session.add(MediaLog(media_item_id=item.id, status=body.status))
        return {"status": "ok", "media_item_id": item.id, "tags": tags}


def _count_untagged(session) -> int:
    return sum(
        1 for m in session.execute(select(MediaItem)).scalars() if not (m.dimension_tags or {})
    )


@router.post("/api/identity/media/tag-untagged")
async def tag_untagged(limit: int = Body(default=5, embed=True)) -> dict[str, Any]:
    """未タグの作品を最大 limit 件だけ LLM タグ付けする (小バッチ)。

    1 件ずつ独立にコミットし、1 件が失敗しても残りは継続する。途中で止まっても
    タグ済みは保存される。返り値の remaining が 0 になるまでフロントが繰り返し呼ぶ。
    """
    with session_scope() as session:
        pending = [
            {
                "id": m.id,
                "title": m.title,
                "kind": m.kind,
                "year": m.year,
                "overview": (m.metadata_json or {}).get("overview"),
            }
            for m in session.execute(select(MediaItem)).scalars()
            if not (m.dimension_tags or {})
        ][:limit]

    tagged = 0
    failed = 0
    for p in pending:
        try:
            tags = await llm_identity.tag_media_dimensions(
                title=p["title"], kind=p["kind"], year=p["year"], overview=p["overview"]
            )
        except Exception:
            failed += 1
            continue
        with session_scope() as session:
            item = session.get(MediaItem, p["id"])
            if item is not None:
                # タグ無し判定でも sentinel を入れて「処理済み」にし、再処理ループを防ぐ。
                item.dimension_tags = tags if tags else {"_none": 0}
                item.tag_source = "llm"
                if tags:
                    tagged += 1

    with session_scope() as session:
        remaining = _count_untagged(session)
    return {"status": "ok", "tagged": tagged, "failed": failed, "remaining": remaining}


@router.post("/api/identity/suggest-new")
async def suggest_new(n: int = Body(default=8, embed=True)) -> dict[str, Any]:
    """伸びしろの大きい次元向けに、リスト外の新規作品を LLM 提案して保存する。

    保存した提案は source="llm_suggestion" として推薦リストに category="new" で並ぶ。
    """
    from app.scoring.identity.dimensions import BY_ID

    with session_scope() as session:
        report = store.build_gap_report(session)
        weak_ids = report["weakest"][:5]
        weak = [(d, BY_ID[d].name_ja) for d in weak_ids if d in BY_ID]
        avoid = [m.title for m in session.execute(select(MediaItem)).scalars()]

    if not weak:
        return {"status": "no_gap", "created": 0, "suggestions": []}

    suggestions = await llm_identity.suggest_new_media(weak_dims=weak, avoid_titles=avoid, n=n)

    created = 0
    avoid_lower = {t.strip().lower() for t in avoid}
    with session_scope() as session:
        for s in suggestions:
            if s["title"].strip().lower() in avoid_lower:
                continue
            session.add(
                MediaItem(
                    source="llm_suggestion",
                    kind=s["kind"],
                    title=s["title"],
                    year=s["year"],
                    metadata_json={"reason": s["reason"]},
                    dimension_tags={s["dimension_id"]: 1.0},
                    tag_source="llm",
                )
            )
            avoid_lower.add(s["title"].strip().lower())
            created += 1
    return {"status": "ok", "created": created, "suggestions": suggestions}


# ---------------------------------------------------------------------------
# 視聴後の内省 → 実行意図ループ
# ---------------------------------------------------------------------------
class ReflectIn(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/api/identity/media/{media_item_id}/reflect")
async def reflect(media_item_id: int, body: ReflectIn) -> dict[str, Any]:
    """作品の内省を 1 ターン進める (会話履歴はフロント保持)。"""
    with session_scope() as session:
        item = session.get(MediaItem, media_item_id)
        if item is None:
            return {"error": "not_found"}
        title = item.title
        target = list((item.dimension_tags or {}).keys())
    return await llm_identity.reflect_to_intention(
        title=title, target_dimensions=target, messages=body.messages
    )


class IntentionIn(BaseModel):
    intention: str = Field(min_length=1, max_length=500)
    dimension_id: str | None = None
    reflection: str | None = Field(default=None, max_length=2000)


@router.post("/api/identity/media/{media_item_id}/intention")
async def save_intention(media_item_id: int, body: IntentionIn) -> dict[str, Any]:
    """実行意図を確定し、作品を seen にする。"""
    with session_scope() as session:
        item = session.get(MediaItem, media_item_id)
        if item is None:
            return {"error": "not_found"}
        log = session.get(MediaLog, media_item_id)
        if log is None:
            log = MediaLog(media_item_id=media_item_id)
            session.add(log)
        log.status = "seen"
        if log.seen_at is None:
            log.seen_at = datetime.utcnow()
        log.dimension_id = body.dimension_id
        log.reflection = body.reflection
        log.intention = body.intention
        log.intention_done = False
        log.intention_rating = 0
        log.updated_at = datetime.utcnow()
    return {"status": "ok"}


class IntentionFeedbackIn(BaseModel):
    done: bool = False
    rating: int = Field(default=0, ge=-1, le=1)


@router.post("/api/identity/media/{media_item_id}/intention/feedback")
async def intention_feedback(media_item_id: int, body: IntentionFeedbackIn) -> dict[str, Any]:
    """実行意図の完遂・有用度を記録する (outcome ループ)。"""
    with session_scope() as session:
        log = session.get(MediaLog, media_item_id)
        if log is None:
            return {"error": "not_found"}
        log.intention_done = body.done
        log.intention_rating = body.rating
        log.updated_at = datetime.utcnow()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 理想プロファイル (アーキタイプ) の更新
# ---------------------------------------------------------------------------
class ArchetypeIn(BaseModel):
    name: str | None = None
    target_profile: dict[str, float] | None = None
    weights: dict[str, float] | None = None


@router.post("/api/identity/archetype")
async def update_archetype(body: ArchetypeIn) -> dict[str, Any]:
    """理想プロファイルを差し替える (型の差し替え可能性を担保)。"""
    from app.models.health import IdentityArchetype

    with session_scope() as session:
        row = session.get(IdentityArchetype, 1)
        if row is None:
            row = IdentityArchetype(id=1)
            session.add(row)
        if body.name is not None:
            row.name = body.name
        if body.target_profile is not None:
            row.target_profile = body.target_profile
        if body.weights is not None:
            row.weights = body.weights
        row.updated_at = datetime.utcnow()
        session.flush()
        return store.build_gap_report(session)
