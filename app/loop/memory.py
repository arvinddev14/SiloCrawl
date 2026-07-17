"""Read-side memory: the compact per-domain context block agents consume.

This is the interface between accumulated knowledge and the agents that can use
it — the Planner (INC-B9) receives exactly this payload when deciding strategy,
and the dashboard (INC-B13) renders it. It merges the learned fetch strategy
(``domain_strategies``, INC-B2) with the knowledge graph (INC-B6).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import KnowledgeEntity
from app.loop import strategy as strategy_mod


async def domain_memory(domain: str) -> dict[str, Any]:
    """Compact summary of everything learned about ``domain``."""
    domain = domain.lower()

    remembered = await strategy_mod.get_strategy(domain)
    strategy_block = None
    if remembered is not None:
        strategy_block = {
            "strategy": remembered.strategy,
            "success_rate": round(remembered.success_rate, 4),
            "avg_latency_ms": remembered.avg_latency_ms,
        }

    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(KnowledgeEntity).where(KnowledgeEntity.domain == domain)
                )
            )
            .scalars()
            .all()
        )

    pages = [r for r in rows if r.entity_type == "page"]
    records = [r for r in rows if r.entity_type == "record"]
    dom = next((r for r in rows if r.entity_type == "domain"), None)

    field_counts: Counter[str] = Counter()
    for page in pages:
        field_counts.update((page.data or {}).get("fields") or [])

    return {
        "domain": domain,
        "strategy": strategy_block,
        "pages_known": len(pages),
        "records_known": len(records),
        "common_fields": [name for name, _ in field_counts.most_common(10)],
        "last_activity": (dom.data or {}).get("last_activity") if dom else None,
    }
