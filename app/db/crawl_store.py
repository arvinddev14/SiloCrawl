"""Durable crawl-job storage (SQLite).

The system of record for crawl jobs: created queued, updated as the in-process
runner makes progress, and read back by the status endpoint. No TTL — jobs
persist for as long as the database keeps them.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import CrawlJobRecord, DeletionLog
from app.models.schemas import CrawlJob


async def save_crawl_job(job: CrawlJob, url: str | None = None) -> None:
    async with session_scope() as session:
        record = await session.get(CrawlJobRecord, job.id)
        payload = job.model_dump(mode="json")
        if record is None:
            session.add(
                CrawlJobRecord(
                    id=job.id,
                    url=url,
                    status=job.status.value,
                    total=job.total,
                    completed=job.completed,
                    payload=payload,
                )
            )
        else:
            record.status = job.status.value
            record.total = job.total
            record.completed = job.completed
            record.payload = payload
            if url is not None:
                record.url = url


async def get_crawl_job(job_id: str) -> CrawlJob | None:
    async with session_scope() as session:
        record = (
            await session.execute(
                select(CrawlJobRecord).where(CrawlJobRecord.id == job_id)
            )
        ).scalar_one_or_none()
        if record is None:
            return None
        return CrawlJob.model_validate(record.payload)


async def list_crawl_jobs(limit: int = 100) -> list[dict]:
    """Lightweight index of stored jobs (no page content) for data-subject
    access / portability. Full content is available via get_crawl_job."""
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(CrawlJobRecord)
                .order_by(CrawlJobRecord.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    return [
        {
            "id": r.id,
            "url": r.url,
            "status": r.status,
            "total": r.total,
            "completed": r.completed,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


async def delete_crawl_job(job_id: str, actor: str | None = None) -> bool:
    """Erase a crawl job and the content it captured. False if it wasn't there.

    The deletion and its audit-log entry commit in one transaction, so a
    recorded erasure always corresponds to a real one (and vice versa).
    """
    async with session_scope() as session:
        record = await session.get(CrawlJobRecord, job_id)
        if record is None:
            return False
        await session.delete(record)
        session.add(
            DeletionLog(target_type="crawl_job", target_id=job_id, count=1, actor=actor)
        )
    return True
