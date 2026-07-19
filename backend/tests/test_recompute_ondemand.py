from __future__ import annotations


def test_ensure_today_fresh_throttles(db_engine):
    from app.scoring.recompute import _last_ondemand, ensure_today_fresh

    _last_ondemand.clear()
    # 初回は再計算する
    assert ensure_today_fresh() is True
    # 直後 (interval 内) は省略される
    assert ensure_today_fresh() is False
    # interval=0 なら強制的に再計算 (取り込み直後の反映用)
    assert ensure_today_fresh(min_interval_s=0) is True
