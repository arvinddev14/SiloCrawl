"""Benchmark Loop: persist per-run metric scores and aggregate trends.

One ``benchmarks`` row per metric per run, keyed by the telemetry run id, so a
score can always be traced back to the exact run (and its meta) that produced
it. ``summary`` powers ``GET /v1/benchmarks`` and the dashboard (INC-B13).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.db.base import session_scope
from app.db.models import Benchmark


async def record(
    run_id: str | None,
    metrics: dict[str, float],
    meta: dict[str, Any] | None = None,
) -> None:
    """Write one row per metric, all tied to the same run."""
    async with session_scope() as session:
        for metric, value in metrics.items():
            session.add(
                Benchmark(metric=metric, value=float(value), run_id=run_id, meta=meta)
            )


async def summary(hours: int = 24, recent_limit: int = 50) -> dict[str, Any]:
    """Per-metric avg/min/max/count over a window (``hours=0`` = all time)."""
    async with session_scope() as session:
        query = (
            select(
                Benchmark.metric,
                func.avg(Benchmark.value),
                func.min(Benchmark.value),
                func.max(Benchmark.value),
                func.count(),
            )
            .group_by(Benchmark.metric)
            .order_by(Benchmark.metric)
        )
        if hours:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            query = query.where(Benchmark.created_at >= since)
        rows = (await session.execute(query)).all()

        recent = (
            (
                await session.execute(
                    select(Benchmark).order_by(Benchmark.id.desc()).limit(recent_limit)
                )
            )
            .scalars()
            .all()
        )

    return {
        "window_hours": hours,
        "metrics": [
            {
                "metric": metric,
                "avg": round(avg, 4),
                "min": low,
                "max": high,
                "count": count,
            }
            for metric, avg, low, high, count in rows
        ],
        "recent": [
            {
                "metric": r.metric,
                "value": r.value,
                "run_id": r.run_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent
        ],
    }
