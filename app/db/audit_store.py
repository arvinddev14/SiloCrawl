"""Read access to the deletion audit trail (:class:`DeletionLog`).

Writes happen inside the delete operations themselves (crawl_store /
telemetry_store) so a log entry and the erasure it records commit together.
This module only reads the trail back for compliance review.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import DeletionLog


async def list_deletions(limit: int = 200) -> list[dict[str, Any]]:
    """Most-recent erasures first. Metadata only — never deleted content."""
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(DeletionLog).order_by(DeletionLog.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    return [
        {
            "id": r.id,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "count": r.count,
            "actor": r.actor,
            "meta": r.meta,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
