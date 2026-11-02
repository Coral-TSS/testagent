"""/api/v1/jobs."""

from __future__ import annotations

from fastapi import APIRouter, Request

from testagent.core.jobs import JobQueue

router = APIRouter(prefix="/api/v1")


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: int):
    return JobQueue(request.app.state.db).get(job_id)
