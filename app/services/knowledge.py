"""Knowledge Loop: durable graph memory of what crawling has learned.

A deliberately small graph in SQLite (tables scaffolded at INC-3):

* ``domain`` entity — one per site, rolling ``last_activity``
* ``page`` entity — one per extracted URL: fields seen, confidence, counts
* ``record`` entity — the extracted data itself, labelled by its first string
* relations — ``page -part_of-> domain``, ``record -extracted_from-> page``

Entities are upserted by ``(entity_type, name, domain)`` so re-extraction
updates knowledge instead of duplicating it. Capture is best-effort and only
happens on the SiloLoop path — the orchestrator calls :func:`record_extraction`
after a successful run (and skips it when verification said ``fail``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import DomainStrategy, KnowledgeEntity, KnowledgeRelation

logger = logging.getLogger("silocrawl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def get_or_create_entity(
    session: AsyncSession,
    entity_type: str,
    name: str,
    domain: str | None = None,
    data: dict[str, Any] | None = None,
) -> KnowledgeEntity:
    """Idempotent upsert by (entity_type, name, domain); ``data`` is merged."""
    row = (
        await session.execute(
            select(KnowledgeEntity).where(
                KnowledgeEntity.entity_type == entity_type,
                KnowledgeEntity.name == name,
                KnowledgeEntity.domain == domain,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = KnowledgeEntity(
            entity_type=entity_type, name=name, domain=domain, data=data or {}
        )
        session.add(row)
        await session.flush()  # assign the id so relations can point at it
    elif data:
        row.data = {**(row.data or {}), **data}
    return row


async def add_relation(
    session: AsyncSession, subject_id: int, predicate: str, object_id: int
) -> None:
    """Insert a relation unless the exact triple already exists."""
    exists = (
        await session.execute(
            select(KnowledgeRelation.id).where(
                KnowledgeRelation.subject_id == subject_id,
                KnowledgeRelation.predicate == predicate,
                KnowledgeRelation.object_id == object_id,
            )
        )
    ).first()
    if exists is None:
        session.add(
            KnowledgeRelation(
                subject_id=subject_id, predicate=predicate, object_id=object_id
            )
        )


def _record_label(data: dict[str, Any]) -> str | None:
    """Best human label for a record: its first non-empty string value."""
    for value in data.values():
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return None


async def record_extraction(
    source_url: str | None, data: dict[str, Any], confidence: float | None = None
) -> None:
    """Fold one successful extraction into the graph (domain + page + record)."""
    if not source_url or not data:
        return
    domain = urlparse(source_url).netloc.lower()
    if not domain:
        return
    now = _now_iso()
    async with session_scope() as session:
        dom = await get_or_create_entity(session, "domain", domain, domain=domain)
        dom.data = {**(dom.data or {}), "last_activity": now}

        page = await get_or_create_entity(session, "page", source_url, domain=domain)
        prev = page.data or {}
        page.data = {
            "fields": sorted(data.keys()),
            "last_confidence": confidence,
            "extractions": prev.get("extractions", 0) + 1,
            "last_extracted": now,
        }

        label = _record_label(data) or source_url
        record = await get_or_create_entity(session, "record", label, domain=domain)
        record.data = {"values": data, "last_extracted": now}

        await add_relation(session, page.id, "part_of", dom.id)
        await add_relation(session, record.id, "extracted_from", page.id)


async def overview() -> dict[str, Any]:
    """Cross-domain view for the dashboard: graph size, top domains, strategies."""
    async with session_scope() as session:
        counts = dict(
            (
                await session.execute(
                    select(KnowledgeEntity.entity_type, func.count()).group_by(
                        KnowledgeEntity.entity_type
                    )
                )
            ).all()
        )
        top = (
            await session.execute(
                select(KnowledgeEntity.domain, func.count())
                .where(KnowledgeEntity.entity_type == "page")
                .group_by(KnowledgeEntity.domain)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
        strategies = (
            (
                await session.execute(
                    select(DomainStrategy).order_by(DomainStrategy.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )
    return {
        "entities": counts,
        "top_domains": [{"domain": d, "pages": c} for d, c in top],
        "strategies": [
            {
                "domain": s.domain,
                "strategy": s.strategy,
                "success_rate": round(s.success_rate, 4),
                "avg_latency_ms": s.avg_latency_ms,
            }
            for s in strategies
        ],
    }


async def domain_snapshot(domain: str, limit: int = 10) -> dict[str, Any]:
    """Everything we know about a domain: counts + recent pages and records."""
    domain = domain.lower()
    async with session_scope() as session:
        counts = dict(
            (
                await session.execute(
                    select(KnowledgeEntity.entity_type, func.count())
                    .where(KnowledgeEntity.domain == domain)
                    .group_by(KnowledgeEntity.entity_type)
                )
            ).all()
        )

        async def _recent(entity_type: str) -> list[dict[str, Any]]:
            rows = (
                (
                    await session.execute(
                        select(KnowledgeEntity)
                        .where(
                            KnowledgeEntity.domain == domain,
                            KnowledgeEntity.entity_type == entity_type,
                        )
                        .order_by(KnowledgeEntity.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return [{"name": r.name, "data": r.data} for r in rows]

        pages = await _recent("page")
        records = await _recent("record")

    return {"domain": domain, "entities": counts, "pages": pages, "records": records}
