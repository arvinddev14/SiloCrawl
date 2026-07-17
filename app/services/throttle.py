"""Per-domain politeness: a minimum interval between requests to the same host.

Different domains never block each other; same-domain requests are serialized
and spaced by at least the configured delay (or the site's robots Crawl-delay,
capped so a hostile directive can't stall a crawl).
"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

from app.core.config import get_settings

settings = get_settings()

_MAX_DELAY = 10.0


class DomainThrottle:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, url: str, min_delay: float | None = None) -> None:
        host = urlparse(url).netloc
        if not host:
            return
        delay = min(
            min_delay if min_delay is not None else settings.per_domain_delay, _MAX_DELAY
        )
        if delay <= 0:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._last.get(host)
            if last is not None:
                remaining = delay - (time.monotonic() - last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last[host] = time.monotonic()


throttle = DomainThrottle()
