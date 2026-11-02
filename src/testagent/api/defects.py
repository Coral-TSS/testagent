"""/api/v1 defects (M1-10)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from testagent.services.defects import DefectService
from testagent.services.failure_analysis import FailureAnalysisService

router = APIRouter(prefix="/api/v1")
Severity = Literal["critical", "major", "minor", "trivial"]
Cause = Literal["requirement", "design", "development", "test", "environment", "unknown"]
Status = Literal["open", "in_progress", "resolved", "closed", "rejected"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DefectIn(_In):
    sut_id: UUID
    version_id: UUID | None = None
    title: Title
    description: str | None = None
    severity: Severity = "major"
    cause_category: Cause = "unknown"
    requirement_ids: list[UUID] = Field(default_factory=list)


class FromExecutionIn(_In):
    title: Title | None = None
    description: str | None = None
    severity: Severity | None = None
    cause_category: Cause | None = None
    requirement_ids: list[UUID] | None = None


class DefectPatch(_In):
    title: Title | None = None
    description: str | None = None
    severity: Severity | None = None
    cause_category: Cause | None = None


class StatusIn(_In):
    status: Status


class RequirementsIn(_In):
    requirement_ids: list[UUID]


class ResponsibleIn(_In):
    person_id: UUID
    role: Literal["owner", "developer", "tester"]


def defects(request: Request) -> DefectService:
    return DefectService(request.app.state.db, request.app.state.bus)


@router.get("/defects")
def list_defects(
    request: Request,
    sut_id: UUID | None = None,
    version_id: UUID | None = None,
    status: Status | None = None,
    severity: Severity | None = None,
    cause_category: Cause | None = None,
    requirement_id: UUID | None = None,
    person_id: UUID | None = None,
    case_id: UUID | None = None,
    execution_id: UUID | None = None,
    created_by: Literal["human", "agent"] | None = None,
    q: str | None = None,
):
    return defects(request).list(
        {
            "sut_id": sut_id,
            "version_id": version_id,
            "status": status,
            "severity": severity,
            "cause_category": cause_category,
            "requirement_id": requirement_id,
            "person_id": person_id,
            "case_id": case_id,
            "execution_id": execution_id,
            "created_by": created_by,
            "q": q,
        }
    )


@router.post("/defects", status_code=201)
def create_defect(request: Request, body: DefectIn):
    data = body.model_dump(mode="json")
    return defects(request).create(data)


@router.get("/defects/{defect_id}")
def get_defect(request: Request, defect_id: UUID):
    return defects(request).get(defect_id)


@router.patch("/defects/{defect_id}")
def patch_defect(request: Request, defect_id: UUID, body: DefectPatch):
    return defects(request).update(defect_id, body.model_dump(exclude_unset=True, mode="json"))


@router.post("/defects/{defect_id}/status")
def defect_status(request: Request, defect_id: UUID, body: StatusIn):
    return defects(request).set_status(defect_id, body.status)


@router.put("/defects/{defect_id}/requirements")
def defect_requirements(request: Request, defect_id: UUID, body: RequirementsIn):
    return defects(request).set_requirements(defect_id, body.requirement_ids)


@router.put("/defects/{defect_id}/responsible")
def defect_responsible(request: Request, defect_id: UUID, body: list[ResponsibleIn]):
    return defects(request).set_responsible(defect_id, [e.model_dump() for e in body])


@router.post("/defects/{defect_id}/infer-responsible")
def infer_responsible(request: Request, defect_id: UUID):
    return defects(request).infer_responsible(defect_id)


@router.post("/defects/{defect_id}/accept-suggestion")
def accept_suggestion(request: Request, defect_id: UUID):
    return defects(request).accept_suggestion(defect_id)


@router.post("/executions/{execution_id}/defect", status_code=201)
def defect_from_execution(request: Request, execution_id: UUID, body: FromExecutionIn):
    data = body.model_dump(exclude_none=True, mode="json")
    return defects(request).create_from_execution(execution_id, data)


@router.post("/executions/{execution_id}/analyze")
def analyze_execution(request: Request, execution_id: UUID):
    s = request.app.state
    return FailureAnalysisService(s.db, s.bus, s.agent.runtime).analyze(execution_id)
