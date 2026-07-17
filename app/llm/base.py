"""Provider-agnostic LLM types.

Agents depend only on these dataclasses and the ``LLMProvider`` protocol —
never on a concrete provider SDK. This is what keeps the architecture
``Agent -> Router -> Provider`` with no leakage of provider details upward.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    """A single tool/function call returned by the model."""

    name: str
    arguments: str  # raw JSON string, exactly as the model emitted it


@dataclass
class LLMResponse:
    """Normalized response shape every provider returns."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    raw: Any = None  # original provider object; agents should not need this


@dataclass
class ModelSpec:
    """Resolved configuration for one model alias."""

    alias: str
    provider: str
    model: str
    endpoint: str
    api_key: str
    max_tokens: int = 4096
    params: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    """Every provider implements this. Providers may import their own SDKs;
    agents may not import providers."""

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        max_tokens: int | None = None,
        **extra: Any,
    ) -> LLMResponse: ...
