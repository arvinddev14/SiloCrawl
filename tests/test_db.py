from sqlalchemy import inspect

from app.db.base import get_engine
from app.db.crawl_store import get_crawl_job, save_crawl_job
from app.models.schemas import (
    CrawlJob,
    CrawlStatus,
    FailedPage,
    PageMetadata,
    ScrapeResult,
)


async def test_init_creates_tables(temp_db):
    async with get_engine().connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    for expected in ("crawl_jobs", "runs", "telemetry_events", "domain_strategies",
                     "knowledge_entities", "benchmarks", "prompt_versions"):
        assert expected in tables


async def test_crawl_job_roundtrip(temp_db):
    job = CrawlJob(
        id="job123",
        status=CrawlStatus.completed,
        total=1,
        completed=1,
        data=[ScrapeResult(metadata=PageMetadata(source_url="https://example.com"), markdown="hi")],
        failed_pages=[FailedPage(url="https://example.com/x", error="boom")],
    )
    await save_crawl_job(job, url="https://example.com")

    got = await get_crawl_job("job123")
    assert got is not None
    assert got.id == "job123"
    assert got.status == CrawlStatus.completed
    assert got.data[0].markdown == "hi"
    assert got.failed_pages[0].error == "boom"


async def test_save_is_idempotent_upsert(temp_db):
    job = CrawlJob(id="dup", status=CrawlStatus.running, total=0, completed=0)
    await save_crawl_job(job, url="https://example.com")
    job.status = CrawlStatus.completed
    job.completed = 5
    await save_crawl_job(job, url="https://example.com")

    got = await get_crawl_job("dup")
    assert got.status == CrawlStatus.completed
    assert got.completed == 5


async def test_missing_job_returns_none(temp_db):
    assert await get_crawl_job("nope") is None
