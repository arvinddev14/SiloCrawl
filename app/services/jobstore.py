"""Crawl-job state store, backed by SQLite (durable, no Redis).

Crawl jobs used to live in Redis with a 24h TTL and a separate arq worker.
They now run in-process (see :mod:`app.services.crawl_runner`) and their state
persists to SQLite via :mod:`app.db.crawl_store`, so a job is readable for as
long as the database keeps it — no TTL, no external queue.
"""
from __future__ import annotations

from app.db import crawl_store
from app.models.schemas import CrawlJob, CrawlStatus


async def create(job_id: str, url: str | None = None) -> CrawlJob:
    job = CrawlJob(id=job_id, status=CrawlStatus.queued)
    await crawl_store.save_crawl_job(job, url=url)
    return job


async def save(job: CrawlJob, url: str | None = None) -> None:
    await crawl_store.save_crawl_job(job, url=url)


async def get(job_id: str) -> CrawlJob | None:
    return await crawl_store.get_crawl_job(job_id)
