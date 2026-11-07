"""/api/v1 statistics, severity weights and reports (M1-11)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from testagent.services.reports import ReportService
from testagent.services.stats import DEFAULT_WEIGHTS, StatsService

router = APIRouter(prefix="/api/v1")


class WeightsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    critical: float = Field(ge=0, le=1000)
    major: float = Field(ge=0, le=1000)
    minor: float = Field(ge=0, le=1000)
    trivial: float = Field(ge=0, le=1000)


def reports(request: Request) -> ReportService:
    s = request.app.state
    return ReportService(s.db, s.bus, s.agent.runtime)


@router.get("/stats/people")
def people_stats(
    request: Request,
    version_id: UUID | None = None,
    sut_id: UUID | None = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    sort: Literal["attributed_score", "attributed_count", "related_count"] = "attributed_score",
):
    return StatsService(request.app.state.db).people(
        version_id=version_id, sut_id=sut_id, date_from=date_from, date_to=date_to, sort=sort
    )


@router.get("/stats/requirements")
def requirement_stats(
    request: Request,
    version_id: UUID | None = None,
    sut_id: UUID | None = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
):
    return StatsService(request.app.state.db).requirements(
        version_id=version_id, sut_id=sut_id, date_from=date_from, date_to=date_to
    )


@router.get("/settings/severity-weights")
def get_weights(request: Request):
    return StatsService(request.app.state.db).weights()


@router.get("/settings/severity-weights/defaults")
def default_weights():
    return DEFAULT_WEIGHTS


@router.put("/settings/severity-weights")
def put_weights(request: Request, body: WeightsIn):
    return StatsService(request.app.state.db).set_weights(body.model_dump())


@router.get("/reports")
def list_reports(
    request: Request,
    scope_type: Literal["task_run", "version"] | None = None,
    scope_id: UUID | None = None,
    version_id: UUID | None = None,
    sut_id: UUID | None = None,
):
    return reports(request).list(scope_type, scope_id, version_id, sut_id=sut_id)


@router.get("/reports/{report_id}")
def get_report(request: Request, report_id: UUID):
    return reports(request).get(report_id)


@router.post("/versions/{version_id}/report", status_code=201)
def version_report(request: Request, version_id: UUID):
    return reports(request).for_version(version_id)


@router.post("/runs/{run_id}/report", status_code=201)
def run_report(request: Request, run_id: UUID):
    return reports(request).for_run(run_id)
