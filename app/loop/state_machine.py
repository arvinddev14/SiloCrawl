"""Explicit state machine for a single SiloLoop run.

The machine is deliberately tiny and data-only: it defines the legal states,
the legal transitions between them, and a :class:`LoopContext` that carries the
request plus whatever artifacts each stage produces. The orchestrator
(``app/loop/orchestrator.py``) is what actually advances the machine by calling
into the existing services; keeping the topology here makes the pipeline easy to
reason about and to extend (INC-B2+ insert new states without touching callers).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LoopState(str, Enum):
    """Stages a request moves through. ``DONE``/``ERROR`` are terminal."""

    PLAN = "plan"
    FETCH = "fetch"
    EXTRACT = "extract"
    VERIFY = "verify"
    REPAIR = "repair"
    DONE = "done"
    ERROR = "error"


# Legal forward transitions. Any state may also jump to ERROR (handled in code),
# so ERROR is intentionally omitted from the values here.
TRANSITIONS: dict[LoopState, tuple[LoopState, ...]] = {
    # PLAN may go straight to EXTRACT: the extractor scrapes internally, so the
    # extract pipeline skips the standalone FETCH stage.
    LoopState.PLAN: (LoopState.FETCH, LoopState.EXTRACT),
    LoopState.FETCH: (LoopState.EXTRACT, LoopState.DONE),
    LoopState.EXTRACT: (LoopState.VERIFY, LoopState.REPAIR, LoopState.DONE),
    LoopState.VERIFY: (LoopState.REPAIR, LoopState.DONE),
    # Re-verification after a repair happens inside the REPAIR handler — the
    # machine itself stays acyclic for now.
    LoopState.REPAIR: (LoopState.DONE,),
    LoopState.DONE: (),
    LoopState.ERROR: (),
}

TERMINAL_STATES = frozenset({LoopState.DONE, LoopState.ERROR})


def can_transition(src: LoopState, dst: LoopState) -> bool:
    """True if ``src -> dst`` is a legal move (ERROR is always reachable)."""
    return dst is LoopState.ERROR or dst in TRANSITIONS.get(src, ())


@dataclass
class LoopContext:
    """Mutable carrier threaded through the whole run.

    ``request`` is the original pydantic request model. Stages stash their
    outputs on the typed slots (``scrape_result`` / ``extract_result``) and may
    record arbitrary breadcrumbs in ``meta`` for telemetry. ``history`` is the
    ordered list of states visited, useful for tests and observability.
    """

    request: Any
    steps: tuple[LoopState, ...]
    state: LoopState = LoopState.PLAN
    history: list[LoopState] = field(default_factory=list)
    scrape_result: Any = None
    extract_result: Any = None
    content: str | None = None  # source content shared between EXTRACT and VERIFY
    run_id: str | None = None  # telemetry run id, set by the orchestrator
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def advance(self, dst: LoopState) -> None:
        """Move to ``dst``, validating the transition and logging history."""
        if not can_transition(self.state, dst):
            raise ValueError(f"illegal transition {self.state.value} -> {dst.value}")
        self.state = dst
        self.history.append(dst)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
