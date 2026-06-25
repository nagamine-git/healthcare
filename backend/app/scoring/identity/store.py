"""Compass の DB オーケストレーション。

純粋ロジック (gap.py) と次元定義 (dimensions.py) を、DB の理想プロファイル・
SJT 本測・意思決定ログ・現在地テーブルに接続する。recompute_dimension_scores が
中心: SJT ベースラインを起点に、意思決定ログ観測を EWMA 合成して現在地を更新する。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.health import (
    IdentityArchetype,
    IdentityAssessment,
    IdentityDecisionLog,
    IdentityDimensionScore,
    MediaItem,
    MediaLog,
)
from app.scoring.identity import gap
from app.scoring.identity.dimensions import ALL_IDS, BY_ID

# 現在地合成に使う意思決定ログの遡及窓 (日)。古すぎる行動は現在の自分を表さない。
DECISION_LOOKBACK_DAYS = 90


def get_archetype(session: Session) -> tuple[str, dict[str, float], dict[str, float]]:
    """理想プロファイル (name, targets, weights) を返す。

    DB の IdentityArchetype(id=1) を優先し、未設定の項目は config 既定で補完する。
    """
    settings = get_settings()
    name = settings.identity_archetype_name
    targets = dict(settings.identity_archetype_targets)
    weights = dict(settings.identity_archetype_weights)

    row = session.get(IdentityArchetype, 1)
    if row is not None:
        if row.name:
            name = row.name
        if row.target_profile:
            targets.update({k: float(v) for k, v in row.target_profile.items()})
        if row.weights:
            weights.update({k: float(v) for k, v in row.weights.items()})
    return name, targets, weights


def latest_baselines(session: Session) -> dict[str, float]:
    """最新 SJT 本測の次元別ベースライン。無ければ既存 sjt_baseline で補完。"""
    baselines: dict[str, float] = {}
    last = session.execute(
        select(IdentityAssessment).order_by(IdentityAssessment.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if last and last.result:
        for dim_id, val in last.result.items():
            if dim_id in ALL_IDS and val is not None:
                baselines[dim_id] = float(val)
    # 本測に含まれない次元は既存の保存値で補完。
    for row in session.execute(select(IdentityDimensionScore)).scalars():
        if row.dimension_id not in baselines and row.sjt_baseline is not None:
            baselines[row.dimension_id] = float(row.sjt_baseline)
    return baselines


def _observations_by_dim(session: Session, baselines: dict[str, float]) -> dict[str, list[float]]:
    """遡及窓内の意思決定ログを次元別の観測スコア列 (古い順) に変換する。"""
    cutoff = (datetime.utcnow() - timedelta(days=DECISION_LOOKBACK_DAYS)).date()
    rows = session.execute(
        select(IdentityDecisionLog)
        .where(IdentityDecisionLog.date >= cutoff)
        .order_by(IdentityDecisionLog.created_at.asc())
    ).scalars()
    out: dict[str, list[float]] = {}
    for row in rows:
        signals = (row.inferred or {}).get("signals") if isinstance(row.inferred, dict) else None
        for sig in signals or []:
            dim_id = sig.get("dimension_id")
            if dim_id not in ALL_IDS:
                continue
            base = baselines.get(dim_id, 50.0)
            obs = gap.signal_to_observation(base, float(sig.get("signal") or 0.0))
            out.setdefault(dim_id, []).append(obs)
    return out


def recompute_dimension_scores(session: Session) -> dict[str, float]:
    """SJT ベースライン + 意思決定ログ観測を EWMA 合成し、現在地を upsert する。

    返り値: {dimension_id: current_estimate}。
    """
    settings = get_settings()
    baselines = latest_baselines(session)
    observations = _observations_by_dim(session, baselines)

    currents: dict[str, float] = {}
    now = datetime.utcnow()
    # ベースラインか観測がある次元のみ更新する。
    dim_ids = set(baselines) | set(observations)
    for dim_id in dim_ids:
        baseline = baselines.get(dim_id)
        obs = observations.get(dim_id, [])
        current = gap.blend_current(baseline, obs, span=settings.identity_ewma_span)
        if current is None:
            continue
        currents[dim_id] = current
        row = session.get(IdentityDimensionScore, dim_id)
        if row is None:
            row = IdentityDimensionScore(dimension_id=dim_id)
            session.add(row)
        row.sjt_baseline = baseline
        row.current_estimate = current
        row.components = {"baseline": baseline, "n_observations": len(obs)}
        row.updated_at = now
    return currents


def current_estimates(session: Session) -> dict[str, float | None]:
    """保存済みの次元別現在地 (なければ None)。"""
    out: dict[str, float | None] = {}
    for row in session.execute(select(IdentityDimensionScore)).scalars():
        out[row.dimension_id] = row.current_estimate
    return out


def build_gap_report(session: Session) -> dict:
    """理想プロファイル × 現在地のギャップ集計を返す (ダッシュボード用)。"""
    name, targets, weights = get_archetype(session)
    currents = current_estimates(session)
    report = gap.compute_gap_report(currents, targets, weights)
    report["archetype_name"] = name
    return report


def _imdb_url(item: MediaItem) -> str | None:
    """映画/ドラマの IMDb リンク (観た記録=評価のため)。本・マンガは IMDb 圏外で None。

    IMDb 由来は正確なタイトルページ、LLM 提案などはタイトル検索リンクにする。
    """
    if item.kind not in ("film", "tv"):
        return None
    if item.source == "imdb":
        meta = item.metadata_json or {}
        if meta.get("url"):
            return str(meta["url"])
        if item.ext_id:
            return f"https://www.imdb.com/title/{item.ext_id}/"
    # IMDb ID が無い (LLM 提案・手動) → タイトル検索リンク。
    return f"https://www.imdb.com/find/?q={quote(item.title)}&s=tt"


def recommend_media(session: Session, *, per_category: int = 12) -> list[dict]:
    """最弱ギャップ次元に効く作品を、category 別に上位 per_category 件ずつ推薦する。

    category:
      - "rewatch":   視聴済み (IMDb 評価あり)。診断の弱点 × 個人評価で「見返すべき」を出す。
      - "watchlist": リストにあるが未視聴 (これから観る)。
      - "new":       リスト外の LLM 提案 (source="llm_suggestion")。
    スコア = Σ(タグ確信度 × その次元のギャップ/100)。rewatch は個人評価で重み付け
    (高評価ほど見返す価値が高い)。グローバル上位 N だと多数派 (watchlist) が枠を独占し
    他カテゴリが埋もれるため、category 別に上位 per_category 件ずつ返す (全体はスコア降順)。
    """
    report = build_gap_report(session)
    gap_by_dim = {
        d["id"]: (d["gap"] or 0.0) / 100.0 for d in report["dimensions"] if d["gap"] is not None
    }
    # レバレッジ = 理想に近づく寄与なので、次元の重要度 (アーキタイプ重み) も掛ける。
    weight_by_dim = {d["id"]: float(d["weight"]) for d in report["dimensions"]}
    if not gap_by_dim:
        return []

    logs = {r.media_item_id: r for r in session.execute(select(MediaLog)).scalars()}

    scored: list[dict] = []
    for item in session.execute(select(MediaItem)).scalars():
        tags = item.dimension_tags or {}
        if not tags:
            continue
        # レバレッジ = Σ(タグ確信度 × 残ギャップ × 次元重み)。
        # 重く・現状が弱く・複数次元に効く作品ほど高い。
        best_dim, best_contrib, total = None, 0.0, 0.0
        for dim_id, conf in tags.items():
            g = gap_by_dim.get(dim_id, 0.0)
            contrib = float(conf) * g * weight_by_dim.get(dim_id, 1.0)
            total += contrib
            if contrib > best_contrib:
                best_contrib, best_dim = contrib, dim_id
        if total <= 0 or best_dim is None:
            continue

        log = logs.get(item.id)
        rating = log.rating if log else None
        if log and log.status == "seen":
            category = "rewatch"
            # IMDb 個人評価 (1-10) で重み: 10→×1.5, 5→×1.0, 低評価は控えめに。
            if rating is not None:
                total *= 0.5 + min(float(rating), 10.0) / 10.0
        elif log and log.status == "watchlist":
            category = "watchlist"
            total *= 1.1
        else:
            category = "new"

        dim = BY_ID.get(best_dim)
        scored.append(
            {
                "media_item_id": item.id,
                "title": item.title,
                "kind": item.kind,
                "year": item.year,
                "category": category,
                "rating": rating,
                "imdb_url": _imdb_url(item),
                "reason_dimension": best_dim,
                "reason": f"{dim.name_ja}の伸びしろに効く" if dim else "",
                "score": round(total, 4),
            }
        )

    scored.sort(key=lambda r: r["score"], reverse=True)

    # category 別に上位 per_category 件ずつ拾う (全体はスコア降順を維持)。
    caps: dict[str, int] = {"rewatch": 0, "watchlist": 0, "new": 0}
    out: list[dict] = []
    for r in scored:
        cat = r["category"]
        if caps.get(cat, per_category) >= per_category:
            continue
        out.append(r)
        caps[cat] = caps.get(cat, 0) + 1
    return out
