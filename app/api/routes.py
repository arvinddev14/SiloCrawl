from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.core import telemetry
from app.core.auth import require_api_key
from app.core.config import get_settings
from app.db.base import session_scope
from app.db.models import TelemetryEvent
from app.models.schemas import (
    ClientEventBatch,
    CrawlJob,
    CrawlRequest,
    DocumentRequest,
    DocumentResult,
    ExtractRequest,
    ExtractResult,
    MapRequest,
    MapResult,
    ScrapeRequest,
    ScrapeResult,
)
from app.loop import benchmark as benchmark_loop
from app.loop import experiments, memory, orchestrator, prompts
from app.loop.orchestrator import SCRAPE_STEPS
from app.services import (
    crawl_runner,
    documents,
    evaluator,
    extractor,
    jobstore,
    knowledge,
    mapper,
    scraper,
    verifier,
)
from app.services import repair as repair_service
from app.services.netguard import PrivateAddressError
from app.services.robots import RobotsDisallowedError

logger = logging.getLogger("silocrawl")

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@router.post("/scrape", response_model=ScrapeResult)
async def scrape_endpoint(req: ScrapeRequest, loop: bool = False, benchmark: bool = False):
    try:
        if loop or benchmark:  # benchmark measures the pipeline, so it implies it
            return await orchestrator.run(req, steps=SCRAPE_STEPS, benchmark=benchmark)
        async with telemetry.track("scrape", url=str(req.url)):
            return await scraper.scrape(req)
    except (RobotsDisallowedError, PrivateAddressError) as e:
        raise HTTPException(403, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Scrape failed: {e}") from e


@router.post("/map", response_model=MapResult)
async def map_endpoint(req: MapRequest):
    try:
        async with telemetry.track("map", url=str(req.url)):
            return await mapper.map_site(req)
    except PrivateAddressError as e:
        raise HTTPException(403, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Map failed: {e}") from e


@router.post("/extract", response_model=ExtractResult)
async def extract_endpoint(
    req: ExtractRequest,
    loop: bool = False,
    verify: bool = False,
    repair: bool = False,
    benchmark: bool = False,
):
    if not req.url and not req.content:
        raise HTTPException(400, "Provide 'url' or 'content'.")
    try:
        if loop or benchmark:  # benchmark measures the pipeline, so it implies it
            steps = orchestrator.extract_steps(verify=verify, repair=repair)
            return await orchestrator.run(req, steps=steps, benchmark=benchmark)
        async with telemetry.track("extract", url=str(req.url) if req.url else None) as handle:
            if repair:
                result = await repair_service.extract_and_repair(req, verify=verify)
                handle.confidence = result.confidence
                return result
            if verify:
                result = await verifier.extract_and_verify(req)
                handle.confidence = result.confidence
                return result
            return await extractor.extract(req)
    except (RobotsDisallowedError, PrivateAddressError) as e:
        raise HTTPException(403, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Extract failed: {e}") from e


async def _document_result(text, meta, schema, prompt, verify, repair, handle) -> DocumentResult:
    """Wrap converted text; run the extract/verify/repair pipeline if asked."""
    result = DocumentResult(text=text, metadata=meta)
    if schema is None and prompt is None:
        return result
    ereq = ExtractRequest(content=text, schema=schema, prompt=prompt)
    if repair:
        ext = await repair_service.extract_and_repair(ereq, verify=verify)
    elif verify:
        ext = await verifier.extract_and_verify(ereq)
    else:
        ext = await extractor.extract(ereq)
    result.data = ext.data
    result.confidence = ext.confidence
    result.verification = ext.verification
    result.repair = ext.repair
    handle.confidence = ext.confidence
    return result


@router.post("/document", response_model=DocumentResult)
async def document_endpoint(req: DocumentRequest, verify: bool = False, repair: bool = False):
    """Fetch a document (pdf/docx/pptx/xlsx/csv/...), convert to text, optionally extract."""
    try:
        async with telemetry.track("document", url=str(req.url)) as handle:
            text, meta = await documents.process(url=str(req.url))
            return await _document_result(
                text, meta, req.json_schema, req.prompt, verify, repair, handle
            )
    except (RobotsDisallowedError, PrivateAddressError) as e:
        raise HTTPException(403, str(e)) from e
    except documents.DocumentTooLargeError as e:
        raise HTTPException(413, str(e)) from e
    except documents.DocumentError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Document processing failed: {e}") from e


@router.post("/document/upload", response_model=DocumentResult)
async def document_upload_endpoint(
    file: UploadFile = File(...),
    # form field is still called "schema"; the alias avoids shadowing
    # BaseModel.schema in the generated body model
    extract_schema: str | None = Form(None, alias="schema"),
    prompt: str | None = Form(None),
    verify: bool = False,
    repair: bool = False,
):
    """Upload a document instead of pointing at a URL. Same processing."""
    schema_dict = None
    if extract_schema:
        try:
            schema_dict = json.loads(extract_schema)
        except json.JSONDecodeError as e:
            raise HTTPException(400, "'schema' must be valid JSON.") from e
    # Read at most limit+1 bytes so an oversized upload is refused by process()
    # without ever buffering the whole thing.
    raw = await file.read(get_settings().document_max_bytes + 1)
    try:
        async with telemetry.track("document", url=file.filename) as handle:
            text, meta = await documents.process(
                data=raw, content_type=file.content_type, filename=file.filename
            )
            return await _document_result(
                text, meta, schema_dict, prompt, verify, repair, handle
            )
    except documents.DocumentTooLargeError as e:
        raise HTTPException(413, str(e)) from e
    except documents.DocumentError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Document processing failed: {e}") from e


@router.post("/crawl", response_model=CrawlJob, status_code=202)
async def crawl_endpoint(req: CrawlRequest):
    """Start an async crawl job. Runs in-process; poll /crawl/{id} for status."""
    job_id = uuid.uuid4().hex
    job = await jobstore.create(job_id, url=str(req.url))
    crawl_runner.start(job_id, req)
    return job


class PromptUpdate(BaseModel):
    template: str


@router.get("/prompts")
async def list_prompts_endpoint(agent: str | None = None):
    """All prompt versions (optionally for one agent)."""
    return {"prompts": await prompts.list_prompts(agent)}


@router.put("/prompts/{agent}/{name}")
async def set_prompt_endpoint(agent: str, name: str, body: PromptUpdate):
    """Publish the next version of an agent prompt and activate it."""
    return await prompts.set_prompt(agent, name, body.template)


@router.post("/prompts/{agent}/{name}/activate")
async def activate_prompt_endpoint(agent: str, name: str, version: int):
    """Roll (back) to an existing prompt version."""
    if not await prompts.activate(agent, name, version):
        raise HTTPException(404, "Prompt version not found")
    return {"agent": agent, "name": name, "version": version, "active": True}


@router.post("/events", status_code=202)
async def events_endpoint(batch: ClientEventBatch):
    """Client-side UX telemetry (INC-B11). Fire-and-forget: persistence
    problems are logged, never surfaced to the browser."""
    try:
        async with session_scope() as session:
            for event in batch.events:
                meta = dict(event.meta or {})
                if event.value is not None:
                    meta["value"] = event.value
                session.add(
                    TelemetryEvent(kind="ux", message=event.name, meta=meta or None)
                )
    except Exception:  # noqa: BLE001
        logger.warning("ux_events_persist_failed", exc_info=True)
    return {"accepted": len(batch.events)}


@router.get("/ux")
async def ux_endpoint(hours: int = 24):
    """Aggregated frontend usage signals + rule-based UX recommendations."""
    return await evaluator.ux_report(hours)


@router.get("/benchmarks")
async def benchmarks_endpoint(hours: int = 24):
    """Per-metric benchmark trends (avg/min/max/count) + recent scores."""
    return await benchmark_loop.summary(hours)


class ExperimentRequest(BaseModel):
    agent: str
    candidates: list[str] = Field(min_length=1, max_length=10)  # model aliases
    tasks: list[ExtractRequest] = Field(min_length=1, max_length=20)
    verify: bool = True
    promote: bool = False  # auto-promote a decisive winner


class PromoteRequest(BaseModel):
    agent: str
    model: str  # alias under models: in models.yaml


@router.post("/experiments/run")
async def run_experiment_endpoint(req: ExperimentRequest):
    """Trial candidate models for an agent over the same tasks (INC-B14)."""
    try:
        return await experiments.run_experiment(
            req.agent, req.candidates, req.tasks, verify=req.verify, promote=req.promote
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Experiment failed: {e}") from e


@router.get("/experiments/promotions")
async def list_promotions_endpoint():
    return {"promotions": await experiments.list_promotions()}


@router.post("/experiments/promote")
async def promote_endpoint(req: PromoteRequest):
    """Manually promote a model for an agent (applied when the flag is on)."""
    return await experiments.promote_model(req.agent, req.model)


@router.delete("/experiments/promotions/{agent}")
async def demote_endpoint(agent: str):
    if not await experiments.demote(agent):
        raise HTTPException(404, "No promotion recorded for that agent")
    return {"agent": agent, "removed": True}


@router.get("/knowledge")
async def knowledge_overview_endpoint():
    """Cross-domain knowledge: graph size, top domains, learned strategies."""
    return await knowledge.overview()


@router.get("/knowledge/{domain}")
async def knowledge_endpoint(domain: str):
    """What SiloLoop has learned about a domain: graph snapshot + agent memory."""
    snapshot = await knowledge.domain_snapshot(domain)
    snapshot["memory"] = await memory.domain_memory(domain)
    return snapshot


@router.get("/crawl/{job_id}", response_model=CrawlJob)
async def crawl_status(job_id: str):
    job = await jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
