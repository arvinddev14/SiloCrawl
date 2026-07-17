"""Aggregate observability metrics from SQLite for /metrics and the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.db.base import session_scope
from app.db.models import CrawlJobRecord, Run


async def collect_metrics(hours: int = 24) -> dict[str, Any]:
    """Counts + latency per run kind, LLM usage per agent, crawl jobs by status.

    ``hours=0`` means all time.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours) if hours > 0 else None

    async with session_scope() as session:
        run_q = (
            select(Run.kind, Run.status, func.count(), func.avg(Run.duration_ms))
            .group_by(Run.kind, Run.status)
        )
        if since is not None:
            run_q = run_q.where(Run.created_at >= since)
        runs = [
            {
                "kind": kind,
                "status": status,
                "count": count,
                "avg_duration_ms": round(avg, 1) if avg is not None else None,
            }
            for kind, status, count, avg in (await session.execute(run_q)).all()
        ]

        llm_q = (
            select(
                Run.agent,
                Run.model,
                func.count(),
                func.coalesce(func.sum(Run.tokens), 0),
            )
            .where(Run.kind == "llm")
            .group_by(Run.agent, Run.model)
        )
        if since is not None:
            llm_q = llm_q.where(Run.created_at >= since)
        llm = [
            {"agent": agent, "model": model, "count": count, "total_tokens": tokens}
            for agent, model, count, tokens in (await session.execute(llm_q)).all()
        ]

        job_q = select(CrawlJobRecord.status, func.count()).group_by(
            CrawlJobRecord.status
        )
        if since is not None:
            job_q = job_q.where(CrawlJobRecord.created_at >= since)
        crawl_jobs = [
            {"status": status, "count": count}
            for status, count in (await session.execute(job_q)).all()
        ]

    return {"window_hours": hours, "runs": runs, "llm": llm, "crawl_jobs": crawl_jobs}
