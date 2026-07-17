"""Structured logging + best-effort run telemetry.

Every execution is observable (SiloLoop principle #4): service boundaries wrap
work in :func:`track`, which writes a ``runs`` row (and a ``telemetry_events``
row on failure) to SQLite. Telemetry is strictly best-effort — a persistence
hiccup is logged and swallowed, never surfaced to the user request.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.core.config import get_settings

logger = logging.getLogger("silocrawl")

_LOG_RECORD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line; extra= fields are included automatically."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


_configured = False


def setup_logging() -> None:
    """Route root logging through the JSON formatter. Idempotent."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(get_settings().log_level.upper())
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


class RunHandle:
    """Mutable handle so the tracked block can attach agent/model/tokens/etc."""

    def __init__(self, run_id: str, meta: dict[str, Any] | None = None):
        self.id = run_id
        self.agent: str | None = None
        self.model: str | None = None
        self.tokens: int | None = None
        self.confidence: float | None = None
        self.meta = meta


async def _persist(
    handle: RunHandle,
    kind: str,
    url: str | None,
    status: str,
    duration_ms: int,
    error: BaseException | None,
) -> None:
    from app.db.base import session_scope
    from app.db.models import Run, TelemetryEvent

    async with session_scope() as session:
        session.add(
            Run(
                id=handle.id,
                kind=kind,
                url=url,
                status=status,
                agent=handle.agent,
                model=handle.model,
                tokens=handle.tokens,
                confidence=handle.confidence,
                finished_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                meta=handle.meta,
            )
        )
        if error is not None:
            session.add(
                TelemetryEvent(run_id=handle.id, kind="error", message=str(error))
            )


@asynccontextmanager
async def track(
    kind: str, url: str | None = None, meta: dict[str, Any] | None = None
) -> AsyncIterator[RunHandle]:
    """Record one unit of work as a run. Re-raises; never fails the caller."""
    handle = RunHandle(uuid.uuid4().hex, meta=meta)
    if not get_settings().telemetry_enabled:
        yield handle
        return

    start = time.monotonic()
    error: BaseException | None = None
    try:
        yield handle
    except BaseException as e:
        error = e
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        status = "error" if error else "ok"
        logger.info(
            "run",
            extra={
                "run_id": handle.id,
                "kind": kind,
                "url": url,
                "status": status,
                "duration_ms": duration_ms,
            },
        )
        try:
            await _persist(handle, kind, url, status, duration_ms, error)
        except Exception:  # noqa: BLE001 - telemetry must never break the request
            logger.warning("telemetry_persist_failed", exc_info=True)
