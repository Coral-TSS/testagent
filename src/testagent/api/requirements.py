"""/api/v1 versions, requirements (people, structure, confirm), model suggestions."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from testagent.services.ai_tasks import AiTaskService
from testagent.services.requirements import RequirementService
from testagent.services.suggestions import SuggestionService
from testagent.services.versions import VersionService

router = APIRouter(prefix="/api/v1")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Priority = Literal["P0", "P1", "P2"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionIn(_In):
    name: Name


class UnfreezeIn(_In):
    reason: str | None = None


class StatusIn(_In):
    status: Literal["testing", "closed"]


class RequirementIn(_In):
    title: Name
    raw_text: str | None = None
    priority: Priority = "P1"
    code: Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")] | None = None


class RequirementPatch(_In):
    title: Name | None = None
    raw_text: str | None = None
    priority: Priority | None = None


class PersonRole(_In):
    person_id: UUID
    role: Literal["owner", "developer", "tester"]


class StructItemIn(_In):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    node_id: UUID | None = None
    attribute_id: UUID | None = None
    link_id: UUID | None = None


class StructureIn(_In):
    actor: list[StructItemIn] = Field(default_factory=list)
    condition: list[StructItemIn] = Field(default_factory=list)
    action: list[StructItemIn] = Field(default_factory=list)
    result: list[StructItemIn] = Field(default_factory=list)
    constraint: list[StructItemIn] = Field(default_factory=list)


class CompleteIn(_In):
    version_id: UUID | None = None


class AcceptIn(_In):
    name: Name | None = None
    module_id: UUID | None = None
    # link suggestions: the person may rename the two sides / change the cardinality
    forward_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    reverse_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    forward_api_name: str | None = Field(default=None, max_length=100)
    reverse_api_name: str | None = Field(default=None, max_length=100)
    cardinality: Literal["one_to_one", "many_to_one", "one_to_many", "many_to_many"] | None = None


class RejectIn(_In):
    reason: str | None = None


def _versions(r: Request) -> VersionService:
    return VersionService(r.app.state.db, r.app.state.bus)


def _reqs(r: Request) -> RequirementService:
    return RequirementService(r.app.state.db, r.app.state.bus)


def _ai(r: Request) -> AiTaskService:
    return AiTaskService(r.app.state.db, r.app.state.bus, r.app.state.agent.runtime)


# ---- versions
@router.get("/suts/{sut_id}/versions")
def list_versions(request: Request, sut_id: UUID):
    return _versions(request).list(sut_id)


@router.post("/suts/{sut_id}/versions", status_code=201)
def create_version(request: Request, sut_id: UUID, body: VersionIn):
    return _versions(request).create(sut_id, body.name)


@router.get("/versions/{version_id}")
def get_version(request: Request, version_id: UUID):
    return _versions(request).get(version_id)


@router.patch("/versions/{version_id}")
def rename_version(request: Request, version_id: UUID, body: VersionIn):
    return _versions(request).rename(version_id, body.name)


@router.get("/versions/{version_id}/history")
def version_history(request: Request, version_id: UUID):
    return _versions(request).history(version_id)


@router.post("/versions/{version_id}/freeze")
def freeze_version(request: Request, version_id: UUID):
    return _versions(request).freeze(version_id)


@router.post("/versions/{version_id}/unfreeze")
def unfreeze_version(request: Request, version_id: UUID, body: UnfreezeIn):
    return _versions(request).unfreeze(version_id, body.reason)


@router.post("/versions/{version_id}/status")
def set_version_status(request: Request, version_id: UUID, body: StatusIn):
    return _versions(request).set_status(version_id, body.status)


# ---- requirements
@router.get("/versions/{version_id}/requirements")
def list_requirements(request: Request, version_id: UUID):
    return _reqs(request).list(version_id)


@router.post("/versions/{version_id}/requirements", status_code=201)
def create_requirement(request: Request, version_id: UUID, body: RequirementIn):
    return _reqs(request).create(version_id, body.model_dump(exclude_none=True))


@router.get("/requirements/{req_id}")
def get_requirement(request: Request, req_id: UUID):
    return _reqs(request).detail(req_id)


@router.patch("/requirements/{req_id}")
def patch_requirement(request: Request, req_id: UUID, body: RequirementPatch):
    return _reqs(request).update(req_id, body.model_dump(exclude_unset=True))


@router.delete("/requirements/{req_id}", status_code=204)
def delete_requirement(request: Request, req_id: UUID):
    _reqs(request).delete(req_id)
    return Response(status_code=204)


@router.put("/requirements/{req_id}/people")
def set_requirement_people(request: Request, req_id: UUID, body: list[PersonRole]):
    return _reqs(request).set_people(req_id, [p.model_dump() for p in body])


@router.put("/requirements/{req_id}/structure")
def set_structure(request: Request, req_id: UUID, body: StructureIn):
    return _reqs(request).set_structure(req_id, body.model_dump(mode="json"))


@router.post("/requirements/{req_id}/structure")
def structure_with_agent(request: Request, req_id: UUID):
    return _ai(request).structure_requirement(req_id)


@router.post("/requirements/{req_id}/confirm")
def confirm_requirement(request: Request, req_id: UUID):
    return _reqs(request).confirm(req_id)


@router.get("/persons/{person_id}/requirements")
def person_requirements(request: Request, person_id: UUID):
    return _reqs(request).person_requirements(person_id)


# ---- model completion suggestions
@router.post("/suts/{sut_id}/model/complete")
def complete_model(request: Request, sut_id: UUID, body: CompleteIn):
    return _ai(request).complete_model(sut_id, body.version_id)


@router.get("/suts/{sut_id}/suggestions")
def list_suggestions(request: Request, sut_id: UUID, status: Literal["pending", "accepted", "rejected"] | None = None):
    return SuggestionService(request.app.state.db, request.app.state.bus).list(sut_id, status)


@router.post("/suggestions/{sugg_id}/accept")
def accept_suggestion(request: Request, sugg_id: UUID, body: AcceptIn):
    service = SuggestionService(request.app.state.db, request.app.state.bus)
    return service.accept(sugg_id, body.model_dump(exclude_none=True))


@router.post("/suggestions/{sugg_id}/reject")
def reject_suggestion(request: Request, sugg_id: UUID, body: RejectIn):
    return SuggestionService(request.app.state.db, request.app.state.bus).reject(sugg_id, body.reason)
