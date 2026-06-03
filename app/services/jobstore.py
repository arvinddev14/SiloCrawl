"""Tiny Redis-backed store for crawl job state."""
from __future__ import annotations

import json

import redis.asyncio as redis

from app.core.config import get_settings
from app.models.schemas import CrawlJob, CrawlStatus

settings = get_settings()
_KEY = "silocrawl:job:{}"
_TTL = 60 * 60 * 24  # 24h


def _client() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


async def create(job_id: str) -> CrawlJob:
    job = CrawlJob(id=job_id, status=CrawlStatus.queued)
    await save(job)
    return job


async def save(job: CrawlJob) -> None:
    r = _client()
    await r.set(_KEY.format(job.id), job.model_dump_json(), ex=_TTL)
    await r.aclose()


async def get(job_id: str) -> CrawlJob | None:
    r = _client()
    raw = await r.get(_KEY.format(job_id))
    await r.aclose()
    return CrawlJob.model_validate_json(raw) if raw else None
