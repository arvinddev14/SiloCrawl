"""Planner agent: turn a request + domain memory into an execution plan.

The deterministic core inspects the request (input type, schema presence,
content size) and the domain memory block (learned fetch strategy from INC-B2/
B6) and emits a plan dict that the orchestrator records in telemetry. One
capability uses the LLM (router agent ``planner`` — gpt-oss today, qwen3 later
by config): drafting a JSON Schema when the caller supplied a prompt but no
schema, so the whole extract/verify/repair pipeline gets typed structure
instead of freeform output.

The planner never overrides explicit user choices (verify/repair flags,
supplied schemas) and is best-effort end to end — a planning failure downgrades
gracefully, it never kills the run.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

from app.core.config import get_settings
from app.llm import get_router
from app.loop.prompts import get_prompt
from app.loop.state_machine import LoopState

logger = logging.getLogger("silocrawl")

SYSTEM = (
    "You design JSON Schemas for data extraction. Given a user's extraction "
    "request, return a compact JSON Schema (type object with properties) that "
    "captures exactly the fields the user asked for — nothing more. Use "
    "lowercase snake_case property names and only the types string, number, "
    "integer, boolean, or array."
)

_SCHEMA_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_schema",
        "description": "Return the designed JSON Schema for the extraction.",
        "parameters": {
            "type": "object",
            "properties": {
                "schema": {"type": "object", "description": "A JSON Schema object."}
            },
            "required": ["schema"],
        },
    },
}


def build_plan(
    request: Any, memory: dict[str, Any] | None, steps: tuple[LoopState, ...]
) -> dict[str, Any]:
    """Deterministic plan: input type, fetch prediction, cost estimates."""
    settings = get_settings()
    url = getattr(request, "url", None)
    content = getattr(request, "content", None)

    strategy_block = (memory or {}).get("strategy") or {}
    plan: dict[str, Any] = {
        "input_type": "url" if url else "content",
        "fetch": {
            "render_js": bool(getattr(request, "render_js", False)),
            # Informational: the escalation ladder (B2) acts on this at fetch
            # time; the planner just surfaces what it expects to happen.
            "predicted_strategy": strategy_block.get("strategy"),
        },
    }
    if LoopState.EXTRACT not in steps:
        return plan  # scrape pipeline: nothing to plan beyond the fetch

    schema = getattr(request, "json_schema", None)
    prompt = getattr(request, "prompt", None)
    if schema:
        source = "user"
    elif prompt:
        source = "generated"  # the orchestrator will attempt generation
    else:
        source = "freeform"

    limit = settings.extract_content_limit
    chunks: int | None = None
    if content:
        chunks = max(1, min(math.ceil(len(content) / limit), settings.extract_max_chunks))

    stage_calls = sum(1 for s in steps if s in (LoopState.VERIFY, LoopState.REPAIR))
    plan["extraction"] = {
        "mode": "deep",
        "schema_source": source,
        "estimated_chunks": chunks,
    }
    plan["estimated_llm_calls"] = (
        (chunks or 1) + stage_calls + (1 if source == "generated" else 0)
    )
    plan["estimated_tokens"] = (
        min(len(content), limit * (chunks or 1)) // 4 if content else None
    )
    return plan


async def generate_schema(prompt: str) -> dict[str, Any] | None:
    """Draft a JSON Schema from a freeform extraction prompt. None on failure."""
    try:
        system = await get_prompt("planner", "schema_system", SYSTEM)
        response = await get_router().complete(
            "planner",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Extraction request: {prompt}"},
            ],
            tools=[_SCHEMA_TOOL],
            tool_choice={"type": "function", "function": {"name": "emit_schema"}},
        )
        if not response.tool_calls:
            return None
        schema = json.loads(response.tool_calls[0].arguments).get("schema")
        if isinstance(schema, dict) and schema.get("properties"):
            schema.setdefault("type", "object")
            return schema
    except Exception:  # noqa: BLE001 - fall back to freeform, never fail the run
        logger.warning("schema_generation_failed", exc_info=True)
    return None
