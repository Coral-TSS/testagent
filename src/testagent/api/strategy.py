"""/api/v1 strategy and tasks."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from testagent.services.strategy import StrategyService
from testagent.services.task_binding import TaskBindingService
from testagent.services.tasks import TaskService

router = APIRouter(prefix="/api/v1")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Tag = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyIn(_In):
    scope: str | None = None
    test_types: list[Tag] = Field(default_factory=list)
    intensity: Literal["light", "standard", "thorough"] | None = None
    notes: str | None = None


class Schedule(_In):
    type: Literal["once", "cron"]
    at: str | None = None
    expr: str | None = None
    tz: str | None = Field(default=None, max_length=64)


Kind = Literal["requirement", "quality", "regression"]


class Selector(_In):
    """Task case rule; every list is optional, values within a list are OR-ed and the
    lists are AND-ed. Only executable (ready) cases ever match."""

    requirement_ids: list[UUID] = Field(default_factory=list)
    categories: list[Literal["requirement", "quality", "regression"]] = Field(default_factory=list)
    type_tags: list[Tag] = Field(default_factory=list)
    scenarios: list[Literal["normal", "boundary", "exception"]] = Field(default_factory=list)
    priorities: list[Literal["P0", "P1", "P2"]] = Field(default_factory=list)
    quality_tags: list[Tag] = Field(default_factory=list)


class SelectorIn(_In):
    selector: Selector | None = None
    """None removes the rule: the task keeps only its current rows."""


class TaskIn(_In):
    name: Name
    kind: Kind = "requirement"
    executor: Literal["agent", "automation", "human"] = "agent"
    environment_id: UUID | None = None
    description: str | None = None
    schedule: Schedule | None = None
    case_ids: list[UUID] = Field(default_factory=list)
    selector: Selector | None = None


class TaskPatch(_In):
    name: Name | None = None
    kind: Kind | None = None
    executor: Literal["agent", "automation", "human"] | None = None
    environment_id: UUID | None = None
    description: str | None = None
    schedule: Schedule | None = None


class CasesIn(_In):
    case_ids: list[UUID]


class TaskStatusIn(_In):
    status: Literal["draft", "ready", "archived"]
    allow_missing_scripts: bool = False


def _strategy(r: Request) -> StrategyService:
    return StrategyService(r.app.state.db, r.app.state.bus)


def _tasks(r: Request) -> TaskService:
    return TaskService(r.app.state.db, r.app.state.bus, default_tz=r.app.state.timezone)


def _binding(r: Request) -> TaskBindingService:
    return TaskBindingService(r.app.state.db, r.app.state.bus)


def _selector(body: SelectorIn) -> dict | None:
    return body.selector.model_dump(mode="json") if body.selector is not None else None


def _dump(model: BaseModel, **kw) -> dict[str, Any]:
    data = model.model_dump(mode="json", **kw)
    if isinstance(data.get("schedule"), dict):
        data["schedule"] = {k: v for k, v in data["schedule"].items() if v is not None}
    return data


@router.get("/versions/{version_id}/strategy")
def get_strategy(request: Request, version_id: UUID):
    return _strategy(request).get(version_id)


@router.put("/versions/{version_id}/strategy")
def put_strategy(request: Request, version_id: UUID, body: StrategyIn):
    return _strategy(request).save(version_id, body.model_dump())


@router.post("/versions/{version_id}/strategy/generate")
def generate_strategy(request: Request, version_id: UUID):
    return _strategy(request).generate(version_id, request.app.state.agent.runtime)


@router.post("/strategy/{strategy_id}/confirm")
def confirm_strategy(request: Request, strategy_id: UUID):
    return _strategy(request).confirm(strategy_id)


@router.get("/versions/{version_id}/tasks")
def list_tasks(request: Request, version_id: UUID):
    return _tasks(request).list(version_id)


@router.post("/versions/{version_id}/tasks", status_code=201)
def create_task(request: Request, version_id: UUID, body: TaskIn):
    return _tasks(request).create(version_id, _dump(body))


@router.get("/tasks/{task_id}")
def get_task(request: Request, task_id: UUID):
    return _tasks(request).get(task_id)


@router.patch("/tasks/{task_id}")
def patch_task(request: Request, task_id: UUID, body: TaskPatch):
    return _tasks(request).update(task_id, _dump(body, exclude_unset=True))


@router.put("/tasks/{task_id}/cases")
def set_task_cases(request: Request, task_id: UUID, body: CasesIn):
    return _tasks(request).set_cases(task_id, body.case_ids)


@router.post("/tasks/{task_id}/status")
def set_task_status(request: Request, task_id: UUID, body: TaskStatusIn):
    return _tasks(request).set_status(task_id, body.status, allow_missing_scripts=body.allow_missing_scripts)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(request: Request, task_id: UUID):
    _tasks(request).delete(task_id)
    return Response(status_code=204)


@router.put("/tasks/{task_id}/selector")
def set_task_selector(request: Request, task_id: UUID, body: SelectorIn):
    return _binding(request).set_selector(task_id, _selector(body))


@router.post("/tasks/{task_id}/selector/preview")
def preview_task_selector(request: Request, task_id: UUID, body: SelectorIn):
    return _binding(request).preview(task_id, _selector(body))


@router.post("/tasks/{task_id}/sync")
def sync_task_cases(request: Request, task_id: UUID):
    return _binding(request).sync(task_id)


@router.delete("/tasks/{task_id}/exclusions/{case_id}")
def restore_task_case(request: Request, task_id: UUID, case_id: UUID):
    return _binding(request).restore(task_id, str(case_id))


@router.post("/versions/{version_id}/tasks/ensure")
def ensure_tasks(request: Request, version_id: UUID):
    """Add the missing requirement / quality / regression rule tasks without asking the model."""
    created = _binding(request).ensure_tasks(
        version_id, strategy_id=StrategyService.strategy_id(request.app.state.db, version_id)
    )
    return {"created": created}


@router.get("/versions/{version_id}/gaps")
def requirement_gaps(request: Request, version_id: UUID):
    return _binding(request).gaps(version_id)
