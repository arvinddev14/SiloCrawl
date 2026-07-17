"""Fetch raw HTML for a URL, optionally rendering JS with Playwright.

All fetches funnel through :func:`fetch`, which enforces robots.txt (when
``respect_robots`` is on) and per-domain politeness before dispatching to the
static (httpx) or rendered (Playwright) path.
"""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.services import robots
from app.services.throttle import throttle

settings = get_settings()


class FetchResponse:
    def __init__(
        self,
        url: str,
        html: str,
        status_code: int,
        screenshot: bytes | None = None,
    ):
        self.url = url
        self.html = html
        self.status_code = status_code
        self.screenshot = screenshot


class _wait_retry_after(wait_exponential):
    """Exponential backoff, but honor a server's Retry-After on 429/503 (capped)."""

    def __call__(self, retry_state) -> float:  # noqa: ANN001
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exc, httpx.HTTPStatusError):
            retry_after = exc.response.headers.get("retry-after", "")
            if retry_after.isdigit():
                return min(float(retry_after), 30.0)
        return super().__call__(retry_state)


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=_wait_retry_after(multiplier=0.5, max=8),
    reraise=True,
)
async def fetch_static(
    url: str, extra_headers: dict[str, str] | None = None
) -> FetchResponse:
    """Fast path: plain HTTP fetch, no JS.

    ``extra_headers`` layers browser-like headers on top of the default UA — the
    ``headers`` rung of the escalation ladder (INC-B2) uses it to clear naive bot
    filters without paying for a headless render.
    """
    headers = {"User-Agent": settings.user_agent}
    if extra_headers:
        headers.update(extra_headers)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=settings.request_timeout,
        headers=headers,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return FetchResponse(str(resp.url), resp.text, resp.status_code)


async def fetch_rendered(url: str, capture_screenshot: bool = False) -> FetchResponse:
    """JS path: render with a headless browser. Imported lazily so the
    package works without Playwright installed when render_js is never used."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent=settings.user_agent)
            resp = await page.goto(
                url, wait_until="networkidle", timeout=settings.request_timeout * 1000
            )
            html = await page.content()
            shot = await page.screenshot(full_page=True) if capture_screenshot else None
            status = resp.status if resp else 200
            final_url = page.url
            return FetchResponse(final_url, html, status, screenshot=shot)
        finally:
            await browser.close()


async def fetch(
    url: str,
    render_js: bool = False,
    capture_screenshot: bool = False,
    escalate: bool = False,
) -> FetchResponse:
    min_delay: float | None = None
    if settings.respect_robots:
        await robots.check(url)
        site_delay = await robots.crawl_delay(url)
        if site_delay is not None:
            min_delay = max(site_delay, settings.per_domain_delay)
    await throttle.wait(url, min_delay)

    if escalate:
        # SiloLoop path: walk the strategy ladder, learning per-domain winners.
        from app.loop import retries  # lazy: avoids a fetcher<->retries cycle

        return await retries.escalating_fetch(
            url, render_js=render_js, capture_screenshot=capture_screenshot
        )
    if render_js or capture_screenshot:
        return await fetch_rendered(url, capture_screenshot=capture_screenshot)
    return await fetch_static(url)
