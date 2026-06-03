from __future__ import annotations

import uuid

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.models.schemas import (
    CrawlJob,
    CrawlRequest,
    ExtractRequest,
    ExtractResult,
    MapRequest,
    MapResult,
    ScrapeRequest,
    ScrapeResult,
)
from app.services import extractor, jobstore, mapper, scraper

settings = get_settings()
router = APIRouter(prefix="/v1")


@router.post("/scrape", response_model=ScrapeResult)
async def scrape_endpoint(req: ScrapeRequest):
    try:
        return await scraper.scrape(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Scrape failed: {e}") from e


@router.post("/map", response_model=MapResult)
async def map_endpoint(req: MapRequest):
    try:
        return await mapper.map_site(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Map failed: {e}") from e


@router.post("/extract", response_model=ExtractResult)
async def extract_endpoint(req: ExtractRequest):
    if not req.url and not req.content:
        raise HTTPException(400, "Provide 'url' or 'content'.")
    try:
        return await extractor.extract(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Extract failed: {e}") from e


@router.post("/crawl", response_model=CrawlJob, status_code=202)
async def crawl_endpoint(req: CrawlRequest):
    """Enqueue an async crawl job. Poll /crawl/{id} for status + results."""
    job_id = uuid.uuid4().hex
    await jobstore.create(job_id)
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await pool.enqueue_job("run_crawl", job_id, req.model_dump_json())
    await pool.aclose()
    job = await jobstore.get(job_id)
    assert job
    return job


@router.get("/crawl/{job_id}", response_model=CrawlJob)
async def crawl_status(job_id: str):
    job = await jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
