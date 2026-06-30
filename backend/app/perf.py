"""常駐パフォーマンス監視: エラー / 低速レスポンス / 低速クエリを記録する。

ホットパスでは in-memory に集計のみ(DB 書込みなし)。perf_tick_job が定期的に
PerfIssue へ flush する。記録された問題は人(コーディングエージェント)が PR で直す。
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

SLOW_REQUEST_MS = 800.0
SLOW_QUERY_MS = 200.0
_MAX_ISSUES = 1000


@dataclass
class EndpointStat:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    slow: int = 0
    errors: int = 0
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=100))


class PerfRegistry:
    def __init__(self) -> None:
        self.endpoints: dict[str, EndpointStat] = {}
        self.issues: deque[dict[str, Any]] = deque(maxlen=_MAX_ISSUES)
        self._lock = Lock()

    def record_request(self, label: str, ms: float, status: int) -> None:
        with self._lock:
            st = self.endpoints.setdefault(label, EndpointStat())
            st.count += 1
            st.total_ms += ms
            st.max_ms = max(st.max_ms, ms)
            st.samples.append(ms)
            if status >= 500:
                st.errors += 1
                self.issues.append({"kind": "error", "label": label,
                                    "duration_ms": round(ms, 1), "detail": f"HTTP {status}"})
            if ms >= SLOW_REQUEST_MS:
                st.slow += 1
                self.issues.append({"kind": "slow_request", "label": label,
                                    "duration_ms": round(ms, 1), "detail": None})

    def record_query(self, statement: str, ms: float) -> None:
        if ms < SLOW_QUERY_MS:
            return
        norm = _normalize_sql(statement)
        with self._lock:
            self.issues.append({"kind": "slow_query", "label": norm,
                                "duration_ms": round(ms, 1), "detail": statement[:300]})

    def drain_issues(self) -> list[dict[str, Any]]:
        with self._lock:
            out = list(self.issues)
            self.issues.clear()
            return out

    def snapshot(self, top: int = 20) -> dict[str, Any]:
        with self._lock:
            rows = []
            for label, st in self.endpoints.items():
                s = sorted(st.samples)
                p95 = s[min(len(s) - 1, int(len(s) * 0.95))] if s else 0.0
                rows.append({
                    "label": label, "count": st.count,
                    "avg_ms": round(st.total_ms / st.count, 1) if st.count else 0.0,
                    "p95_ms": round(p95, 1), "max_ms": round(st.max_ms, 1),
                    "slow": st.slow, "errors": st.errors,
                })
        rows.sort(key=lambda r: r["p95_ms"], reverse=True)
        return {"endpoints": rows[:top],
                "thresholds": {"slow_request_ms": SLOW_REQUEST_MS, "slow_query_ms": SLOW_QUERY_MS}}


registry = PerfRegistry()

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\b\d+\b")
_INLIST = re.compile(r"IN\s*\([^)]*\)", re.IGNORECASE)


def _normalize_sql(sql: str) -> str:
    """パラメータ/数値/IN句を伏せて集約キーにする。"""
    s = _WS.sub(" ", sql.strip())
    s = _INLIST.sub("IN (?)", s)
    s = re.sub(r"'[^']*'", "?", s)
    s = _NUM.sub("?", s)
    return s[:255]


def attach_query_timing(engine: Any) -> None:
    """SQLAlchemy エンジンにクエリ計測リスナーを付ける(init_engine から呼ぶ)。"""
    from sqlalchemy import event

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info["_perf_start"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        start = conn.info.pop("_perf_start", None)
        if start is not None:
            registry.record_query(statement, (time.perf_counter() - start) * 1000.0)


async def perf_middleware(request: Any, call_next: Any) -> Any:
    """全リクエストの応答時間を計測し registry に記録する。"""
    start = time.perf_counter()
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        return resp
    finally:
        ms = (time.perf_counter() - start) * 1000.0
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        registry.record_request(f"{request.method} {path}", ms, status)


async def perf_tick_job() -> dict[str, Any]:
    """in-memory に溜まった問題を集約して PerfIssue へ flush する(スケジューラ起点)。"""
    from datetime import datetime

    from app.db import session_scope
    from app.models.health import PerfIssue

    issues = registry.drain_issues()
    if not issues:
        return {"flushed": 0}
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for it in issues:
        key = (it["kind"], it["label"][:255])
        a = agg.setdefault(key, {"count": 0, "max": 0.0, "detail": it.get("detail")})
        a["count"] += 1
        a["max"] = max(a["max"], it["duration_ms"])
        if it.get("detail"):
            a["detail"] = it["detail"]
    now = datetime.utcnow()
    with session_scope() as session:
        for (kind, label), a in agg.items():
            row = session.query(PerfIssue).filter_by(kind=kind, label=label).first()
            if row is None:
                row = PerfIssue(kind=kind, label=label, count=0, max_duration_ms=0.0, first_ts=now)
                session.add(row)
            row.count += a["count"]
            row.max_duration_ms = max(row.max_duration_ms, a["max"])
            row.detail = (a["detail"] or row.detail)
            row.last_ts = now
            row.resolved = False  # 再発したら未解決へ
    return {"flushed": len(issues), "aggregated": len(agg)}
