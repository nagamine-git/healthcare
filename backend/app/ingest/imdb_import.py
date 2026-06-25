"""IMDb のエクスポート CSV (ratings.csv / watchlist.csv) を取り込む。

IMDb は個人リスト用の公式 API を提供しないため、ブラウザからエクスポートした CSV を
アップロードして取り込む (Apple Health がアプリから push、Garmin が pull なのと同じく、
ここは「ユーザーがエクスポートを渡す」取り込み経路)。

ratings.csv: 評価済み = 視聴済みとみなし status="seen" + 個人評価。
watchlist.csv: 未消化 = status="watchlist"。
既に seen の作品を watchlist で seen→watchlist に逆戻りさせない (状態は前進のみ)。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health import MediaItem, MediaLog

# IMDb の Title Type → 内部 kind (film | tv)。
_TV_TYPES = {"tvSeries", "tvMiniSeries", "tvEpisode", "tvSpecial"}


def _kind_from_title_type(title_type: str) -> str:
    return "tv" if (title_type or "").strip() in _TV_TYPES else "film"


def _parse_int(v: str | None) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _parse_float(v: str | None) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _parse_dt(v: str | None) -> datetime | None:
    s = (v or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%a %b %d %H:%M:%S %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


@dataclass
class NormalizedMedia:
    ext_id: str
    title: str
    kind: str
    year: int | None
    status: str  # seen | watchlist
    rating: float | None = None
    seen_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_imdb_csv(text: str, *, list_kind: str) -> list[NormalizedMedia]:
    """IMDb CSV テキストをパースする。

    list_kind: "ratings" (評価=視聴済み) か "watchlist" (未消化)。
    列名の表記揺れ (大小・スペース) に寛容にする。
    """
    if list_kind not in ("ratings", "watchlist"):
        raise ValueError(f"unknown list_kind: {list_kind}")

    reader = csv.DictReader(io.StringIO(text))
    out: list[NormalizedMedia] = []
    for raw in reader:
        row = {(k or "").strip(): v for k, v in raw.items()}
        const = (row.get("Const") or "").strip()
        title = (row.get("Title") or "").strip()
        if not const or not title:
            continue
        title_type = (row.get("Title Type") or "").strip()
        meta = {
            "title_type": title_type,
            "genres": (row.get("Genres") or "").strip(),
            "url": (row.get("URL") or "").strip(),
            "imdb_rating": _parse_float(row.get("IMDb Rating")),
            "runtime_min": _parse_int(row.get("Runtime (mins)")),
        }
        item = NormalizedMedia(
            ext_id=const,
            title=title,
            kind=_kind_from_title_type(title_type),
            year=_parse_int(row.get("Year")),
            status="seen" if list_kind == "ratings" else "watchlist",
            metadata=meta,
        )
        if list_kind == "ratings":
            item.rating = _parse_float(row.get("Your Rating"))
            item.seen_at = _parse_dt(row.get("Date Rated"))
        out.append(item)
    return out


def import_media(session: Session, items: list[NormalizedMedia]) -> dict[str, int]:
    """正規化済み作品を media_item / media_log に upsert する。

    返り値: {"items": 新規/更新した作品数, "seen": seen 件数, "watchlist": watchlist 件数}。
    """
    counts = {"items": 0, "seen": 0, "watchlist": 0}
    for it in items:
        media = session.execute(
            select(MediaItem).where(MediaItem.source == "imdb", MediaItem.ext_id == it.ext_id)
        ).scalar_one_or_none()
        if media is None:
            media = MediaItem(
                source="imdb",
                ext_id=it.ext_id,
                kind=it.kind,
                title=it.title,
                year=it.year,
                metadata_json=it.metadata,
            )
            session.add(media)
            session.flush()  # media.id を確定
        else:
            # メタdata は最新で更新するが、手動の dimension_tags は触らない。
            media.title = it.title or media.title
            media.year = it.year if it.year is not None else media.year
            media.metadata_json = it.metadata
        counts["items"] += 1

        log = session.get(MediaLog, media.id)
        if log is None:
            log = MediaLog(media_item_id=media.id, status=it.status)
            session.add(log)
        # 状態は前進のみ: 既に seen のものを watchlist に戻さない。
        if it.status == "seen":
            log.status = "seen"
            if it.rating is not None:
                log.rating = it.rating
            if it.seen_at is not None:
                log.seen_at = it.seen_at
        elif log.status != "seen":
            log.status = "watchlist"
        log.updated_at = datetime.utcnow()
        counts[it.status] += 1
    return counts
