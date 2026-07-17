"""Verification Loop: challenge an extraction before trusting it.

Two layers, cheap first:

1. Deterministic scoring (``app/loop/confidence.py``) — schema validity, field
   coverage, literal evidence in the source content. Always runs, costs nothing.
2. An LLM pass via the Model Router as agent ``verifier`` — the model is shown
   the content and the extracted data and must return a per-field verdict. The
   LLM layer is best-effort: if the call fails, the deterministic score stands
   alone rather than failing the request.

The combined report rides back on ``ExtractResult.confidence`` /
``ExtractResult.verification`` when the caller opts in with ``verify=true``.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel

from app.core.config import get_settings
from app.llm import get_router
from app.loop import confidence
from app.loop.prompts import get_prompt
from app.models.schemas import ExtractRequest, ExtractResult
from app.services import extractor

logger = logging.getLogger("silocrawl")

# Blend: deterministic signals dominate; the LLM adjudicates the remainder.
_W_DETERMINISTIC, _W_LLM = 0.7, 0.3

SYSTEM = (
    "You are a strict verification engine. For each extracted field, decide "
    "whether its value is supported by the supplied content. Answer "
    "'supported' if the content backs the value, 'unsupported' if the value "
    "contradicts or does not appear in the content, and 'not_found' if the "
    "field is null/empty. Judge only from the content; never assume."
)

_VERDICT_TOOL = {
    "type": "function",
    "function": {
        "name": "report_verification",
        "description": "Report a per-field verdict for the extracted data.",
        "parameters": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "verdict": {
                                "type": "string",
                                "enum": ["supported", "unsupported", "not_found"],
                            },
                        },
                        "required": ["name", "verdict"],
                    },
                }
            },
            "required": ["fields"],
        },
    },
}


class VerificationReport(BaseModel):
    confidence: float
    schema_valid: bool
    field_coverage: float
    evidence_score: float
    unsupported_fields: list[str] = []
    llm_checked: bool = False
    verdict: str  # pass | warn | fail


async def _llm_verdicts(
    data: dict[str, Any], content: str
) -> tuple[float, list[str]] | None:
    """Ask the verifier agent for per-field verdicts. None = no usable signal."""
    if not data:
        return None
    content = content[: get_settings().extract_content_limit]
    try:
        system = await get_prompt("verifier", "system", SYSTEM)
        response = await get_router().complete(
            "verifier",
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"--- EXTRACTED DATA ---\n{json.dumps(data, default=str)}\n\n"
                        f"--- CONTENT ---\n{content}"
                    ),
                },
            ],
            tools=[_VERDICT_TOOL],
            tool_choice={"type": "function", "function": {"name": "report_verification"}},
        )
        if not response.tool_calls:
            return None
        fields = json.loads(response.tool_calls[0].arguments).get("fields") or []
        if not fields:
            return None
        unsupported = [f["name"] for f in fields if f.get("verdict") == "unsupported"]
        score = 1.0 - len(unsupported) / len(fields)
        return score, unsupported
    except Exception:  # noqa: BLE001 - verification must not fail the request
        logger.warning("llm_verification_failed", exc_info=True)
        return None


def _verdict_label(score: float, unsupported: list[str]) -> str:
    if score >= 0.8 and not unsupported:
        return "pass"
    if score >= 0.5:
        return "warn"
    return "fail"


async def verify(
    schema: dict[str, Any] | None, data: dict[str, Any], content: str
) -> VerificationReport:
    """Score ``data`` against ``schema`` and ``content``; deterministic + LLM."""
    det = confidence.assess(data, schema or {}, content)

    llm = await _llm_verdicts(data, content)
    if llm is None:
        score = det.confidence
        unsupported = det.unsupported_fields
        llm_checked = False
    else:
        llm_score, llm_unsupported = llm
        score = round(_W_DETERMINISTIC * det.confidence + _W_LLM * llm_score, 4)
        unsupported = sorted(set(det.unsupported_fields) | set(llm_unsupported))
        llm_checked = True

    return VerificationReport(
        confidence=score,
        schema_valid=det.schema_valid,
        field_coverage=det.field_coverage,
        evidence_score=det.evidence_score,
        unsupported_fields=unsupported,
        llm_checked=llm_checked,
        verdict=_verdict_label(score, unsupported),
    )


async def extract_and_verify(
    req: ExtractRequest, *, escalate: bool = False
) -> ExtractResult:
    """Extract, then verify against the same content (fetched exactly once)."""
    content, source_url = await extractor.get_content(req, escalate=escalate)
    result = await extractor.extract(
        req, escalate=escalate, content=content, source_url=source_url
    )
    report = await verify(req.json_schema, result.data, content)
    result.confidence = report.confidence
    result.verification = report.model_dump()
    return result
