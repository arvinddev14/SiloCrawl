"""In-process crawl execution.

Replaces the arq/Redis worker: a crawl job runs as a background asyncio task
inside the API process, updating its state in SQLite. This drops the external
queue and the separate worker process — a self-hosted deploy is now just the
API (Redis becomes optional, used only by the opt-in response cache / auth).

Trade-off: a job in flight when the process stops is not resumed (it stays in
its last-persisted state). For a single-node self-host that is acceptable; the
API contract is unchanged (POST returns 202 + id, poll GET /crawl/{id}).
"""
from __future__ import annotations

import asyncio
import logging

from app.core import telemetry
from app.models.schemas import CrawlRequest, CrawlStatus, FailedPage
from app.services import crawler, jobstore

logger = logging.getLogger("silocrawl")

# Hold strong references so the event loop can't garbage-collect a running task.
_tasks: set[asyncio.Task] = set()


async def run_job(job_id: str, req: CrawlRequest) -> None:
    """Execute a crawl and persist its outcome. Never raises to the caller."""
    job = await jobstore.get(job_id)
    if job is None:
        logger.warning("crawl_job_missing", extra={"job_id": job_id})
        return

    url = str(req.url)
    async with telemetry.track("crawl", url=url) as run:
        job.status = CrawlStatus.running
        await jobstore.save(job, url=url)

        def progress(completed: int, total: int, result) -> None:  # noqa: ANN001
            job.completed = completed
            job.total = total

        try:
            results, failures = await crawler.crawl(req, on_progress=progress)
            job.data = results
            job.failed_pages = [FailedPage(url=u, error=e) for u, e in failures]
            job.total = len(results) + len(failures)
            job.completed = len(results)
            job.status = CrawlStatus.completed
        except Exception as e:  # noqa: BLE001 - a failed crawl is a job outcome
            job.status = CrawlStatus.failed
            job.error = str(e)
        await jobstore.save(job, url=url)
        run.meta = {
            "job_id": job_id,
            "status": job.status.value,
            "pages": job.completed,
            "failed": len(job.failed_pages),
        }


def start(job_id: str, req: CrawlRequest) -> asyncio.Task:
    """Launch a crawl in the background and return its task."""
    task = asyncio.create_task(run_job(job_id, req))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task
