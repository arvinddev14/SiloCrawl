"""Deterministic confidence scoring for extraction results — no LLM involved.

Three cheap signals, combined into a single ``confidence`` in [0, 1]:

* **schema validity** — does the data validate against the user's JSON Schema?
* **field coverage** — what fraction of the schema's properties came back non-null?
* **evidence** — what fraction of extracted leaf values literally appear in the
  source content? (the anti-hallucination check)

The LLM verification pass (``app/services/verifier.py``) layers on top of this;
these numbers are always computed first because they're free.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

import jsonschema

# Weighted sum: validity is the strongest signal, coverage/evidence split the rest.
_W_VALID, _W_COVERAGE, _W_EVIDENCE = 0.4, 0.3, 0.3

# Strings shorter than this are too generic to prove anything either way.
_MIN_EVIDENCE_LEN = 3


@dataclass
class DeterministicAssessment:
    schema_valid: bool
    field_coverage: float
    evidence_score: float
    unsupported_fields: list[str] = field(default_factory=list)
    confidence: float = 0.0


def _leaves(obj: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Yield (dotted-path, value) for every scalar leaf in the extracted data."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _leaves(value, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _leaves(value, f"{path}[{i}]")
    else:
        yield path, obj


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _supported(value: Any, content_norm: str) -> bool | None:
    """True/False if the value can be checked against the content, None if not."""
    if value is None or isinstance(value, bool):
        return None  # nulls and booleans carry no literal evidence
    if isinstance(value, (int, float)):
        return str(value) in content_norm or f"{value:,}" in content_norm
    if isinstance(value, str):
        needle = _normalize(value)
        if len(needle) < _MIN_EVIDENCE_LEN:
            return None
        return needle in content_norm
    return None


def evidence(data: dict[str, Any], content: str) -> tuple[float, list[str]]:
    """Fraction of checkable leaf values present in content + the missing paths."""
    content_norm = _normalize(content)
    checked = 0
    hits = 0
    missing: list[str] = []
    for path, value in _leaves(data):
        verdict = _supported(value, content_norm)
        if verdict is None:
            continue
        checked += 1
        if verdict:
            hits += 1
        else:
            missing.append(path)
    return (hits / checked if checked else 1.0), missing


def field_coverage(data: dict[str, Any], schema: dict[str, Any]) -> float:
    """Fraction of top-level schema properties that came back non-null."""
    props = schema.get("properties") or {}
    if not props:
        return 1.0 if data else 0.0
    filled = sum(1 for name in props if data.get(name) is not None)
    return filled / len(props)


def schema_valid(data: dict[str, Any], schema: dict[str, Any]) -> bool:
    try:
        jsonschema.validate(data, schema)
        return True
    except jsonschema.ValidationError:
        return False
    except jsonschema.SchemaError:
        return True  # a broken user schema shouldn't zero out the extraction


def assess(
    data: dict[str, Any], schema: dict[str, Any], content: str
) -> DeterministicAssessment:
    valid = schema_valid(data, schema)
    coverage = field_coverage(data, schema)
    ev_score, missing = evidence(data, content)
    score = _W_VALID * (1.0 if valid else 0.0) + _W_COVERAGE * coverage + _W_EVIDENCE * ev_score
    return DeterministicAssessment(
        schema_valid=valid,
        field_coverage=round(coverage, 4),
        evidence_score=round(ev_score, 4),
        unsupported_fields=missing,
        confidence=round(score, 4),
    )
