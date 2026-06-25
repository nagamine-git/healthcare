"""IMDb CSV パースと取り込み (状態の前進のみ) のテスト。"""

from __future__ import annotations

import tempfile

import pytest

from app.db import create_all, init_engine, session_scope
from app.ingest.imdb_import import import_media, parse_imdb_csv
from app.models.health import MediaItem, MediaLog

_RATINGS_CSV = (
    "Const,Your Rating,Date Rated,Title,Original Title,URL,Title Type,"
    "IMDb Rating,Runtime (mins),Year,Genres,Num Votes,Release Date,Directors\n"
    "tt0903747,9,2024-01-15,Breaking Bad,Breaking Bad,https://www.imdb.com/title/tt0903747/,"
    "tvSeries,9.5,49,2008,Crime,2000000,2008-01-20,Vince Gilligan\n"
    "tt1285016,8,2024-02-01,The Social Network,The Social Network,"
    "https://www.imdb.com/title/tt1285016/,movie,7.8,120,2010,Drama,800000,2010-10-01,David Fincher\n"
)

_WATCHLIST_CSV = (
    "Position,Const,Created,Modified,Description,Title,Original Title,URL,Title Type,"
    "IMDb Rating,Runtime (mins),Year,Genres,Num Votes,Release Date,Directors\n"
    "1,tt0848228,2024-03-01,2024-03-01,,The Avengers,The Avengers,"
    "https://www.imdb.com/title/tt0848228/,movie,8.0,143,2012,Action,1400000,2012-05-04,Joss Whedon\n"
    "2,tt1285016,2024-03-02,2024-03-02,,The Social Network,The Social Network,"
    "https://www.imdb.com/title/tt1285016/,movie,7.8,120,2010,Drama,800000,2010-10-01,David Fincher\n"
)


def test_parse_ratings_maps_kind_and_status() -> None:
    items = parse_imdb_csv(_RATINGS_CSV, list_kind="ratings")
    assert len(items) == 2
    bb = next(i for i in items if i.ext_id == "tt0903747")
    assert bb.kind == "tv"  # tvSeries → tv
    assert bb.status == "seen"
    assert bb.rating == 9.0
    assert bb.year == 2008
    sn = next(i for i in items if i.ext_id == "tt1285016")
    assert sn.kind == "film"  # movie → film


def test_parse_watchlist_status() -> None:
    items = parse_imdb_csv(_WATCHLIST_CSV, list_kind="watchlist")
    assert all(i.status == "watchlist" for i in items)
    assert {i.ext_id for i in items} == {"tt0848228", "tt1285016"}


def test_parse_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        parse_imdb_csv("", list_kind="bogus")


@pytest.fixture()
def _db():
    init_engine(tempfile.mktemp(suffix=".sqlite3"))
    create_all()
    yield


def test_import_is_idempotent_and_advances_status(_db) -> None:
    # まず watchlist を取り込む。
    with session_scope() as s:
        c1 = import_media(s, parse_imdb_csv(_WATCHLIST_CSV, list_kind="watchlist"))
    assert c1["items"] == 2

    with session_scope() as s:
        items = s.query(MediaItem).all()
        assert len(items) == 2  # 重複なし
        logs = {log.media_item_id: log for log in s.query(MediaLog).all()}
        assert all(log.status == "watchlist" for log in logs.values())

    # 次に ratings (= seen) を取り込む。重複作品 (tt1285016) は seen に前進する。
    with session_scope() as s:
        import_media(s, parse_imdb_csv(_RATINGS_CSV, list_kind="ratings"))

    with session_scope() as s:
        # tt0903747 (新規) + tt0848228 (watchlist のまま) + tt1285016 (seen 化) = 3 作品。
        items = {i.ext_id: i for i in s.query(MediaItem).all()}
        assert set(items) == {"tt0903747", "tt0848228", "tt1285016"}
        logs = {i.ext_id: s.get(MediaLog, i.id) for i in items.values()}
        assert logs["tt1285016"].status == "seen"  # watchlist → seen に前進
        assert logs["tt1285016"].rating == 8.0
        assert logs["tt0848228"].status == "watchlist"  # 触れていないものは据え置き


def test_seen_not_downgraded_by_watchlist(_db) -> None:
    with session_scope() as s:
        import_media(s, parse_imdb_csv(_RATINGS_CSV, list_kind="ratings"))
    # 同じ作品が後から watchlist に現れても seen を維持する。
    with session_scope() as s:
        import_media(s, parse_imdb_csv(_WATCHLIST_CSV, list_kind="watchlist"))
    with session_scope() as s:
        item = s.query(MediaItem).filter_by(ext_id="tt1285016").one()
        log = s.get(MediaLog, item.id)
        assert log.status == "seen"  # 逆戻りしない
