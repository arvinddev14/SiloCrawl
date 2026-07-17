"""High-level scrape: cache -> fetch -> clean."""
import base64

from app.models.schemas import OutputFormat, ScrapeRequest, ScrapeResult
from app.services import cache, cleaner, fetcher


async def scrape(req: ScrapeRequest, *, escalate: bool = False) -> ScrapeResult:
    cached = await cache.get(req)
    if cached is not None:
        return cached

    want_screenshot = OutputFormat.screenshot in req.formats
    resp = await fetcher.fetch(
        str(req.url),
        render_js=req.render_js,
        capture_screenshot=want_screenshot,
        escalate=escalate,
    )
    result = cleaner.clean(
        html=resp.html,
        url=resp.url,
        status_code=resp.status_code,
        formats=req.formats,
        only_main_content=req.only_main_content,
        include_tags=req.include_tags,
        exclude_tags=req.exclude_tags,
    )
    if want_screenshot and resp.screenshot:
        result.screenshot = base64.b64encode(resp.screenshot).decode()

    await cache.set(req, result)
    return result
