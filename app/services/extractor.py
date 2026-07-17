"""LLM-powered structured extraction.

Strategy: scrape the page to markdown, then ask the model — via the SiloLoop
Model Router (Agent -> Router -> Provider) — to populate the user's JSON Schema.
We use function calling to force valid JSON output (the schema becomes the
function's parameters), which is more reliable than parsing free-form text.

Two modes (INC-B5):

* **plain** (default) — one LLM call, content truncated at the limit. Exactly
  the legacy behavior.
* **deep** (``deep=True``, used by the SiloLoop EXTRACT stage) — long content is
  chunked on paragraph boundaries, extracted per chunk (map), merged field-wise
  (reduce), and any still-missing fields get one focused retry with a sub-schema
  of just those fields. Nothing beyond the limit is silently lost anymore.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import get_settings
from app.llm import get_router

# Direct submodule import: extractor is loaded during app.loop's own package
# init (via the orchestrator), so `from app.loop import prompts` would hit a
# partially initialized package.
from app.loop.prompts import get_prompt
from app.models.schemas import (
    ExtractRequest,
    ExtractResult,
    OutputFormat,
    ScrapeRequest,
)
from app.services import scraper

settings = get_settings()


class ExtractionParseError(ValueError):
    """The model's tool-call arguments were not valid JSON.

    Carries the raw model output so the Repair Loop (INC-B4) can salvage it
    instead of rerunning the whole extraction.
    """

    def __init__(self, raw: str, cause: Exception):
        super().__init__(f"model emitted invalid JSON: {cause}")
        self.raw = raw


SYSTEM = (
    "You are a precise data-extraction engine. Extract the requested fields "
    "from the supplied web content. Only use information present in the content. "
    "If a field cannot be found, use null. Never invent values."
)


async def get_content(req: ExtractRequest, *, escalate: bool = False) -> tuple[str, str | None]:
    """Resolve the raw content for an extract request (inline text or a scrape).

    Public so the verifier (INC-B3) can fetch once and share the same content
    between extraction and verification.
    """
    if req.content:
        return req.content, None
    if not req.url:
        raise ValueError("Either 'url' or 'content' must be provided.")
    scraped = await scraper.scrape(
        ScrapeRequest(
            url=req.url, formats=[OutputFormat.markdown], render_js=req.render_js
        ),
        escalate=escalate,
    )
    return (scraped.markdown or ""), scraped.metadata.source_url


# Used when the request supplies no schema: freeform "key facts" extraction
# guided entirely by the prompt.
FREEFORM_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": True}


def _chunks(content: str, limit: int, max_chunks: int) -> list[str]:
    """Split content into <=limit chunks on paragraph boundaries (capped)."""
    if len(content) <= limit:
        return [content]
    chunks: list[str] = []
    buf = ""
    for para in content.split("\n\n"):
        if len(para) > limit:  # a single oversized paragraph — hard split
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(para[i : i + limit] for i in range(0, len(para), limit))
            continue
        if len(buf) + len(para) + 2 > limit:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks[:max_chunks]


def _merge_chunk_data(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce step: first non-null wins per scalar field; lists union in order."""
    merged: dict[str, Any] = {}
    for data in results:
        for key, value in data.items():
            if isinstance(value, list):
                existing = merged.get(key)
                if isinstance(existing, list):
                    existing.extend(item for item in value if item not in existing)
                elif existing is None:
                    merged[key] = list(value)
            elif merged.get(key) is None:
                merged[key] = value
    return merged


def _missing_subschema(
    schema: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any] | None:
    """Schema covering only the properties still null/absent, or None if complete."""
    props = schema.get("properties") or {}
    missing = {name: spec for name, spec in props.items() if data.get(name) is None}
    if not missing:
        return None
    return {"type": "object", "properties": missing}


async def _single_pass(
    schema: dict[str, Any], instructions: str, content: str
) -> dict[str, Any]:
    """One extractor-agent call over one piece of content."""
    system = await get_prompt("extractor", "system", SYSTEM)
    tool = {
        "type": "function",
        "function": {
            "name": "emit_extracted_data",
            "description": "Return the extracted structured data.",
            "parameters": schema,
        },
    }
    response = await get_router().complete(
        "extractor",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"{instructions}\n\n--- WEB CONTENT ---\n{content}"},
        ],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "emit_extracted_data"}},
    )
    data: dict[str, Any] = {}
    if response.tool_calls:
        raw = response.tool_calls[0].arguments
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ExtractionParseError(raw, e) from e
    return data


async def extract(
    req: ExtractRequest,
    *,
    escalate: bool = False,
    content: str | None = None,
    source_url: str | None = None,
    deep: bool = False,
) -> ExtractResult:
    if content is None:
        content, source_url = await get_content(req, escalate=escalate)

    schema = req.json_schema or FREEFORM_SCHEMA
    instructions = req.prompt or "Extract the structured data defined by the schema."

    if not deep:  # legacy path: one call, truncate past the limit
        data = await _single_pass(
            schema, instructions, content[: settings.extract_content_limit]
        )
        return ExtractResult(data=data, source_url=source_url)

    # --- deep path: map -> reduce -> retry missing fields only ---
    chunks = _chunks(content, settings.extract_content_limit, settings.extract_max_chunks)
    sem = asyncio.Semaphore(settings.extract_chunk_concurrency)

    async def _mapped(chunk: str) -> dict[str, Any]:
        async with sem:
            return await _single_pass(schema, instructions, chunk)

    results = await asyncio.gather(*(_mapped(c) for c in chunks))
    data = _merge_chunk_data(list(results))
    llm_calls = len(chunks)

    retried_fields: list[str] = []
    filled_by_retry: list[str] = []
    sub = _missing_subschema(schema, data)
    if sub is not None:
        retried_fields = sorted(sub["properties"])
        retry_instructions = (
            f"{instructions}\n\nOnly these fields are still missing: "
            f"{', '.join(retried_fields)}. Extract only these fields."
        )
        for chunk in chunks:  # walk in order, stop as soon as everything fills
            partial = await _single_pass(sub, retry_instructions, chunk)
            llm_calls += 1
            for name, value in partial.items():
                if value is not None and data.get(name) is None:
                    data[name] = value
                    filled_by_retry.append(name)
            if all(data.get(name) is not None for name in retried_fields):
                break

    result = ExtractResult(data=data, source_url=source_url)
    result.extraction = {
        "chunks": len(chunks),
        "llm_calls": llm_calls,
        "retried_fields": retried_fields,
        "filled_by_retry": sorted(filled_by_retry),
    }
    return result
