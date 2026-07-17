"""Crawl intelligence: the fetch escalation ladder + learned per-domain memory.

The engine tries progressively heavier fetch strategies and remembers which one
actually works for each domain, so the next crawl of that domain can skip the
cheap rungs that historically fail. Memory lives in the ``domain_strategies``
table (defined at INC-3) and is updated with an exponential moving average so a
single fluke doesn't overwrite a stable winner.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import DomainStrategy

# Ordered cheapest -> heaviest. ``proxy`` is intentionally absent until we add
# IP rotation (the column already accepts it).
LADDER: tuple[str, ...] = ("static", "headers", "browser", "browser_delay")

# Browser-like headers for the ``headers`` rung — enough to clear naive UA/bot
# filters without paying for a full headless render.
BROWSER_HEADERS: dict[str, str] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

# Extra politeness applied on the ``browser_delay`` rung (seconds).
DELAY_RUNG_BACKOFF = 3.0

# EMA weight for a new observation and the threshold above which a remembered
# strategy is trusted as the starting rung.
_ALPHA = 0.3
_TRUST_THRESHOLD = 0.5

# HTTP statuses worth escalating on (soft blocks / rate limits). Anything else
# (404, 401, robots-disallowed) is terminal — escalating won't help.
RETRYABLE_STATUSES = frozenset({403, 408, 425, 429, 500, 502, 503, 504})


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def is_retryable(exc: BaseException) -> bool:
    """True if escalating to a heavier strategy might plausibly succeed."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUSES
    # Transport-level problems (connect/read/timeouts) are worth another rung.
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


async def get_strategy(domain: str) -> DomainStrategy | None:
    async with session_scope() as session:
        return (
            await session.execute(
                select(DomainStrategy).where(DomainStrategy.domain == domain)
            )
        ).scalar_one_or_none()


def starting_rung(remembered: DomainStrategy | None, *, force_browser: bool) -> int:
    """Index into :data:`LADDER` to begin escalation from."""
    if force_browser:
        return LADDER.index("browser")
    if (
        remembered is not None
        and remembered.strategy in LADDER
        and remembered.success_rate >= _TRUST_THRESHOLD
    ):
        return LADDER.index(remembered.strategy)
    return 0


async def record_outcome(
    domain: str, strategy: str, ok: bool, latency_ms: float | None
) -> None:
    """Fold one attempt into the domain's learned strategy via EMA upsert."""
    async with session_scope() as session:
        row = (
            await session.execute(
                select(DomainStrategy).where(DomainStrategy.domain == domain)
            )
        ).scalar_one_or_none()
        sample = 1.0 if ok else 0.0
        if row is None:
            session.add(
                DomainStrategy(
                    domain=domain,
                    strategy=strategy,
                    success_rate=sample,
                    avg_latency_ms=latency_ms,
                )
            )
            return
        row.success_rate = (1 - _ALPHA) * row.success_rate + _ALPHA * sample
        if latency_ms is not None:
            row.avg_latency_ms = (
                latency_ms
                if row.avg_latency_ms is None
                else (1 - _ALPHA) * row.avg_latency_ms + _ALPHA * latency_ms
            )
        # A successful attempt claims the domain's preferred strategy.
        if ok:
            row.strategy = strategy
