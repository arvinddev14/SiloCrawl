"""Optional API-key auth + per-key rate limiting.

Disabled by default (``auth_enabled=false``) so self-hosting stays zero-config.
When enabled, ``/v1/*`` and ``/metrics`` require a key from ``api_keys``, and
each key gets a fixed-window Redis quota. Raw keys are never logged or stored —
a short sha256 key-id identifies clients in logs and rate-limit keys.

If Redis is unreachable the quota check fails open (auth itself still holds).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time

import redis.asyncio as redis
from fastapi import HTTPException, Request

from app.core.config import get_settings

logger = logging.getLogger("silocrawl.auth")


def _client() -> redis.Redis:
    return redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def _extract_key(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip() or None
    return request.headers.get("x-api-key")


def _valid_keys() -> set[str]:
    return {k.strip() for k in get_settings().api_keys.split(",") if k.strip()}


async def _check_rate_limit(key_id: str) -> None:
    limit = get_settings().rate_limit_per_minute
    if limit <= 0:
        return
    minute = int(time.time() // 60)
    rl_key = f"silocrawl:rl:{key_id}:{minute}"
    try:
        r = _client()
        count = await r.incr(rl_key)
        if count == 1:
            await r.expire(rl_key, 120)
        await r.aclose()
    except Exception:  # noqa: BLE001 - fail open: quota degrades, auth still holds
        logger.warning("rate_limit_check_failed", extra={"key_id": key_id})
        return
    if count > limit:
        retry_after = 60 - int(time.time() % 60)
        raise HTTPException(
            429, "Rate limit exceeded", headers={"Retry-After": str(retry_after)}
        )


async def require_api_key(request: Request) -> None:
    """FastAPI dependency: no-op unless auth is enabled."""
    if not get_settings().auth_enabled:
        return
    key = _extract_key(request)
    if not key or not any(secrets.compare_digest(key, valid) for valid in _valid_keys()):
        raise HTTPException(401, "Invalid or missing API key")
    key_id = hashlib.sha256(key.encode()).hexdigest()[:12]
    request.state.api_key_id = key_id
    await _check_rate_limit(key_id)
