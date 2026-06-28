from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import session_scope
from app.ingest.book_tracker_import import import_books, parse_book_tracker_csv
from app.models.health import GoodActionLog
from app.scoring.identity import store


@pytest.fixture
def app_client_books(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client

HEADER = (
    "createdAt,updatedAt,id,externalId,source,title,subtitle,externalLink,state,types,"
    "isbn10,isbn13,releaseDate,originalReleaseDate,releaseYear,originalReleaseYear,"
    "placeOfPublication,description,remoteImageUrl,thumbnailRemoteImageUrl,"
    "externalAverageRating,userRating,pages,audiobookDuration,languages,purchaseDate,"
    "purchasePrice,purchaseCurrency,series,seriesNumber,location,bookcase,shelf,"
    "authors,narrators,illustrators,translators,publishers,categories,tags,"
    "readingStatus,startReading,endReading"
)


def _row(title, *, isbn13="", year="", rating="", status="", end="", authors="", categories=""):
    cols = {
        "title": title, "isbn13": isbn13, "releaseYear": year, "userRating": rating,
        "readingStatus": status, "endReading": end, "authors": authors, "categories": categories,
    }
    order = HEADER.split(",")
    return ",".join(str(cols.get(c, "")) for c in order)


def test_parse_maps_status_and_fields():
    csv = "\n".join([
        HEADER,
        _row("我が闘争", isbn13="9784003342916", year="1925", status="finished",
             end="2026-05-10", authors="Adolf Hitler", categories="History"),
        _row("読みたい本", status="toRead"),
        _row("読書中の本", status="reading", authors="Foo"),
    ])
    rows = parse_book_tracker_csv(csv)
    assert len(rows) == 3
    by_title = {r.title: r for r in rows}
    assert by_title["我が闘争"].status == "seen"
    assert by_title["我が闘争"].end_reading is not None
    assert by_title["読みたい本"].status == "watchlist"
    assert by_title["読書中の本"].status == "reading"


def test_import_and_taste(db_engine):
    csv = "\n".join([
        HEADER,
        _row("Zero to One", isbn13="9780753555200", year="2014", rating="5", status="finished",
             end="2026-05-10", authors="Peter Thiel", categories="Business"),
        _row("Sapiens", isbn13="9780099590088", year="2011", rating="4", status="finished",
             end="2026-05-10", authors="Yuval Harari", categories="History"),
        _row("積読本", status="toRead", authors="Someone"),
    ])
    rows = parse_book_tracker_csv(csv)
    with session_scope() as session:
        counts = import_books(session, rows)
        assert counts["items"] == 3
        assert counts["seen"] == 2 and counts["watchlist"] == 1
        # 2冊とも同じ日に読了 → finish_dates は1日
        assert counts["finish_dates"] == ["2026-05-10"]

        taste = store.book_taste(session)
        assert taste["total"] == 3 and taste["seen"] == 2
        assert taste["avg_rating"] == 4.5
        authors = {a["name"] for a in taste["top_authors"]}
        assert {"Peter Thiel", "Yuval Harari"} <= authors
        assert store.book_taste_hint(session) is not None

    # 再インポートは upsert(重複しない)
    with session_scope() as session:
        counts2 = import_books(session, parse_book_tracker_csv(csv))
        assert counts2["items"] == 3
        assert store.book_taste(session)["total"] == 3


def test_import_handles_duplicate_rows(db_engine):
    # 同一ISBNが複数行(再読・重複エクスポート)あっても MediaLog 二重insertで落ちない
    csv = "\n".join([
        HEADER,
        _row("Same Book", isbn13="9781111111111", rating="4", status="finished", end="2026-05-01"),
        _row("Same Book", isbn13="9781111111111", rating="5", status="finished", end="2026-05-09"),
    ])
    with session_scope() as session:
        counts = import_books(session, parse_book_tracker_csv(csv))
        assert counts["items"] == 2  # 行は2回処理されるが…
    with session_scope() as session:
        # MediaItem / MediaLog は1件に集約され、最新の評価で更新されている
        from app.models.health import MediaItem, MediaLog

        items = session.query(MediaItem).filter_by(source="book_tracker").all()
        assert len(items) == 1
        log = session.get(MediaLog, items[0].id)
        assert log.rating == 5


def test_books_import_endpoint_returns_taste_and_finish_dates(app_client_books):
    csv = "\n".join([
        HEADER,
        _row("Zero to One", isbn13="9780753555200", year="2014", rating="5",
             status="finished", end="2026-05-10", authors="Peter Thiel", categories="Business"),
        _row("積読本", status="toRead", authors="Someone"),
    ])
    r = app_client_books.post("/api/identity/books/import", json={"csv": csv})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == 2 and body["seen"] == 1
    assert body["finish_dates"] == ["2026-05-10"]  # 文字列→date 変換が壊れていない
    assert body["book_taste"]["total"] == 2


def test_reconcile_marks_crosslanguage_read_recs_seen(app_client_books, monkeypatch):
    import app.api.identity as iapi
    from app.db import session_scope
    from app.models.health import MediaItem, MediaLog

    # 既読の和書(蔵書)
    csv = "\n".join([
        HEADER,
        _row("リーン・スタートアップ", isbn13="9784822248970", status="finished",
             end="2026-05-10", authors="エリック・リース"),
    ])
    app_client_books.post("/api/identity/books/import", json={"csv": csv})

    # 英語タイトルの seed おすすめ(別 source・未 seen)
    with session_scope() as session:
        seed = MediaItem(source="manual", kind="book", title="The Lean Startup", year=2011,
                         dimension_tags={"growth_mindset": 1.0})
        session.add(seed)
        session.flush()
        session.add(MediaLog(media_item_id=seed.id, status="watchlist"))
        seed_id = seed.id

    async def fake_match(candidates, read_books):
        # 言語横断で The Lean Startup を既読と判定
        return [c["id"] for c in candidates if "Lean Startup" in c["title"]]

    monkeypatch.setattr(iapi.llm_identity, "match_read_titles", fake_match)

    r = app_client_books.post("/api/identity/books/reconcile")
    assert r.json()["matched"] == 1
    with session_scope() as session:
        assert session.get(MediaLog, seed_id).status == "seen"


def test_tag_untagged_count_excludes_book_tracker(app_client_books):
    csv = "\n".join([HEADER, _row("和書A", isbn13="9784000000001", status="finished", end="2026-05-10")])
    app_client_books.post("/api/identity/books/import", json={"csv": csv})
    # GET /api/identity の library.untagged は book_tracker を数えない
    lib = app_client_books.get("/api/identity").json()["library"]
    assert lib["untagged"] == 0


def test_books_backfill_reading_idempotent(app_client_books):
    r1 = app_client_books.post(
        "/api/identity/books/backfill-reading", json={"dates": ["2026-05-10", "2026-05-11"]}
    )
    assert sorted(r1.json()["logged"]) == ["2026-05-10", "2026-05-11"]
    # 再実行で増えない
    r2 = app_client_books.post(
        "/api/identity/books/backfill-reading", json={"dates": ["2026-05-10"]}
    )
    assert r2.json()["logged"] == []

    with session_scope() as session:
        reads = session.query(GoodActionLog).filter_by(kind="reading", source="book_tracker").all()
        assert len(reads) == 2
