"""High-level scrape: fetch then clean."""
from app.models.schemas import ScrapeRequest, ScrapeResult
from app.services import cleaner, fetcher


async def scrape(req: ScrapeRequest) -> ScrapeResult:
    resp = await fetcher.fetch(str(req.url), render_js=req.render_js)
    return cleaner.clean(
        html=resp.html,
        url=resp.url,
        status_code=resp.status_code,
        formats=req.formats,
        only_main_content=req.only_main_content,
        include_tags=req.include_tags,
        exclude_tags=req.exclude_tags,
    )
