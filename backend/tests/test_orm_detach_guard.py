"""ORM オブジェクトを session_scope の外へ持ち出していないかの横断チェック。

背景: `session_scope()` を抜けたインスタンスは detach され、未ロード属性に触れた瞬間
`DetachedInstanceError` で 500 になる。**テストが通っても本番で落ちる**タチの悪い壊れ方で、
実際に `/api/sleep/last-night` と `/api/body-measurement` の2箇所で踏んだ。
個別に直すだけでは3度目が起きるので、静的に検出する。

検出方法: `with session_scope() as X:` ブロックの**中で** `return` している関数のうち、
返している式が ORM クエリの結果そのもの (`.scalars().first()` / `.scalars().all()` /
`session.get(...)`) になっているものを弾く。素の dict/list に詰め替えていれば安全。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"

# 返り値が ORM インスタンスでも安全な例 (呼び出し側が同じセッション内で使い切る等)。
# 追加する場合は**なぜ安全か**を必ずコメントで書くこと。
_ALLOWLIST: set[str] = set()


def _returns_orm_inside_session(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """with session_scope() の中で ORM クエリ結果をそのまま return しているか。"""
    for node in ast.walk(func):
        if not isinstance(node, ast.With | ast.AsyncWith):
            continue
        if not any(
            isinstance(it.context_expr, ast.Call)
            and getattr(it.context_expr.func, "id", None) == "session_scope"
            for it in node.items
        ):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Return) or inner.value is None:
                continue
            v = inner.value
            if not isinstance(v, ast.Call):
                continue
            attr = getattr(v.func, "attr", None)
            # `session.get(Model, pk)` は ORM インスタンスを返す
            if attr == "get" and getattr(v.func.value, "id", "") == "session":
                return True
            # `.first()/.all()/...` は **`.scalars()` を経由している時だけ** ORM
            # インスタンス。`select(Model.col, ...)` のような列指定は素のタプルを
            # 返すので detach の問題は起きない (例: api/timeline.py::_gather)。
            if attr in {"first", "all", "one", "one_or_none"}:
                if any(
                    isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "scalars"
                    for n in ast.walk(v)
                ):
                    return True
    return False


def _iter_functions():
    for path in sorted(_APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                yield path, node


@pytest.mark.parametrize(
    "path,func",
    [(p, f) for p, f in _iter_functions() if _returns_orm_inside_session(f)],
    ids=lambda x: getattr(x, "name", str(x)),
)
def test_no_orm_instance_escapes_session(path, func):
    key = f"{path.relative_to(_APP)}::{func.name}"
    assert key in _ALLOWLIST, (
        f"{key} が session_scope の中から ORM クエリ結果をそのまま return している。"
        " セッションを抜けると detach され、属性アクセスで DetachedInstanceError (500) になる。"
        " 必要な値を素の dict/list に詰め替えてから返すこと。"
    )
