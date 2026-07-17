"""Repair Loop: fix broken extractions without a full rerun.

Three repair classes, cheapest first:

1. **Malformed JSON** — the model emitted broken tool arguments. Deterministic
   salvage first (markdown fences, trailing commas, outermost-object slice);
   only if that fails, one LLM call to the ``repair`` agent.
2. **Schema violations + missing fields** (and values flagged ``unsupported``
   by verification) — one *targeted* LLM repair call that receives an explicit
   problem list, then a conservative merge: repaired values are taken only for
   the problem fields, everything already good keeps its original value.
3. **Clean extraction** — repair is a no-op; the repair agent is never called.

All LLM traffic goes through the Model Router as agent ``repair`` (gpt-oss-120b
today; swappable in ``models.yaml`` with no code change).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import jsonschema

from app.core.config import get_settings
from app.llm import get_router
from app.loop.prompts import get_prompt
from app.models.schemas import ExtractRequest, ExtractResult
from app.services import extractor, verifier
from app.services.extractor import ExtractionParseError

logger = logging.getLogger("silocrawl")

# Single targeted pass for now; the Benchmark loop (INC-B10) can tune this.
MAX_REPAIR_ROUNDS = 1

SYSTEM_JSON = (
    "You repair malformed JSON. Return the same data as valid JSON matching "
    "the schema. Fix syntax only — never change, add, or drop values."
)

SYSTEM_DATA = (
    "You are a data-repair engine. You receive extracted data, a list of "
    "problems, and the source content. Fix ONLY the listed problems using "
    "information from the content. Keep every other value exactly as it is. "
    "If the content does not contain a missing value, use null. Never invent."
)


def _repair_tool(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_repaired_data",
            "description": "Return the repaired structured data.",
            "parameters": schema,
        },
    }


_FORCE_REPAIR = {"type": "function", "function": {"name": "emit_repaired_data"}}


# ---------- 1. malformed JSON ----------

def salvage_json(raw: str) -> dict[str, Any] | None:
    """Deterministic JSON cleanup: fences, trailing commas, outer-object slice."""
    candidates: list[str] = []
    s = raw.strip()
    candidates.append(s)
    fenceless = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    candidates.append(fenceless)
    if "{" in fenceless and "}" in fenceless:
        candidates.append(fenceless[fenceless.index("{"): fenceless.rindex("}") + 1])
    # retry every candidate with trailing commas removed
    candidates += [re.sub(r",\s*([}\]])", r"\1", c) for c in list(candidates)]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


async def repair_json(raw: str, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """Salvage broken JSON; returns ``(data, used_llm)``. Deterministic first."""
    data = salvage_json(raw)
    if data is not None:
        return data, False
    try:
        system = await get_prompt("repair", "json_system", SYSTEM_JSON)
        response = await get_router().complete(
            "repair",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"--- BROKEN JSON ---\n{raw}"},
            ],
            tools=[_repair_tool(schema)],
            tool_choice=_FORCE_REPAIR,
        )
        if response.tool_calls:
            return salvage_json(response.tool_calls[0].arguments), True
    except Exception:  # noqa: BLE001 - repair is best-effort
        logger.warning("json_repair_failed", exc_info=True)
    return None, True


# ---------- 2. schema violations / missing fields ----------

def find_problems(
    data: dict[str, Any],
    schema: dict[str, Any],
    unsupported: list[str] | None = None,
) -> list[str]:
    """Human-readable problem list the repair agent is asked to fix."""
    problems: list[str] = []
    try:
        validator = jsonschema.Draft202012Validator(schema)
        for err in validator.iter_errors(data):
            path = ".".join(str(p) for p in err.path) or "(root)"
            problems.append(f"schema violation at {path}: {err.message}")
    except jsonschema.SchemaError:
        pass  # a broken user schema is not the extraction's fault
    for name in schema.get("properties") or {}:
        if data.get(name) is None:
            problems.append(f"missing field: {name}")
    for name in unsupported or []:
        problems.append(f"unsupported value (not backed by content): {name}")
    return problems


def _problem_fields(
    data: dict[str, Any],
    schema: dict[str, Any],
    unsupported: list[str] | None = None,
) -> set[str]:
    """Top-level field names the merge is allowed to overwrite."""
    fields: set[str] = set()
    try:
        validator = jsonschema.Draft202012Validator(schema)
        for err in validator.iter_errors(data):
            if err.path:
                fields.add(str(err.path[0]))
    except jsonschema.SchemaError:
        pass
    for name in schema.get("properties") or {}:
        if data.get(name) is None:
            fields.add(name)
    for name in unsupported or []:
        fields.add(re.split(r"[.\[]", name, maxsplit=1)[0])
    return fields


def merge(
    original: dict[str, Any], repaired: dict[str, Any], problem_fields: set[str]
) -> tuple[dict[str, Any], list[str]]:
    """Take repaired values only for problem fields; keep good fields as-is."""
    out = dict(original)
    changed: list[str] = []
    for name in problem_fields:
        new = repaired.get(name)
        if new is not None and new != original.get(name):
            out[name] = new
            changed.append(name)
    return out, sorted(changed)


async def repair_data(
    data: dict[str, Any],
    schema: dict[str, Any],
    content: str,
    problems: list[str],
) -> dict[str, Any] | None:
    """One targeted repair call. Returns the agent's full candidate or None."""
    content = content[: get_settings().extract_content_limit]
    problem_list = "\n".join(f"- {p}" for p in problems)
    try:
        system = await get_prompt("repair", "data_system", SYSTEM_DATA)
        response = await get_router().complete(
            "repair",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"--- PROBLEMS ---\n{problem_list}\n\n"
                        f"--- CURRENT DATA ---\n{json.dumps(data, default=str)}\n\n"
                        f"--- CONTENT ---\n{content}"
                    ),
                },
            ],
            tools=[_repair_tool(schema)],
            tool_choice=_FORCE_REPAIR,
        )
        if response.tool_calls:
            return salvage_json(response.tool_calls[0].arguments)
    except Exception:  # noqa: BLE001 - repair is best-effort
        logger.warning("data_repair_failed", exc_info=True)
    return None


async def repair_result(
    data: dict[str, Any],
    schema: dict[str, Any] | None,
    content: str,
    unsupported: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Core repair pass shared by the route and the loop's REPAIR stage.

    Returns ``(possibly-repaired data, repair info dict)``. No problems means
    no LLM call at all.
    """
    schema = schema or {}
    info: dict[str, Any] = {
        "attempted": False,
        "parse_repaired": False,
        "problems": [],
        "repaired_fields": [],
        "success": True,
    }
    problems = find_problems(data, schema, unsupported)
    if not problems:
        return data, info

    info["attempted"] = True
    info["problems"] = problems
    candidate = await repair_data(data, schema, content, problems)
    if candidate is None:
        info["success"] = False
        return data, info

    fields = _problem_fields(data, schema, unsupported)
    merged, changed = merge(data, candidate, fields)
    info["repaired_fields"] = changed
    return merged, info


# ---------- orchestration for the plain (non-loop) route ----------

async def extract_and_repair(
    req: ExtractRequest, *, escalate: bool = False, verify: bool = False
) -> ExtractResult:
    """Extract, repair what's broken, optionally (re-)verify — one fetch total."""
    content, source_url = await extractor.get_content(req, escalate=escalate)
    parse_repaired = False
    try:
        result = await extractor.extract(
            req, escalate=escalate, content=content, source_url=source_url
        )
    except ExtractionParseError as e:
        data, _ = await repair_json(e.raw, req.json_schema or {})
        if data is None:
            raise  # unsalvageable — surface exactly like the plain path
        result = ExtractResult(data=data, source_url=source_url)
        parse_repaired = True

    report = None
    if verify:  # verification findings feed the problem list
        report = await verifier.verify(req.json_schema, result.data, content)

    unsupported = report.unsupported_fields if report else None
    result.data, info = await repair_result(
        result.data, req.json_schema, content, unsupported
    )
    if parse_repaired:
        info["attempted"] = True
        info["parse_repaired"] = True

    if verify:
        if info["repaired_fields"]:  # re-score so confidence reflects the fix
            report = await verifier.verify(req.json_schema, result.data, content)
        result.confidence = report.confidence
        result.verification = report.model_dump()

    result.repair = info
    return result
