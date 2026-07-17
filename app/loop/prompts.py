"""Versioned, DB-backed agent prompts (``prompt_versions`` table).

Agents fetch their system prompts through :func:`get_prompt`, passing the
hardcoded constant as a fallback. First use seeds version 1 from that constant,
so out of the box behavior is byte-identical — but a new version can be
published (and rolled back) at runtime through the API, without a redeploy.
This is the substrate the Benchmark loop (INC-B10) and autonomous optimization
(INC-B14) use to trial and promote prompt changes.

Lookups are best-effort: a persistence problem returns the fallback rather than
ever blocking an LLM call.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import session_scope
from app.db.models import PromptVersion

logger = logging.getLogger("silocrawl")


async def _deactivate_all(session: AsyncSession, agent: str, name: str) -> None:
    rows = (
        (
            await session.execute(
                select(PromptVersion).where(
                    PromptVersion.agent == agent,
                    PromptVersion.name == name,
                    PromptVersion.active,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.active = False


async def get_prompt(agent: str, name: str, fallback: str) -> str:
    """Active template for (agent, name); seeds v1 from ``fallback`` on first use."""
    try:
        async with session_scope() as session:
            row = (
                (
                    await session.execute(
                        select(PromptVersion)
                        .where(
                            PromptVersion.agent == agent,
                            PromptVersion.name == name,
                            PromptVersion.active,
                        )
                        .order_by(PromptVersion.version.desc())
                    )
                )
                .scalars()
                .first()
            )
            if row is not None:
                return row.template
            session.add(
                PromptVersion(
                    agent=agent, name=name, template=fallback, version=1, active=True
                )
            )
            return fallback
    except Exception:  # noqa: BLE001 - never block an LLM call on prompt storage
        logger.warning("prompt_lookup_failed", exc_info=True)
        return fallback


async def set_prompt(agent: str, name: str, template: str) -> dict[str, Any]:
    """Publish the next version of a prompt and make it active."""
    async with session_scope() as session:
        latest = (
            await session.execute(
                select(func.max(PromptVersion.version)).where(
                    PromptVersion.agent == agent, PromptVersion.name == name
                )
            )
        ).scalar_one()
        next_version = (latest or 0) + 1
        await _deactivate_all(session, agent, name)
        session.add(
            PromptVersion(
                agent=agent, name=name, template=template, version=next_version, active=True
            )
        )
    return {"agent": agent, "name": name, "version": next_version, "active": True}


async def activate(agent: str, name: str, version: int) -> bool:
    """Roll (back) to an existing version. False if it doesn't exist."""
    async with session_scope() as session:
        target = (
            (
                await session.execute(
                    select(PromptVersion).where(
                        PromptVersion.agent == agent,
                        PromptVersion.name == name,
                        PromptVersion.version == version,
                    )
                )
            )
            .scalars()
            .first()
        )
        if target is None:
            return False
        await _deactivate_all(session, agent, name)
        target.active = True
        return True


async def list_prompts(agent: str | None = None) -> list[dict[str, Any]]:
    async with session_scope() as session:
        query = select(PromptVersion).order_by(
            PromptVersion.agent, PromptVersion.name, PromptVersion.version
        )
        if agent:
            query = query.where(PromptVersion.agent == agent)
        rows = (await session.execute(query)).scalars().all()
    return [
        {
            "agent": r.agent,
            "name": r.name,
            "version": r.version,
            "active": r.active,
            "template": r.template,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
