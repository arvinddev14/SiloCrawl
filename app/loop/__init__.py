"""SiloLoop — the adaptive orchestration layer over the SiloCrawl engine.

SiloCrawl (``app/services``) stays the deterministic execution engine. SiloLoop
sits on top: a state machine that drives a request through explicit stages
(plan -> fetch/clean -> extract -> done), delegating the actual work to the
existing services. Everything here is opt-in — a request only enters the loop
when a caller passes ``loop=true``; the plain endpoints are untouched.

Later increments grow the loop with retries/escalation (INC-B2), verification
(INC-B3), repair (INC-B4) and map-reduce extraction (INC-B5). INC-B1 lays down
the skeleton and the ``loop=true`` wiring only.
"""
from app.loop.orchestrator import run
from app.loop.state_machine import LoopContext, LoopState

__all__ = ["run", "LoopContext", "LoopState"]
