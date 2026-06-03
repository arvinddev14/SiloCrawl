"""LLM-powered structured extraction.

Strategy: scrape the page to markdown, then ask the model to populate the
user's JSON Schema. We use OpenAI-compatible function calling to force valid
JSON output (the schema becomes the function's parameters), which is more
reliable than parsing free-form text.
"""
from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.models.schemas import (
    ExtractRequest,
    ExtractResult,
    OutputFormat,
    ScrapeRequest,
)
from app.services import scraper

settings = get_settings()

SYSTEM = (
    "You are a precise data-extraction engine. Extract the requested fields "
    "from the supplied web content. Only use information present in the content. "
    "If a field cannot be found, use null. Never invent values."
)


async def _get_content(req: ExtractRequest) -> tuple[str, str | None]:
    if req.content:
        return req.content, None
    if not req.url:
        raise ValueError("Either 'url' or 'content' must be provided.")
    scraped = await scraper.scrape(
        ScrapeRequest(
            url=req.url, formats=[OutputFormat.markdown], render_js=req.render_js
        )
    )
    return (scraped.markdown or ""), scraped.metadata.source_url


async def extract(req: ExtractRequest) -> ExtractResult:
    content, source_url = await _get_content(req)
    content = content[: settings.extract_content_limit]

    client = AsyncOpenAI(
        api_key=settings.hf_api_key,
        base_url=settings.hf_endpoint_url,
    )

    instructions = req.prompt or "Extract the structured data defined by the schema."
    tool = {
        "type": "function",
        "function": {
            "name": "emit_extracted_data",
            "description": "Return the extracted structured data.",
            "parameters": req.json_schema,
        },
    }

    response = await client.chat.completions.create(
        model=settings.extract_model,
        max_tokens=settings.extract_max_tokens,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"{instructions}\n\n--- WEB CONTENT ---\n{content}"},
        ],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "emit_extracted_data"}},
    )

    data: dict[str, Any] = {}
    tool_calls = response.choices[0].message.tool_calls
    if tool_calls:
        data = json.loads(tool_calls[0].function.arguments)

    return ExtractResult(data=data, source_url=source_url)
