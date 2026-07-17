"""Best-effort Redis cache for scrape results.

Disabled unless ``scrape_cache_ttl > 0``. Every Redis failure is swallowed so
scrape keeps working with no Redis at all — the cache may never become a hard
dependency of the fetch path.
"""
from __future__ import annotations

import hashlib
import json

import redis.asyncio as redis

from app.core.config import get_settings
from app.models.schemas import ScrapeRequest, ScrapeResult

settings = get_settings()
_PREFIX = "silocrawl:cache:"


def _key(req: ScrapeRequest) -> str:
    basis = json.dumps(
        {
            "url": str(req.url),
            "formats": sorted(f.value for f in req.formats),
            "render_js": req.render_js,
            "only_main_content": req.only_main_content,
            "include_tags": req.include_tags,
            "exclude_tags": req.exclude_tags,
        },
        sort_keys=True,
    )
    return _PREFIX + hashlib.sha256(basis.encode()).hexdigest()


def _client() -> redis.Redis:
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


async def get(req: ScrapeRequest) -> ScrapeResult | None:
    if settings.scrape_cache_ttl <= 0:
        return None
    try:
        r = _client()
        raw = await r.get(_key(req))
        await r.aclose()
    except Exception:  # noqa: BLE001 - cache is best-effort
        return None
    return ScrapeResult.model_validate_json(raw) if raw else None


async def set(req: ScrapeRequest, result: ScrapeResult) -> None:
    if settings.scrape_cache_ttl <= 0:
        return
    try:
        r = _client()
        await r.set(_key(req), result.model_dump_json(), ex=settings.scrape_cache_ttl)
        await r.aclose()
    except Exception:  # noqa: BLE001 - cache is best-effort
        pass
