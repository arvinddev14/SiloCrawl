"""OpenAI-compatible provider.

One provider covers every open-source model we care about: HuggingFace
Inference Endpoints (gpt-oss), vLLM, Ollama, and TGI all speak the OpenAI
Chat Completions API. Adding a new open model is therefore config-only.
"""
from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.llm.base import LLMResponse, ToolCall


class OpenAICompatProvider:
    def __init__(self, endpoint: str, api_key: str) -> None:
        # AsyncOpenAI requires a non-empty key; local vLLM/Ollama often need none.
        self._client = AsyncOpenAI(api_key=api_key or "-", base_url=endpoint)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        max_tokens: int | None = None,
        **extra: Any,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": model, "messages": messages, **extra}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        resp = await self._client.chat.completions.create(**kwargs)
        message = resp.choices[0].message
        tool_calls = [
            ToolCall(name=tc.function.name, arguments=tc.function.arguments)
            for tc in (message.tool_calls or [])
        ]
        usage = resp.usage.model_dump() if resp.usage else None
        return LLMResponse(text=message.content, tool_calls=tool_calls, usage=usage, raw=resp)
