"""Breadth-first crawler with depth/page limits and concurrency control."""
from __future__ import annotations

import asyncio
import re
from collections import deque
from urllib.parse import urlparse

from app.core.config import get_settings
from app.models.schemas import (
    CrawlRequest,
    OutputFormat,
    ScrapeRequest,
    ScrapeResult,
)
from app.services import scraper

settings = get_settings()


def _matches(url: str, patterns: list[str] | None) -> bool:
    return any(re.search(p, url) for p in patterns) if patterns else False


def _allowed(url: str, base: str, req: CrawlRequest) -> bool:
    if not req.allow_external and urlparse(url).netloc != urlparse(base).netloc:
        return False
    if req.exclude_paths and _matches(url, req.exclude_paths):
        return False
    if req.include_paths and not _matches(url, req.include_paths):
        return False
    return True


async def crawl(
    req: CrawlRequest, on_progress=None
) -> tuple[list[ScrapeResult], list[tuple[str, str]]]:
    """Crawl a site. Returns (results, failed_pages) where failed_pages is a list of (url, error)."""
    base = str(req.url)
    seen: set[str] = {base}
    queue: deque[tuple[str, int]] = deque([(base, 0)])
    results: list[ScrapeResult] = []
    failures: list[tuple[str, str]] = []
    sem = asyncio.Semaphore(settings.crawl_concurrency)

    async def visit(url: str, depth: int) -> list[str]:
        async with sem:
            try:
                fmts = list(req.formats)
                if OutputFormat.links not in fmts:
                    fmts.append(OutputFormat.links)  # need links to keep crawling
                res = await scraper.scrape(
                    ScrapeRequest(url=url, formats=fmts, render_js=req.render_js)
                )
            except Exception as exc:  # noqa: BLE001
                failures.append((url, str(exc)))
                return []
            results.append(res)
            if on_progress:
                on_progress(len(results), len(seen), res)
            new_links = []
            if depth < req.max_depth and res.links:
                for link in res.links:
                    if link not in seen and _allowed(link, base, req):
                        seen.add(link)
                        new_links.append(link)
            return new_links

    while queue and len(results) < req.max_pages:
        batch = []
        while queue and len(batch) < settings.crawl_concurrency:
            batch.append(queue.popleft())
        discovered = await asyncio.gather(*(visit(u, d) for u, d in batch))
        for links, (_, depth) in zip(discovered, batch):
            for link in links:
                if len(queue) < req.max_pages * 3:  # bound queue size, not seen set
                    queue.append((link, depth + 1))

    return results[: req.max_pages], failures
