"""C01: some decisions are human-only. Agents never reach these service methods through tools,
and the services refuse an `agent` actor as a second line of defence."""

from __future__ import annotations

from testagent.core.errors import AppError

AGENT_ACTOR = "agent"


def ensure_human(actor: str, action: str) -> None:
    if actor == AGENT_ACTOR or actor.startswith("agent:"):
        raise AppError("VALIDATION", f"“{action}” can only be done by a person")
