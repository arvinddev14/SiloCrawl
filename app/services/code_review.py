"""Code Improvement Loop: LLM review of a unified diff via the ``coder`` agent.

Deterministic CI (pytest/ruff/eslint/build) stays the merge gate; this review is
strictly advisory. The coder agent runs through the Model Router — gpt-oss-120b
today, DeepSeek-Coder later by editing ``models.yaml`` only. The system prompt
is versioned through the prompt store (INC-B7) and falls back to the constant in
DB-less environments like CI.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.llm import get_router
from app.loop.prompts import get_prompt

logger = logging.getLogger("silocrawl")

# Chars of diff per coder call; a diff bigger than this is reviewed in batches.
BATCH_CHAR_BUDGET = 60_000
# Hard cap on the rendered PR comment (GitHub cuts off around 65k).
MAX_COMMENT_CHARS = 60_000

SYSTEM = (
    "You are a rigorous senior code reviewer. Report only real problems in the "
    "diff: bugs, security issues, race conditions, broken error handling, "
    "resource leaks, or misleading behavior. Cite the file each finding is in. "
    "Do not praise, do not restate the diff, do not invent style nits. If the "
    "diff looks fine, return an empty findings list."
)

_REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "report_findings",
        "description": "Report the code review findings for the diff.",
        "parameters": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "severity": {
                                "type": "string",
                                "enum": ["bug", "risk", "style"],
                            },
                            "comment": {"type": "string"},
                        },
                        "required": ["file", "severity", "comment"],
                    },
                }
            },
            "required": ["findings"],
        },
    },
}

_SKIP_DIRS = ("node_modules/", "dist/", "build/", ".next/", "vendor/", "__pycache__/")
_SKIP_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
}
_SKIP_SUFFIXES = (
    ".min.js", ".map", ".lock", ".svg", ".png", ".jpg", ".jpeg",
    ".webp", ".gif", ".ico", ".pdf", ".woff", ".woff2",
)


def _skip(path: str) -> bool:
    lowered = path.lower()
    if any(part in lowered for part in _SKIP_DIRS):
        return True
    name = lowered.rsplit("/", 1)[-1]
    return name in _SKIP_NAMES or name.endswith(_SKIP_SUFFIXES)


def split_diff(diff: str) -> list[tuple[str, str]]:
    """Split a unified git diff into (path, file_diff) pairs, noise removed."""
    files: list[tuple[str, str]] = []
    path: str | None = None
    lines: list[str] = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if path is not None:
                files.append((path, "".join(lines)))
            last = line.split()[-1]
            path = last[2:] if last.startswith("b/") else last
            lines = [line]
        elif path is not None:
            lines.append(line)
    if path is not None:
        files.append((path, "".join(lines)))
    return [(p, d) for p, d in files if not _skip(p)]


def _batches(
    files: list[tuple[str, str]], budget: int = BATCH_CHAR_BUDGET
) -> list[list[tuple[str, str]]]:
    """Group files so each coder call stays under the character budget."""
    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for path, file_diff in files:
        file_diff = file_diff[:budget]  # one enormous file still fits one call
        if current and size + len(file_diff) > budget:
            batches.append(current)
            current, size = [], 0
        current.append((path, file_diff))
        size += len(file_diff)
    if current:
        batches.append(current)
    return batches


async def review_diff(diff: str) -> list[dict[str, Any]]:
    """Review a unified diff; returns [{file, severity, comment}]. Best-effort."""
    files = split_diff(diff)
    if not files:
        return []

    system = await get_prompt("coder", "review_system", SYSTEM)
    findings: list[dict[str, Any]] = []
    for batch in _batches(files):
        text = "\n".join(file_diff for _, file_diff in batch)
        try:
            response = await get_router().complete(
                "coder",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Review this diff:\n\n{text}"},
                ],
                tools=[_REVIEW_TOOL],
                tool_choice={"type": "function", "function": {"name": "report_findings"}},
            )
            if not response.tool_calls:
                continue
            raw = json.loads(response.tool_calls[0].arguments).get("findings") or []
            for item in raw:
                if isinstance(item, dict) and item.get("file") and item.get("comment"):
                    findings.append(
                        {
                            "file": str(item["file"]),
                            "severity": str(item.get("severity") or "risk"),
                            "comment": str(item["comment"]),
                        }
                    )
        except Exception:  # noqa: BLE001 - advisory review must never fail CI
            logger.warning("code_review_batch_failed", exc_info=True)
    return findings


_SEVERITY_EMOJI = {"bug": "\U0001f41e", "risk": "⚠️", "style": "✨"}


def to_markdown(findings: list[dict[str, Any]]) -> str:
    """Render findings as the PR comment body (stable heading = sticky comment)."""
    lines = ["## \U0001f916 SiloLoop code review", ""]
    if not findings:
        lines.append("No findings — the diff looks clean.")
    else:
        for path in sorted({f["file"] for f in findings}):
            lines.append(f"### `{path}`")
            for f in (x for x in findings if x["file"] == path):
                emoji = _SEVERITY_EMOJI.get(f["severity"], "⚠️")
                lines.append(f"- {emoji} **{f['severity']}** — {f['comment']}")
            lines.append("")
    lines.append("")
    lines.append(
        "_Advisory review by the `coder` agent via the Model Router. "
        "Deterministic CI remains the merge gate._"
    )
    return "\n".join(lines)[:MAX_COMMENT_CHARS]
