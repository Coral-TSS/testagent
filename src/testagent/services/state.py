"""Table-driven state machines (spec §5.3). All status changes go through `transition`."""

from __future__ import annotations

from testagent.core.errors import AppError

MACHINES: dict[str, dict[str, set[str]]] = {
    "version": {
        "planning": {"requirements_frozen"},
        "requirements_frozen": {"planning", "testing", "closed"},
        "testing": {"closed"},
        "closed": set(),
    },
    "requirement": {
        "draft": {"structured"},
        "structured": {"confirmed", "draft"},
        "confirmed": {"structured"},
    },
    "strategy": {"draft": {"confirmed"}, "confirmed": {"draft"}},
    "task": {
        "draft": {"ready", "archived"},
        "ready": {"running", "draft", "archived"},
        "running": {"done", "cancelled", "ready"},
        "done": {"ready", "archived"},
        "cancelled": {"ready", "archived"},
        "archived": set(),
    },
    "case": {"draft": {"ready"}, "ready": {"deprecated", "draft"}, "deprecated": set()},
    "task_run": {
        "queued": {"running", "cancelled", "error"},
        "running": {"passed", "failed", "error", "cancelled", "not_executed"},
        "passed": set(),
        "not_executed": set(),
        "failed": set(),
        "error": set(),
        "cancelled": set(),
    },
    "case_execution": {
        "queued": {"running", "skipped", "error", "blocked"},
        "running": {"passed", "failed", "error", "blocked", "skipped"},
        "blocked": {"passed", "failed", "error", "skipped"},
        "passed": set(),
        "failed": set(),
        "error": set(),
        "skipped": set(),
    },
    "defect": {
        "open": {"in_progress", "resolved", "rejected"},
        "in_progress": {"resolved", "rejected", "open"},
        "resolved": {"closed", "open"},
        "closed": {"open"},
        "rejected": {"open"},
    },
}

# transitions that require a written reason
REASON_REQUIRED = {("version", "requirements_frozen", "planning")}


def allowed(machine: str, current: str) -> set[str]:
    try:
        return set(MACHINES[machine][current])
    except KeyError as exc:
        raise AppError("VALIDATION", f"Unknown state machine or state: {machine}/{current}") from exc


def transition(machine: str, current: str, target: str, *, reason: str | None = None) -> str:
    if target not in MACHINES.get(machine, {}):
        raise AppError("VALIDATION", f"Unknown target state: {machine}/{target}")
    if target not in allowed(machine, current):
        raise AppError("INVALID_TRANSITION", f"Cannot change from {current} to {target}")
    if (machine, current, target) in REASON_REQUIRED and not (reason and reason.strip()):
        raise AppError(
            "VALIDATION",
            "This state change requires a reason",
            field_errors=[{"field": "reason", "msg": "is required"}],
        )
    return target
