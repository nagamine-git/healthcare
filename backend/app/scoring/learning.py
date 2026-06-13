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

import itertools
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
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

# 節 (subsection) カリキュラム。The Book 日本語版の目次に対応。
# 章ごとの (節ID, タイトル) リスト。節の無い章は章番号だけの1項目。
SECTIONS: dict[int, list[tuple[str, str]]] = {
    1: [("1.1", "インストール"), ("1.2", "Hello, World!"), ("1.3", "Hello, Cargo!")],
    2: [("2", "数当てゲーム")],
    3: [("3.1", "変数と可変性"), ("3.2", "データ型"), ("3.3", "関数"),
        ("3.4", "コメント"), ("3.5", "制御フロー")],
    4: [("4.1", "所有権とは？"), ("4.2", "参照と借用"), ("4.3", "スライス型")],
    5: [("5.1", "構造体を定義・インスタンス化"), ("5.2", "構造体を使った例"), ("5.3", "メソッド記法")],
    6: [("6.1", "Enum を定義"), ("6.2", "match 制御フロー"), ("6.3", "if let")],
    7: [("7.1", "パッケージとクレート"), ("7.2", "モジュール定義"), ("7.3", "パス"),
        ("7.4", "use キーワード"), ("7.5", "複数ファイルに分割")],
    8: [("8.1", "ベクタ"), ("8.2", "文字列(UTF-8)"), ("8.3", "ハッシュマップ")],
    9: [("9.1", "panic! 回復不能エラー"), ("9.2", "Result 回復可能エラー"), ("9.3", "panic! すべきか")],
    10: [("10.1", "ジェネリックなデータ型"), ("10.2", "トレイト"), ("10.3", "ライフタイム")],
    11: [("11.1", "テストの記述法"), ("11.2", "実行制御"), ("11.3", "テストの体系化")],
    12: [("12.1", "コマンドライン引数"), ("12.2", "ファイル読み込み"), ("12.3", "リファクタリング"),
         ("12.4", "TDD でライブラリ開発"), ("12.5", "環境変数"), ("12.6", "標準エラー出力")],
    13: [("13.1", "クロージャ"), ("13.2", "イテレータ"), ("13.3", "プロジェクト改善"),
         ("13.4", "ループ VS イテレータ")],
    14: [("14.1", "リリースプロファイル"), ("14.2", "Crates.io に公開"), ("14.3", "ワークスペース"),
         ("14.4", "cargo install"), ("14.5", "独自コマンド")],
    15: [("15.1", "Box<T>"), ("15.2", "Deref トレイト"), ("15.3", "Drop トレイト"),
         ("15.4", "Rc<T> 参照カウント"), ("15.5", "RefCell<T> 内部可変性"), ("15.6", "循環参照")],
    16: [("16.1", "スレッド"), ("16.2", "メッセージ受け渡し"), ("16.3", "状態共有"),
         ("16.4", "Sync と Send")],
    17: [("17.1", "OO 言語の特徴"), ("17.2", "トレイトオブジェクト"), ("17.3", "OO デザインパターン")],
    18: [("18.1", "パターンが使える箇所"), ("18.2", "論駁可能性"), ("18.3", "パターン記法")],
    19: [("19.1", "Unsafe Rust"), ("19.2", "高度なトレイト"), ("19.3", "高度な型"),
         ("19.4", "高度な関数とクロージャ"), ("19.5", "マクロ")],
    20: [("20.1", "シングルスレッド Web サーバ"), ("20.2", "マルチスレッド化"), ("20.3", "正常なシャットダウン")],
    21: [("21.1", "付録A キーワード"), ("21.2", "付録B 演算子と記号"), ("21.3", "付録C 導出可能なトレイト"),
         ("21.4", "付録D 開発ツール"), ("21.5", "付録E エディション"), ("21.6", "付録F 翻訳"),
         ("21.7", "付録G Rust の作られ方")],
}
TOTAL_SECTIONS = sum(len(v) for v in SECTIONS.values())


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


def _section_rows() -> dict[str, datetime | None]:
    """節ID → done_at (None=未完了)。"""
    from app.models import LearningSectionProgress

    with session_scope() as session:
        rows = session.execute(select(LearningSectionProgress)).scalars().all()
        return {r.section_id: r.done_at for r in rows}


def set_section(section_id: str, done: bool, *, done_at_iso: str | None = None) -> dict[str, Any]:
    """節の読了をトグル。done_at_iso を指定すれば過去の学習も記録できる。"""
    from app.models import LearningSectionProgress

    valid = {sid for secs in SECTIONS.values() for sid, _ in secs}
    if section_id not in valid:
        raise ValueError(f"unknown section: {section_id}")
    ts = None
    if done:
        if done_at_iso:
            dt = datetime.fromisoformat(done_at_iso)
            ts = dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt
        else:
            ts = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as session:
        row = session.get(LearningSectionProgress, section_id)
        if row is None:
            row = LearningSectionProgress(section_id=section_id)
            session.add(row)
        row.done_at = ts
    return state()


def _plan_meta() -> tuple[date_type | None, date_type | None]:
    """(手動開始日, 目標完了日)。未設定は (None, None)。"""
    from app.models import LearningPlanMeta

    with session_scope() as session:
        m = session.get(LearningPlanMeta, 1)
        return (m.started_on, m.target_date) if m else (None, None)


def set_plan(*, started_on: str | None = None, target_date: str | None = None,
             clear_started: bool = False, clear_target: bool = False) -> dict[str, Any]:
    """学習開始日 / 目標完了日 を記録する。"""
    from app.models import LearningPlanMeta

    with session_scope() as session:
        m = session.get(LearningPlanMeta, 1)
        if m is None:
            m = LearningPlanMeta(id=1)
            session.add(m)
        if clear_started:
            m.started_on = None
        elif started_on:
            m.started_on = date_type.fromisoformat(started_on)
        if clear_target:
            m.target_date = None
        elif target_date:
            m.target_date = date_type.fromisoformat(target_date)
    return state()


def projection(rows: dict[int, LearningChapterProgress], today: date_type) -> dict[str, Any] | None:
    """チェック完了タイムスタンプから「いつ終わりそうか」を予測 + 累積グラフ用系列。

    単位はチェック (章×3 = 63)。完了日ごとの累積進捗 % を返し、現在ペースで
    100% に到達する予定日を線形外挿する。データが乏しいと confidence=low。
    手動の開始日/目標完了日があれば反映する。
    """
    # 進捗単位は「節」(細粒度)。節完了タイムスタンプ (時刻まで) から累積を作る
    total_units = TOTAL_SECTIONS
    manual_start, target_date = _plan_meta()
    done_ts: list[datetime] = sorted(ts for ts in _section_rows().values() if ts)
    if not done_ts and manual_start is None:
        return None
    started_on = manual_start or (done_ts[0].date() if done_ts else today)
    done_units = len(done_ts)

    # 累積系列 (日付 → その日までの累積 %)。開始点 0% を先頭に置く
    from collections import Counter
    by_day = Counter(ts.date() for ts in done_ts)
    series: list[dict[str, Any]] = [{"date": started_on.isoformat(), "pct": 0.0}]
    cum = 0
    for day in sorted(by_day):
        cum += by_day[day]
        series.append({"date": day.isoformat(), "pct": round(cum / total_units * 100, 1)})

    remaining = total_units - done_units
    elapsed_days = max(0.5, (today - started_on).days)

    def _eta(pace_per_day: float) -> str | None:
        if remaining <= 0:
            return today.isoformat()
        if pace_per_day <= 0:
            return None
        return (today + timedelta(days=round(remaining / pace_per_day))).isoformat()

    # N予想 (標準): 開始からの平均ペース
    pace_overall = done_units / elapsed_days
    eta_normal = _eta(pace_overall)
    # P予想 (楽観): 直近14日のペース (最近の勢い。早ければ前倒し予測)
    recent_cut = today - timedelta(days=14)
    recent_done = sum(1 for ts in done_ts if ts.date() > recent_cut)
    recent_days = min(14.0, elapsed_days)
    pace_recent = recent_done / recent_days if recent_days > 0 else 0.0
    # P は「最近ペース」と「全体ペース」の良い方 (楽観側)
    pace_opt = max(pace_recent, pace_overall)
    eta_optimistic = _eta(pace_opt)

    # 互換: 既存フィールド (N予想を主とする)
    eta_date = eta_normal
    eta_days = None
    if eta_normal:
        eta_days = (date_type.fromisoformat(eta_normal) - today).days

    if done_units < 1:
        confidence = "none"
    elif elapsed_days >= 21 and done_units >= 12:
        confidence = "high"
    elif elapsed_days >= 7 and done_units >= 5:
        confidence = "medium"
    else:
        confidence = "low"

    on_track: bool | None = None
    if target_date and eta_normal:
        on_track = date_type.fromisoformat(eta_normal) <= target_date

    return {
        "started_on": started_on.isoformat(),
        "done_units": done_units,
        "total_units": total_units,
        "pct": round(done_units / total_units * 100, 1),
        "pace_per_week": round(pace_overall * 7, 1),
        "pace_recent_per_week": round(pace_recent * 7, 1),
        "eta_date": eta_date,
        "eta_days": eta_days,
        "eta_normal": eta_normal,
        "eta_optimistic": eta_optimistic,
        "target_date": target_date.isoformat() if target_date else None,
        "on_track": on_track,
        "confidence": confidence,
        "series": series,
    }


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
    for prev, cur in itertools.pairwise(rows):
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
    sec_rows = _section_rows()

    chapters: list[dict[str, Any]] = []
    current: int | None = None
    done_count = 0
    section_done = 0
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
        # 節 (subsection)
        secs = []
        for sid, stitle in SECTIONS.get(c["chapter"], []):
            sdone = sec_rows.get(sid) is not None
            if sdone:
                section_done += 1
            secs.append({"id": sid, "title": stitle, "done": sdone})
        chapters.append(
            {
                **c,
                "read": bool(r and r.read_at),
                "rustlings": bool(r and r.rustlings_at),
                "explained": bool(r and r.explained_at),
                "complete": complete,
                "sections": secs,
                "section_done": sum(1 for s in secs if s["done"]),
                "section_total": len(secs),
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
        "section_done": section_done,
        "section_total": TOTAL_SECTIONS,
        "projection": projection(rows, d),
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
