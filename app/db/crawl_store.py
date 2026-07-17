"""Durable crawl-job storage.

Mirrors finished crawl jobs into SQLite so they survive past Redis's 24h TTL.
The API reads Redis first (live progress) and falls back here for old jobs.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import CrawlJobRecord
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
