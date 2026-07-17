"""Drives a :class:`LoopContext` through the SiloLoop state machine.

INC-B1 is orchestration only: each stage delegates to an existing service
(``scraper.scrape`` / ``extractor.extract``) — no new scraping or extraction
logic lives here. The value added is structure and observability: the whole run
is wrapped in one ``telemetry.track("loop")`` span that records the path taken
and the terminal state. Later increments swap the plain stage handlers for
retrying / verifying / repairing variants without changing this driver or the
call sites.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from app.core import telemetry
from app.loop.state_machine import LoopContext, LoopState
from app.services import extractor, scraper

logger = logging.getLogger("silocrawl")

# Ordered pipelines per entry point. DONE is the terminal marker; its handler is
# a no-op. PLAN is currently a placeholder that the Planner agent fills in B9.
SCRAPE_STEPS: tuple[LoopState, ...] = (LoopState.PLAN, LoopState.FETCH, LoopState.DONE)
EXTRACT_STEPS: tuple[LoopState, ...] = (LoopState.PLAN, LoopState.EXTRACT, LoopState.DONE)


def extract_steps(*, verify: bool = False, repair: bool = False) -> tuple[LoopState, ...]:
    """Extract pipeline, optionally with Verification (B3) / Repair (B4) stages."""
    steps: list[LoopState] = [LoopState.PLAN, LoopState.EXTRACT]
    if verify:
        steps.append(LoopState.VERIFY)
    if repair:
        steps.append(LoopState.REPAIR)
    steps.append(LoopState.DONE)
    return tuple(steps)


async def _plan(ctx: LoopContext) -> None:
    # The Planner (INC-B9): domain memory -> execution plan -> optional schema
    # generation. Advisory end to end — a planning failure never kills the run.
    ctx.meta["planned"] = True

    memory_block = None
    url = _url_of(ctx.request)
    if url:
        try:
            from urllib.parse import urlparse

            from app.loop.memory import domain_memory  # lazy: package may be mid-init

            memory_block = await domain_memory(urlparse(url).netloc)
            ctx.meta["memory"] = memory_block
        except Exception:  # noqa: BLE001
            logger.warning("plan_memory_failed", exc_info=True)

    try:
        from app.services import planner  # lazy, like the other stage imports

        plan = planner.build_plan(ctx.request, memory_block, ctx.steps)
        extraction = plan.get("extraction")
        if extraction is not None and extraction["schema_source"] == "generated":
            generated = await planner.generate_schema(ctx.request.prompt)
            if generated is not None:
                ctx.request.json_schema = generated
            else:
                extraction["schema_source"] = "freeform"  # graceful downgrade
        ctx.meta["plan"] = plan
    except Exception:  # noqa: BLE001
        logger.warning("plan_failed", exc_info=True)


async def _fetch(ctx: LoopContext) -> None:
    # escalate=True engages the Retry Engine (INC-B2): escalate strategies on
    # failure and learn the winning one per domain.
    ctx.scrape_result = await scraper.scrape(ctx.request, escalate=True)


async def _extract(ctx: LoopContext) -> None:
    # Fetch content once and keep it on the context so later VERIFY/REPAIR
    # stages check the extraction against the exact same content.
    content, source_url = await extractor.get_content(ctx.request, escalate=True)
    ctx.content = content
    try:
        # deep=True engages the Extraction Loop (INC-B5): chunk long pages,
        # map-reduce, and retry only the fields still missing.
        ctx.extract_result = await extractor.extract(
            ctx.request, escalate=True, content=content, source_url=source_url, deep=True
        )
    except extractor.ExtractionParseError as e:
        if LoopState.REPAIR not in ctx.steps:
            raise
        # A REPAIR stage is coming — salvage the broken JSON instead of dying.
        from app.services import repair as repair_service
        from app.models.schemas import ExtractResult

        data, _ = await repair_service.repair_json(e.raw, ctx.request.json_schema or {})
        if data is None:
            raise
        ctx.extract_result = ExtractResult(data=data, source_url=source_url)
        ctx.meta["parse_repaired"] = True
    if ctx.extract_result.extraction:
        ctx.meta["extraction"] = ctx.extract_result.extraction


async def _verify(ctx: LoopContext) -> None:
    from app.services import verifier  # lazy: keeps orchestrator import-light

    report = await verifier.verify(
        ctx.request.json_schema, ctx.extract_result.data, ctx.content or ""
    )
    ctx.extract_result.confidence = report.confidence
    ctx.extract_result.verification = report.model_dump()
    ctx.meta["verdict"] = report.verdict


async def _repair(ctx: LoopContext) -> None:
    from app.services import repair as repair_service  # lazy, like _verify

    result = ctx.extract_result
    unsupported = (result.verification or {}).get("unsupported_fields")
    result.data, info = await repair_service.repair_result(
        result.data, ctx.request.json_schema, ctx.content or "", unsupported
    )
    if ctx.meta.get("parse_repaired"):
        info["attempted"] = True
        info["parse_repaired"] = True
    result.repair = info
    # Confidence must describe the repaired data — re-run VERIFY if it was on.
    if LoopState.VERIFY in ctx.steps and info["repaired_fields"]:
        await _verify(ctx)


_HANDLERS: dict[LoopState, Callable[[LoopContext], Awaitable[None]] | None] = {
    LoopState.PLAN: _plan,
    LoopState.FETCH: _fetch,
    LoopState.EXTRACT: _extract,
    LoopState.VERIFY: _verify,
    LoopState.REPAIR: _repair,
    LoopState.DONE: None,
}


def _url_of(request: Any) -> str | None:
    url = getattr(request, "url", None)
    return str(url) if url else None


async def run(
    request: Any, *, steps: tuple[LoopState, ...], benchmark: bool = False
) -> Any:
    """Execute ``request`` through ``steps`` and return the terminal artifact.

    ``steps`` selects the pipeline (``SCRAPE_STEPS`` / ``EXTRACT_STEPS``). Returns
    the extract result when the pipeline extracts, otherwise the scrape result.
    On any stage failure the machine moves to ERROR and the exception propagates
    to the caller (the route maps it to an HTTP status, exactly as the plain
    path does). ``benchmark=True`` scores the run into the benchmarks table —
    including failed runs, which is exactly what success-rate trends need.
    """
    ctx = LoopContext(request=request, steps=steps)
    ctx.state = steps[0]
    ctx.history.append(steps[0])
    started = time.monotonic()

    try:
        async with telemetry.track("loop", url=_url_of(request), meta=ctx.meta) as handle:
            ctx.run_id = handle.id
            try:
                for i, step in enumerate(steps):
                    if i > 0:
                        ctx.advance(step)
                    handler = _HANDLERS[step]
                    if handler is not None:
                        await handler(ctx)
            except Exception as e:
                ctx.error = str(e)
                if ctx.state is not LoopState.ERROR:
                    ctx.advance(LoopState.ERROR)
                raise
            finally:
                # Surface the path + outcome on the run row for observability.
                ctx.meta["path"] = [s.value for s in ctx.history]
                ctx.meta["final_state"] = ctx.state.value
                handle.agent = "orchestrator"
                confidence = getattr(ctx.extract_result, "confidence", None)
                if confidence is not None:
                    handle.confidence = confidence
    except Exception:
        if benchmark:
            await _capture_benchmarks(ctx, started)
        raise

    if benchmark:
        await _capture_benchmarks(ctx, started)
    await _capture_knowledge(ctx)
    return ctx.extract_result if LoopState.EXTRACT in steps else ctx.scrape_result


async def _capture_benchmarks(ctx: LoopContext, started: float) -> None:
    """Post-run Benchmark Loop hook (INC-B10). Best-effort, never fails the run."""
    try:
        from app.loop import benchmark  # lazy, like the other stage imports
        from app.services import evaluator

        duration_ms = int((time.monotonic() - started) * 1000)
        metrics = evaluator.evaluate(ctx, duration_ms)
        await benchmark.record(ctx.run_id, metrics)
    except Exception:  # noqa: BLE001 - scoring is a bonus, not a dependency
        logger.warning("benchmark_capture_failed", exc_info=True)


async def _capture_knowledge(ctx: LoopContext) -> None:
    """Post-run Knowledge Loop hook (INC-B6). Best-effort — never fails the run.

    Skips capture when verification judged the extraction a ``fail``: bad data
    must not become remembered knowledge.
    """
    result = ctx.extract_result
    if result is None or not getattr(result, "data", None):
        return
    if ctx.meta.get("verdict") == "fail":
        return
    try:
        from app.services import knowledge  # lazy, like the other stage imports

        await knowledge.record_extraction(
            getattr(result, "source_url", None) or _url_of(ctx.request),
            result.data,
            confidence=getattr(result, "confidence", None),
        )
    except Exception:  # noqa: BLE001 - memory is a bonus, not a dependency
        logger.warning("knowledge_capture_failed", exc_info=True)
