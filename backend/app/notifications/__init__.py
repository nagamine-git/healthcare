"""Web Push 通知サブシステム。

- ``engine``: 「今この瞬間に送るべき通知」を純粋ロジックで選定 (テスト容易)
- ``push``:   pywebpush による配信と購読 (PushSubscription) の管理
- ``service``: スケジューラ tick から呼ぶ統合エントリ (収集 → 重複排除 → 送信)
"""
