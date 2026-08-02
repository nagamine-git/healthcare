"""バックグラウンドジョブを「イベントループを塞がない」形で定義するための道具。

# なぜ必要か (2026-08-03 に実害として判明)

APScheduler の ``AsyncIOScheduler`` は、**コルーチン関数のジョブをイベントループ上で
そのまま実行する**。ジョブの中身が同期 I/O (Garmin Connect への HTTPS ログイン+多数の
API 呼び出し、SQLite への大量書き込み、LLM 呼び出し) だと、その処理が終わるまで
**サーバは他のリクエストを一切返せない**。

実際に起きていたこと::

    async def sync_garmin_job(...):
        client = GarminClient.from_settings(settings)
        return sync_garmin(client, target)   # ← 同期関数。await もスレッド退避も無い

``sync_garmin_job`` は毎時の cron ジョブであると同時に、``POST /admin/full-refresh``
からも呼ばれる。そしてフロントの Today 画面は「データが30分以上古ければ開いた瞬間に
full-refresh を投げる」ので、**アプリを開くたびに Garmin 同期が走り、その間ずっと
``/api/today`` を含む全リクエストが固まり、画面はスケルトンのまま**になっていた。

ローカルで再現しなかったのは Garmin の認証情報が無く同期が即 skip されていたため。

# 使い方

同期処理のジョブは ``def`` で書いて ``@blocking_job`` を付ける。呼び出し側から見ると
従来どおり ``await xxx_job()`` できる (デコレータが async ラッパを返す) ので、
既存の呼び出しは変えなくてよい。

⚠️ ジョブは**別スレッド**で走るようになる。DB は WAL + ``busy_timeout`` 設定済みなので
リクエスト処理と並行して読み書きできる (``app/db.py`` 参照)。
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any


def blocking_job[T](fn: Callable[..., T]) -> Callable[..., Any]:
    """同期処理のジョブを、別スレッドで走る async ジョブに変換する。

    ``await`` を持たない ``async def`` としてジョブを書いてはいけない。それは
    「非同期に見えて実際はイベントループを独占する」最悪の形になる (モジュール
    docstring 参照)。同期処理は ``def`` + このデコレータで明示的にスレッドへ逃がす。
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        import anyio.to_thread

        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))

    return wrapper
