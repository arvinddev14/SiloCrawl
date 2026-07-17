"""robots.txt enforcement with per-domain caching.

Fetch failures and missing files mean "allowed" (the standard convention);
only an explicit Disallow for our user agent blocks a fetch.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import get_settings
from app.services import netguard

settings = get_settings()


class RobotsDisallowedError(Exception):
    def __init__(self, url: str):
        super().__init__(f"Blocked by robots.txt: {url}")
        self.url = url


# domain root -> (parser | None, fetched_at). None = no rules, allow everything.
_cache: dict[str, tuple[RobotFileParser | None, float]] = {}


def _root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


async def _get_parser(root: str) -> RobotFileParser | None:
    cached = _cache.get(root)
    if cached and time.monotonic() - cached[1] < settings.robots_cache_ttl:
        return cached[0]

    parser: RobotFileParser | None = None
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
            event_hooks=netguard.event_hooks(),
        ) as client:
            resp = await client.get(f"{root}/robots.txt")
        if resp.status_code == 200:
            parser = RobotFileParser()
            parser.parse(resp.text.splitlines())
    except httpx.HTTPError:
        parser = None  # unreachable robots.txt -> allow
    _cache[root] = (parser, time.monotonic())
    return parser


async def check(url: str) -> None:
    """Raise RobotsDisallowedError if robots.txt disallows this URL for us."""
    parser = await _get_parser(_root(url))
    if parser and not parser.can_fetch(settings.user_agent, url):
        raise RobotsDisallowedError(url)


async def crawl_delay(url: str) -> float | None:
    """The site's Crawl-delay directive for our user agent, if any."""
    parser = await _get_parser(_root(url))
    if not parser:
        return None
    try:
        delay = parser.crawl_delay(settings.user_agent)
    except Exception:  # noqa: BLE001 - malformed directives are not our problem
        return None
    return float(delay) if delay else None
