"""arq worker that runs crawl jobs off the Redis queue.

Start with:  arq app.workers.crawl_worker.WorkerSettings
"""
from __future__ import annotations

from arq.connections import RedisSettings

from app.core import telemetry
from app.core.config import get_settings
from app.db import crawl_store, init_db
from app.models.schemas import CrawlRequest, CrawlStatus, FailedPage
from app.services import crawler, jobstore

settings = get_settings()


async def run_crawl(ctx, job_id: str, req_json: str) -> None:
    req = CrawlRequest.model_validate_json(req_json)
    job = await jobstore.get(job_id)
    if not job:
        return

    async with telemetry.track("crawl", url=str(req.url)) as run:
        job.status = CrawlStatus.running
        await jobstore.save(job)

        def progress(completed: int, total: int, result):
            job.completed = completed
            job.total = total

        try:
            results, failures = await crawler.crawl(req, on_progress=progress)
            job.data = results
            job.failed_pages = [FailedPage(url=u, error=e) for u, e in failures]
            job.total = len(results) + len(failures)
            job.completed = len(results)
            job.status = CrawlStatus.completed
        except Exception as e:  # noqa: BLE001
            job.status = CrawlStatus.failed
            job.error = str(e)
        await jobstore.save(job)
        # Mirror the finished job into SQLite so it survives Redis's TTL.
        await crawl_store.save_crawl_job(job, url=str(req.url))
        run.meta = {
            "job_id": job_id,
            "status": job.status.value,
            "pages": job.completed,
            "failed": len(job.failed_pages),
        }


async def _on_startup(ctx) -> None:
    telemetry.setup_logging()
    await init_db()


class WorkerSettings:
    functions = [run_crawl]
    on_startup = _on_startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
