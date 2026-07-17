"""Per-call model overrides via contextvars — the experiment plumbing (INC-B14).

``use_models({"extractor": "llama-3.3"})`` routes the named agents to specific
model aliases for everything awaited inside the context, without touching
config or call sites. The router consults this after an explicit ``model=``
kwarg and before promotions/config.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_active: ContextVar[dict[str, str]] = ContextVar("model_overrides", default={})


def current_override(agent: str) -> str | None:
    return _active.get().get(agent)


@contextmanager
def use_models(mapping: dict[str, str]) -> Iterator[None]:
    """Route the given agents to specific model aliases within this context."""
    token = _active.set({**_active.get(), **mapping})
    try:
        yield
    finally:
        _active.reset(token)
