"""Retry Engine: escalate a fetch through the strategy ladder until one works.

This is the SiloLoop counterpart to the plain ``fetcher.fetch`` path. On a
*retryable* failure it climbs :data:`app.loop.strategy.LADDER` — static, then
browser-like headers, then a headless render, then a delayed render — recording
each attempt so the domain's winning strategy is remembered for next time. A
terminal failure (404, robots-disallowed, ...) stops immediately; escalating
wouldn't help.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.loop import strategy
from app.loop.strategy import BROWSER_HEADERS, DELAY_RUNG_BACKOFF, LADDER
from app.services import fetcher
from app.services.fetcher import FetchResponse

logger = logging.getLogger("silocrawl")


async def _attempt(
    rung: str, url: str, *, capture_screenshot: bool
) -> FetchResponse:
    if rung == "static":
        return await fetcher.fetch_static(url)
    if rung == "headers":
        return await fetcher.fetch_static(url, extra_headers=BROWSER_HEADERS)
    if rung == "browser":
        return await fetcher.fetch_rendered(url, capture_screenshot=capture_screenshot)
    if rung == "browser_delay":
        await asyncio.sleep(DELAY_RUNG_BACKOFF)
        return await fetcher.fetch_rendered(url, capture_screenshot=capture_screenshot)
    raise ValueError(f"unknown strategy rung: {rung}")


async def escalating_fetch(
    url: str, *, render_js: bool = False, capture_screenshot: bool = False
) -> FetchResponse:
    """Fetch ``url``, climbing the ladder on retryable failures.

    Returns the first successful :class:`FetchResponse`. If every rung from the
    starting point fails, the last exception is re-raised. A non-retryable error
    on any rung is recorded and re-raised without further escalation.
    """
    domain = strategy.domain_of(url)
    remembered = await strategy.get_strategy(domain)
    force_browser = render_js or capture_screenshot
    start = strategy.starting_rung(remembered, force_browser=force_browser)

    last_exc: BaseException | None = None
    for rung in LADDER[start:]:
        began = time.monotonic()
        try:
            resp = await _attempt(rung, url, capture_screenshot=capture_screenshot)
        except Exception as exc:  # noqa: BLE001 - classified below
            latency_ms = (time.monotonic() - began) * 1000
            await strategy.record_outcome(domain, rung, ok=False, latency_ms=latency_ms)
            last_exc = exc
            if not strategy.is_retryable(exc):
                raise  # terminal — a heavier strategy can't fix a 404
            logger.info(
                "fetch_escalate",
                extra={"url": url, "rung": rung, "error": str(exc)},
            )
            continue
        latency_ms = (time.monotonic() - began) * 1000
        await strategy.record_outcome(domain, rung, ok=True, latency_ms=latency_ms)
        return resp

    assert last_exc is not None  # loop ran at least once
    raise last_exc
