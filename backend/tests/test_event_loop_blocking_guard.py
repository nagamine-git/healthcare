"""`await` を持たない `async def` を禁じる静的ガード。

# なぜこのテストがあるか (2026-08-03 の実障害)

``sync_garmin_job`` が ``async def`` なのに中身は完全に同期 (Garmin への HTTPS +
大量の SQLite 書き込み) だった。APScheduler の ``AsyncIOScheduler`` はコルーチン
ジョブを**イベントループ上で**実行するため、毎時の同期のたびにサーバが数十秒
固まり、``/api/today`` を含む全リクエストが返らなくなっていた。さらにフロントは
「データが30分以上古ければ開いた瞬間に ``POST /admin/full-refresh``」を投げるので、
**アプリを開くたびに凍結**していた。

``await`` の無い ``async def`` は「非同期に見えて実際はイベントループを独占する」
という最悪の形で、見た目からは危険が分からない。だから機械的に禁じる。

正しい書き方:
- バックグラウンドジョブ → ``def`` + ``@app.jobs.blocking_job`` (別スレッドへ退避)
- FastAPI のルートハンドラ → ただの ``def`` (FastAPI がスレッドプールで実行する)
"""

from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

# 例外: 中身が同期でも問題にならないもの。
#   healthz  … 定数を返すだけ (DB も I/O も触らない)
#   lifespan … 起動/終了フック。ここは元々ブロッキングで正しい
_ALLOWED = {"healthz", "lifespan"}


def _has_blocking_job_decorator(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    for d in node.decorator_list:
        if isinstance(d, ast.Name) and d.id == "blocking_job":
            return True
        if isinstance(d, ast.Attribute) and d.attr == "blocking_job":
            return True
    return False


def test_no_async_def_without_await() -> None:
    """`await` を1つも持たない `async def` が新たに増えていないこと。"""
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if node.name in _ALLOWED or _has_blocking_job_decorator(node):
                continue
            has_await = any(
                isinstance(x, (ast.Await, ast.AsyncFor, ast.AsyncWith))
                for x in ast.walk(node)
            )
            if not has_await:
                rel = path.relative_to(APP.parent)
                offenders.append(f"{rel}:{node.lineno} async def {node.name}()")

    assert not offenders, (
        "await を持たない async def はイベントループを塞ぎます。\n"
        "同期処理なら `def` にしてください "
        "(ジョブは @blocking_job、FastAPI のハンドラは素の def でスレッドプール実行)。\n  "
        + "\n  ".join(offenders)
    )
