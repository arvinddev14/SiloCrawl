"""Raw telemetry access for data-subject rights (export + purge).

Aggregated views live in :mod:`app.db.metrics` / evaluator; these functions
expose the raw ``telemetry_events`` rows so an operator can honour access
(export as JSON) and erasure (purge by time window) requests, as promised by
the privacy policy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from app.db.base import session_scope
from app.db.models import DeletionLog, TelemetryEvent


async def export_events(hours: int = 0, limit: int = 5000) -> list[dict[str, Any]]:
    """Raw telemetry events as JSON-serializable dicts. ``hours=0`` = all time."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours) if hours > 0 else None
    async with session_scope() as session:
        q = select(TelemetryEvent).order_by(TelemetryEvent.created_at.desc()).limit(limit)
        if since is not None:
            q = q.where(TelemetryEvent.created_at >= since)
        rows = (await session.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "run_id": r.run_id,
            "kind": r.kind,
            "message": r.message,
            "meta": r.meta,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def purge_events(older_than_hours: int | None = None, actor: str | None = None) -> int:
    """Delete telemetry events. ``older_than_hours=None`` (or <=0) deletes all;
    otherwise only events older than that window. Returns the number removed.

    A non-empty purge writes its audit-log entry in the same transaction."""
    async with session_scope() as session:
        stmt = delete(TelemetryEvent)
        if older_than_hours is not None and older_than_hours > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
            stmt = stmt.where(TelemetryEvent.created_at < cutoff)
        result = await session.execute(stmt)
        removed = result.rowcount or 0
        if removed:
            session.add(
                DeletionLog(
                    target_type="telemetry",
                    count=removed,
                    actor=actor,
                    meta={"older_than_hours": older_than_hours},
                )
            )
    return removed
