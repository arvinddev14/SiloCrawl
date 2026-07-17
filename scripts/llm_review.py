"""Run the SiloLoop LLM code review over a git diff.

Usage:
    git diff origin/main...HEAD | python scripts/llm_review.py
    python scripts/llm_review.py --base origin/main --out review.md

Needs HF_API_KEY / HF_ENDPOINT_URL in the environment (or .env) for the coder
agent. Prints the review markdown to stdout; --out also writes it to a file
(what CI posts as the PR comment).
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root import

from app.services.code_review import review_diff, to_markdown  # noqa: E402


def _diff_from_git(base: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def main() -> None:
    # Windows consoles default to cp1252, which can't print the emoji header.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", default=None,
        help="git ref to diff against (omit to read a diff from stdin)",
    )
    parser.add_argument("--out", default=None, help="also write markdown to this file")
    args = parser.parse_args()

    diff = _diff_from_git(args.base) if args.base else sys.stdin.read()
    findings = asyncio.run(review_diff(diff))
    markdown = to_markdown(findings)

    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
