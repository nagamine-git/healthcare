"""The Rust Book 完走プランのカリキュラム定義と進捗計算。

完走プランの設計思想:
- 章のクリア条件は 3 点セット (読了 / Rustlings / 口頭説明)。
  「わかったふり」を構造的に防ぐのが目的なので、読了だけでは完了にならない。
- ペースは 1 章/週 が基準 (約 5 ヶ月で完走)。山場の章 (4, 10, 13, 15) は
  2 週かけてよい設計なので、遅れ判定は緩めにしている。
- 日次の学習活動は ExternalDomainEntry(domain="learning") に書き、
  ライフスコア・LLM コーチングへはそこから流れる (既存経路を再利用)。
"""

from __future__ import annotations

from datetime import UTC, date as date_type, datetime, timedelta
from typing import Any, TypedDict

from sqlalchemy import select

from app.db import session_scope
from app.models import ExternalDomainEntry, LearningChapterProgress
from app.scoring.timewindow import app_today

DOMAIN_KEY = "learning"

# クリア条件の 3 点セット。順序は UI 表示順。
CHECK_FIELDS = ("read", "rustlings", "explained")
_FIELD_COLUMNS = {"read": "read_at", "rustlings": "rustlings_at", "explained": "explained_at"}
_FIELD_LABELS = {"read": "読了", "rustlings": "Rustlings", "explained": "説明できた"}


class Chapter(TypedDict):
    chapter: int
    title: str
    note: str | None
    milestone: bool


# The Rust Programming Language (2024 edition / 日本語版) 全 21 章。
# milestone=True は挫折リスクの高い山場 or 卒業制作。note は事前警告。
CURRICULUM: list[Chapter] = [
    {"chapter": 1, "title": "事始め", "note": None, "milestone": False},
    {"chapter": 2, "title": "数当てゲーム", "note": None, "milestone": False},
    {"chapter": 3, "title": "一般的なプログラミング概念", "note": None, "milestone": False},
    {
        "chapter": 4,
        "title": "所有権を理解する",
        "note": "最初の山。2週かけてよい。Rust の判断力の核",
        "milestone": True,
    },
    {"chapter": 5, "title": "構造体", "note": None, "milestone": False},
    {"chapter": 6, "title": "Enum とパターンマッチング", "note": None, "milestone": False},
    {"chapter": 7, "title": "パッケージ・クレート・モジュール", "note": None, "milestone": False},
    {"chapter": 8, "title": "一般的なコレクション", "note": None, "milestone": False},
    {"chapter": 9, "title": "エラー処理", "note": None, "milestone": False},
    {
        "chapter": 10,
        "title": "ジェネリクス・トレイト・ライフタイム",
        "note": "第二の山。2週かけてよい",
        "milestone": True,
    },
    {"chapter": 11, "title": "自動テスト", "note": None, "milestone": False},
    {
        "chapter": 12,
        "title": "CLI プロジェクト (minigrep)",
        "note": "中間卒業制作。完成したら祝う",
        "milestone": True,
    },
    {
        "chapter": 13,
        "title": "イテレータとクロージャ",
        "note": "完走プランの最多脱落地点。進みが遅くても続いていれば OK",
        "milestone": True,
    },
    {"chapter": 14, "title": "Cargo と Crates.io", "note": None, "milestone": False},
    {
        "chapter": 15,
        "title": "スマートポインタ",
        "note": "最難関。Rc/RefCell は speech-coach の実コードと突き合わせる",
        "milestone": True,
    },
    {"chapter": 16, "title": "恐れるな並行性", "note": None, "milestone": False},
    {"chapter": 17, "title": "非同期プログラミング", "note": None, "milestone": False},
    {"chapter": 18, "title": "オブジェクト指向の考え方", "note": None, "milestone": False},
    {"chapter": 19, "title": "パターンとマッチング", "note": None, "milestone": False},
    {"chapter": 20, "title": "高度な機能", "note": None, "milestone": False},
    {
        "chapter": 21,
        "title": "最終プロジェクト: Web サーバ",
        "note": "卒業制作。写経ではなく自分の指で",
        "milestone": True,
    },
]

TOTAL_CHAPTERS = len(CURRICULUM)


def _progress_rows() -> dict[int, LearningChapterProgress]:
    with session_scope() as session:
        rows = session.execute(select(LearningChapterProgress)).scalars().all()
        # session 外で使うため必要属性だけ展開した軽量オブジェクトにしない —
        # expire_on_commit 無効化に依存せず、ここで dict 化する
        return {
            r.chapter: LearningChapterProgress(
                chapter=r.chapter,
                read_at=r.read_at,
                rustlings_at=r.rustlings_at,
                explained_at=r.explained_at,
            )
            for r in rows
        }


def _is_complete(row: LearningChapterProgress | None) -> bool:
    return bool(row and row.read_at and row.rustlings_at and row.explained_at)


def _streak_days(today: date_type) -> int:
    """学習エントリ (achievement>0) の連続日数。今日が未活動でも昨日から数える。

    週 1-2 回ペースの学習で日単位ストリークは即切れて意欲を削ぐので、
    「7 日以内に活動があれば継続」とみなす猶予付きストリーク (連続週数換算ではなく
    最終活動からの経過で途切れ判定) にしている。
    """
    with session_scope() as session:
        rows = session.execute(
            select(ExternalDomainEntry.date)
            .where(
                ExternalDomainEntry.domain == DOMAIN_KEY,
                ExternalDomainEntry.achievement > 0,
            )
            .order_by(ExternalDomainEntry.date.desc())
        ).scalars().all()
    if not rows:
        return 0
    # 最終活動から 7 日超空いたらストリーク 0
    if (today - rows[0]).days > 7:
        return 0
    # 7 日以内の間隔で繋がっている活動日数を数える
    streak = 1
    for prev, cur in zip(rows, rows[1:]):
        if (prev - cur).days <= 7:
            streak += 1
        else:
            break
    return streak


def upsert_today_entry(detail: str, *, today: date_type | None = None) -> None:
    """今日の学習活動を ExternalDomainEntry に記録する (achievement=100)。

    1 日 1 行。複数アクションがあった日は detail を上書き更新する
    (最後のアクションが最も情報量が多い前提)。
    """
    d = today or app_today()
    with session_scope() as session:
        row = session.get(ExternalDomainEntry, (DOMAIN_KEY, d))
        if row is None:
            row = ExternalDomainEntry(domain=DOMAIN_KEY, date=d)
            session.add(row)
        row.achievement = 100.0
        row.detail = detail[:200]


def set_check(chapter: int, field: str, done: bool) -> dict[str, Any]:
    """章のクリア条件 1 つを記録/取消し、今日の学習エントリを更新する。"""
    if field not in _FIELD_COLUMNS:
        raise ValueError(f"unknown field: {field}")
    if not any(c["chapter"] == chapter for c in CURRICULUM):
        raise ValueError(f"unknown chapter: {chapter}")

    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as session:
        row = session.get(LearningChapterProgress, chapter)
        if row is None:
            row = LearningChapterProgress(chapter=chapter)
            session.add(row)
        setattr(row, _FIELD_COLUMNS[field], now if done else None)

    if done:
        title = next(c["title"] for c in CURRICULUM if c["chapter"] == chapter)
        today = app_today()
        # 今日タイムスタンプが付いた条件を列挙して detail を組み立てる
        rows = _progress_rows()
        r = rows.get(chapter)
        done_today = [
            _FIELD_LABELS[f]
            for f in CHECK_FIELDS
            if r and (ts := getattr(r, _FIELD_COLUMNS[f])) and ts.date() == today
        ]
        upsert_today_entry(f"The Book ch{chapter} {title}: {'+'.join(done_today) or _FIELD_LABELS[field]}")
    return state()


def record_activity(detail: str | None = None) -> dict[str, Any]:
    """章チェック以外の学習活動 (journey リポジトリへの commit 等) を記録する。"""
    upsert_today_entry(detail or "学習活動")
    return {"status": "ok"}


def state(*, today: date_type | None = None) -> dict[str, Any]:
    """カリキュラム全体の進捗状態。フロントと LLM の両方がこれを読む。"""
    d = today or app_today()
    rows = _progress_rows()

    chapters: list[dict[str, Any]] = []
    current: int | None = None
    done_count = 0
    first_ts: datetime | None = None
    for c in CURRICULUM:
        r = rows.get(c["chapter"])
        complete = _is_complete(r)
        if complete:
            done_count += 1
        elif current is None:
            current = c["chapter"]
        for f in CHECK_FIELDS:
            ts = getattr(r, _FIELD_COLUMNS[f]) if r else None
            if ts and (first_ts is None or ts < first_ts):
                first_ts = ts
        chapters.append(
            {
                **c,
                "read": bool(r and r.read_at),
                "rustlings": bool(r and r.rustlings_at),
                "explained": bool(r and r.explained_at),
                "complete": complete,
            }
        )

    started_on = first_ts.date() if first_ts else None
    weeks_elapsed = max(0, (d - started_on).days // 7) if started_on else 0
    # 1 章/週基準。山場 4 章ぶんのバッファを引いて遅れ判定 (緩め)
    expected = max(0, weeks_elapsed - 4)
    pace = "not_started" if started_on is None else (
        "behind" if done_count < expected else ("ahead" if done_count > weeks_elapsed else "on_track")
    )

    with session_scope() as session:
        today_row = session.get(ExternalDomainEntry, (DOMAIN_KEY, d))
        today_entry = (
            {"achievement": today_row.achievement, "detail": today_row.detail}
            if today_row
            else None
        )
        last_row = session.execute(
            select(ExternalDomainEntry)
            .where(ExternalDomainEntry.domain == DOMAIN_KEY, ExternalDomainEntry.achievement > 0)
            .order_by(ExternalDomainEntry.date.desc())
        ).scalars().first()
        last_activity = last_row.date.isoformat() if last_row else None

    return {
        "chapters": chapters,
        "current_chapter": current,  # 全章完了なら None
        "done_count": done_count,
        "total": TOTAL_CHAPTERS,
        "started_on": started_on.isoformat() if started_on else None,
        "weeks_elapsed": weeks_elapsed,
        "pace": pace,
        "streak_sessions": _streak_days(d),
        "last_activity": last_activity,
        "today": today_entry,
        "completed": done_count >= TOTAL_CHAPTERS,
    }


def llm_summary(*, today: date_type | None = None) -> dict[str, Any]:
    """LLM 朝コーチング用の要約。トークンを食わないよう現在章周辺だけ。"""
    s = state(today=today)
    cur = s["current_chapter"]
    cur_info = next((c for c in s["chapters"] if c["chapter"] == cur), None) if cur else None
    days_since = None
    if s["last_activity"]:
        days_since = ((today or app_today()) - date_type.fromisoformat(s["last_activity"])).days
    return {
        "plan": "The Rust Book 完走 (週1章ペース・約5ヶ月)",
        "progress": f"{s['done_count']}/{s['total']} 章完了",
        "pace": s["pace"],
        "current_chapter": (
            {
                "chapter": cur_info["chapter"],
                "title": cur_info["title"],
                "note": cur_info["note"],
                "milestone": cur_info["milestone"],
                "checks": {f: cur_info[f] for f in CHECK_FIELDS},
            }
            if cur_info
            else None
        ),
        "days_since_last_activity": days_since,
        "streak_sessions": s["streak_sessions"],
        "today_done": s["today"] is not None,
    }
