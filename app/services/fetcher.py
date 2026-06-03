"""Fetch raw HTML for a URL, optionally rendering JS with Playwright."""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings

settings = get_settings()


class FetchResponse:
    def __init__(self, url: str, html: str, status_code: int):
        self.url = url
        self.html = html
        self.status_code = status_code


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=0.5, max=8),
    reraise=True,
)
async def fetch_static(url: str) -> FetchResponse:
    """Fast path: plain HTTP fetch, no JS."""
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=settings.request_timeout,
        headers={"User-Agent": settings.user_agent},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return FetchResponse(str(resp.url), resp.text, resp.status_code)


async def fetch_rendered(url: str) -> FetchResponse:
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
            status = resp.status if resp else 200
            final_url = page.url
            return FetchResponse(final_url, html, status)
        finally:
            await browser.close()


async def fetch(url: str, render_js: bool = False) -> FetchResponse:
    return await (fetch_rendered(url) if render_js else fetch_static(url))
