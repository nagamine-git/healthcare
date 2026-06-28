"""Book Tracker アプリの CSV を取り込む(蔵書 + 評価 + 読了履歴)。

蔵書は MediaItem(kind="book", source="book_tracker")として保存。用途は2つ:
1. レコメンドの重複回避(avoid_titles は全 MediaItem 名を見るので自動で効く)。
2. 読書傾向(taste)の把握 → リスト外提案を好みに寄せる。

**dimension_tags は付けない**。成長レバレッジのレコメンド枠を蔵書で汚さず、
ライブラリ/嗜好の参照に徹する設計(研究目的の本などを推薦に混ぜない)。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health import MediaItem, MediaLog

# readingStatus の表記ゆれ → 内部状態。finished/read 系=seen、reading 系、その他=watchlist。
_SEEN = {"finished", "read", "completed", "done", "complete"}
_READING = {"reading", "in_progress", "in progress", "started", "current", "started_reading"}


def _norm_status(raw: str | None) -> str:
    s = (raw or "").strip().lower().replace("-", "_")
    if s in _SEEN or "finish" in s or s == "read":
        return "seen"
    if s in _READING or "reading" in s or "progress" in s:
        return "reading"
    return "watchlist"


def _parse_int(v: Any) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _parse_float(v: Any) -> float | None:
    try:
        f = float(str(v).strip())
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_date(v: Any) -> date_type | None:
    s = (str(v) if v is not None else "").strip()
    if not s:
        return None
    # ISO 日付 or 日時の先頭10桁を採用。
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date_type.fromisoformat(s[:10])
        except ValueError:
            return None


@dataclass
class BookRow:
    title: str
    ext_id: str | None
    year: int | None
    rating: float | None
    status: str
    end_reading: date_type | None
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_book_tracker_csv(text: str) -> list[BookRow]:
    reader = csv.DictReader(io.StringIO(text))
    out: list[BookRow] = []
    for row in reader:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        ext = (
            (row.get("isbn13") or row.get("isbn10") or row.get("externalId") or row.get("id") or "")
            .strip()
            or None
        )
        meta = {
            "authors": (row.get("authors") or "").strip(),
            "categories": (row.get("categories") or "").strip(),
            "tags": (row.get("tags") or "").strip(),
            "series": (row.get("series") or "").strip(),
            "pages": _parse_int(row.get("pages")),
            "user_rating": _parse_float(row.get("userRating")),
            "avg_rating": _parse_float(row.get("externalAverageRating")),
            "reading_status": (row.get("readingStatus") or "").strip(),
            "start_reading": (row.get("startReading") or "").strip(),
            "end_reading": (row.get("endReading") or "").strip(),
        }
        meta = {k: v for k, v in meta.items() if v not in (None, "")}
        out.append(
            BookRow(
                title=title,
                ext_id=ext,
                year=_parse_int(row.get("releaseYear")) or _parse_int(row.get("originalReleaseYear")),
                rating=_parse_float(row.get("userRating")),
                status=_norm_status(row.get("readingStatus")),
                end_reading=_parse_date(row.get("endReading")),
                metadata=meta,
            )
        )
    return out


def import_books(session: Session, rows: list[BookRow]) -> dict[str, Any]:
    """蔵書を media_item / media_log に upsert。

    返り値: {items, seen, reading, watchlist, finish_dates}。finish_dates は読了日
    (読書アクションのバックフィル候補。確認後に別途記録)。
    """
    counts = {"items": 0, "seen": 0, "reading": 0, "watchlist": 0}
    finish_dates: set[date_type] = set()
    for it in rows:
        stmt = select(MediaItem).where(MediaItem.source == "book_tracker")
        stmt = (
            stmt.where(MediaItem.ext_id == it.ext_id)
            if it.ext_id
            else stmt.where(MediaItem.title == it.title)
        )
        media = session.execute(stmt).scalars().first()
        if media is None:
            media = MediaItem(
                source="book_tracker", ext_id=it.ext_id, kind="book",
                title=it.title, year=it.year, metadata_json=it.metadata,
            )
            session.add(media)
            session.flush()
        else:
            media.title = it.title or media.title
            media.year = it.year if it.year is not None else media.year
            media.metadata_json = it.metadata
        counts["items"] += 1

        log = session.get(MediaLog, media.id)
        if log is None:
            log = MediaLog(media_item_id=media.id, status=it.status)
            session.add(log)
            session.flush()  # autoflush=False のため、CSV内の重複本でも get で拾えるよう即 flush
        else:
            log.status = it.status
        if it.rating is not None:
            log.rating = it.rating
        if it.end_reading is not None:
            log.seen_at = datetime.combine(it.end_reading, datetime.min.time())
        counts[it.status] = counts.get(it.status, 0) + 1
        if it.status == "seen" and it.end_reading is not None:
            finish_dates.add(it.end_reading)
    return {**counts, "finish_dates": sorted(d.isoformat() for d in finish_dates)}
