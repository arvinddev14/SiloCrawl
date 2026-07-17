"""Deterministic run evaluator: turn a finished loop run into metric scores.

No LLM involved — every number is derived from artifacts the pipeline already
produced (verification report, repair info, deep-extraction stats, terminal
state). The Benchmark Loop (``app/loop/benchmark.py``) persists these; Phase 4's
autonomous optimization treats them as its objective function.

``overall`` is deliberately simple and monotonic: ``success x confidence``
(confidence defaults to 1.0 when the run wasn't verified). A failed run scores
0 across the board — failures are signal, not noise.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import TelemetryEvent
from app.loop.state_machine import LoopContext, LoopState


def evaluate(ctx: LoopContext, duration_ms: int) -> dict[str, float]:
    metrics: dict[str, float] = {
        "success": 1.0 if ctx.state is LoopState.DONE else 0.0,
        "duration_ms": float(duration_ms),
    }

    result = ctx.extract_result
    verification = getattr(result, "verification", None) if result else None
    if verification:
        evidence = float(verification["evidence_score"])
        metrics["confidence"] = float(verification["confidence"])
        metrics["field_coverage"] = float(verification["field_coverage"])
        metrics["evidence_score"] = evidence
        metrics["hallucination_rate"] = round(1.0 - evidence, 4)

    repair = getattr(result, "repair", None) if result else None
    if repair and repair.get("attempted"):
        schema = getattr(ctx.request, "json_schema", None) or {}
        total = len(schema.get("properties") or {}) or 1
        repaired = len(repair.get("repaired_fields") or [])
        metrics["repair_rate"] = round(repaired / total, 4)

    extraction = getattr(result, "extraction", None) if result else None
    if extraction:
        metrics["llm_calls"] = float(extraction["llm_calls"])
        metrics["chunks"] = float(extraction["chunks"])

    confidence = metrics.get("confidence", 1.0)
    metrics["overall"] = round(metrics["success"] * confidence, 4)
    return metrics


# ---------- Frontend Improvement Loop (INC-B11) ----------

async def ux_report(hours: int = 24) -> dict[str, Any]:
    """Aggregate client UX events into signals + rule-based recommendations.

    Rules are deliberately deterministic and transparent — each one names the
    condition that fired it, so the dashboard (B13) can show *why*.
    """
    async with session_scope() as session:
        query = select(TelemetryEvent).where(TelemetryEvent.kind == "ux")
        if hours:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            query = query.where(TelemetryEvent.created_at >= since)
        rows = (await session.execute(query)).scalars().all()

    counts: dict[str, int] = {}
    waits: list[float] = []
    for row in rows:
        name = row.message or ""
        counts[name] = counts.get(name, 0) + 1
        if name == "playground.wait":
            value = (row.meta or {}).get("value")
            if isinstance(value, (int, float)):
                waits.append(float(value))

    requests = counts.get("playground.request", 0)
    errors = counts.get("playground.error", 0)
    abandons = counts.get("playground.abandon", 0)
    avg_wait_ms = round(sum(waits) / len(waits), 1) if waits else None
    error_rate = round(errors / requests, 4) if requests else 0.0
    abandon_rate = round(abandons / requests, 4) if requests else 0.0

    recommendations: list[str] = []
    if avg_wait_ms is not None and avg_wait_ms > 5000:
        recommendations.append(
            "Average wait exceeds 5s — surface progress earlier or make long "
            "operations async (queued crawl with polling)."
        )
    if requests and error_rate > 0.2:
        recommendations.append(
            "More than 20% of playground requests fail — surface clearer error "
            "messages and validate input before submitting."
        )
    if requests and abandon_rate > 0.25:
        recommendations.append(
            "Users abandon during waits — reduce time-to-first-result or show "
            "partial results while the request runs."
        )
    if not recommendations:
        recommendations.append("No UX issues detected in this window.")

    return {
        "window_hours": hours,
        "events": counts,
        "avg_wait_ms": avg_wait_ms,
        "error_rate": error_rate,
        "abandon_rate": abandon_rate,
        "recommendations": recommendations,
    }
