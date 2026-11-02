"""/api/v1 executions (M1-08): debug, manual results, automation, test repo, artifacts."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from testagent.core.errors import AppError
from testagent.integrations.git_repo import TestRepo
from testagent.services.automation import AutomationService
from testagent.services.executions import ExecutionService

router = APIRouter(prefix="/api/v1")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DebugIn(_In):
    environment_id: UUID
    executor: Literal["auto", "agent_browser", "agent_api", "pytest"] = "auto"


class Attachment(_In):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    content_base64: str


class ManualIn(_In):
    status: Literal["passed", "failed", "blocked", "skipped"]
    result: str | None = None
    failed_assertion: str | None = None
    actual_data: dict[str, Any] | None = None
    environment_id: UUID | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    blocked_reason: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)


class CompleteIn(_In):
    status: Literal["passed", "failed", "skipped", "error"]
    result: str | None = None
    failed_assertion: str | None = None
    actual_data: dict[str, Any] | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    attachments: list[Attachment] = Field(default_factory=list)


class AutomateIn(_In):
    environment_id: UUID | None = None


class BatchAutomateIn(_In):
    environment_id: UUID | None = None
    case_ids: list[UUID] | None = None
    include_drafts: bool = False


class BindIn(_In):
    code_path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def execution_service(state, actor: str = "local-user") -> ExecutionService:
    return ExecutionService(
        state.db,
        state.bus,
        runtime=state.agent.runtime,
        artifacts=state.artifacts,
        repos_root=state.repos_root,
        headless=state.browser_headless,
        pytest_timeout_s=state.pytest_timeout_s,
        actor=actor,
        runners=state.executor_runners,
    )


def executions(r: Request) -> ExecutionService:
    return execution_service(r.app.state)


def _automation(r: Request) -> AutomationService:
    s = r.app.state
    return AutomationService(s.db, s.bus, s.agent.runtime, s.repos_root, pytest_timeout_s=s.pytest_timeout_s)


@router.post("/cases/{case_id}/debug")
def debug_case(request: Request, case_id: UUID, body: DebugIn):
    return executions(request).debug(case_id, body.environment_id, body.executor)


@router.post("/cases/{case_id}/executions/manual", status_code=201)
def manual_execution(request: Request, case_id: UUID, body: ManualIn):
    return executions(request).record_manual(case_id, body.model_dump(mode="json"))


@router.get("/cases/{case_id}/executions")
def case_executions(request: Request, case_id: UUID):
    return executions(request).list_for_case(case_id)


@router.get("/executions/{execution_id}")
def get_execution(request: Request, execution_id: UUID):
    from testagent.services.defects import DefectService

    row = executions(request).get(execution_id)
    s = request.app.state
    row["defects"] = DefectService(s.db, s.bus).for_execution(execution_id)
    return row


@router.post("/executions/{execution_id}/complete")
def complete_execution(request: Request, execution_id: UUID, body: CompleteIn):
    """Human result for a blocked (awaiting_human) execution left by a task run."""
    return executions(request).complete_blocked(execution_id, body.model_dump(mode="json"))


@router.post("/cases/{case_id}/automate")
def automate_case(request: Request, case_id: UUID, body: AutomateIn):
    return _automation(request).automate(case_id, body.environment_id)


@router.post("/versions/{version_id}/automate")
def automate_version(request: Request, version_id: UUID, body: BatchAutomateIn):
    """Batch AI automation as background jobs: ready (optionally draft) manual cases of the
    version, plus cases marked needs_fix."""
    from testagent.services.case_gen import enqueue_automation

    statuses = ["ready", "draft"] if body.include_drafts else ["ready"]
    with request.app.state.db.tx() as cur:
        cur.execute("SELECT id FROM version WHERE id=%s", (version_id,))
        if cur.fetchone() is None:
            raise AppError("NOT_FOUND", "Version not found")
        cur.execute(
            "SELECT c.id FROM test_case c WHERE c.status = ANY(%(st)s)"
            " AND (c.mode='manual' OR c.automation_status IN ('needs_fix', 'env_unavailable')"
            " OR c.code_path IS NULL)"
            " AND (%(ids)s::uuid[] IS NULL OR c.id = ANY(%(ids)s::uuid[]))"
            " AND (c.origin_version_id=%(v)s OR EXISTS (SELECT 1 FROM case_requirement_link l"
            "  JOIN requirement r ON r.id=l.requirement_id WHERE l.case_id=c.id"
            "  AND r.version_id=%(v)s)) ORDER BY c.code",
            {
                "st": statuses,
                "ids": [str(i) for i in body.case_ids] if body.case_ids else None,
                "v": version_id,
            },
        )
        ids = [r["id"] for r in cur.fetchall()]
    return enqueue_automation(request.app.state.jobs, ids, version_id, body.environment_id)


@router.get("/versions/{version_id}/automation")
def automation_progress(request: Request, version_id: UUID):
    from testagent.services.automation import AUTOMATE_JOB

    with request.app.state.db.tx() as cur:
        cur.execute(
            "SELECT j.id, j.status, j.error, j.created_at, j.started_at, j.ended_at,"
            " c.id AS case_id, c.code, c.title, c.mode, c.automation_status, c.automation_note"
            " FROM jobs j LEFT JOIN test_case c ON c.id::text = j.payload->>'case_id'"
            " WHERE j.kind=%s AND j.payload->>'version_id'=%s ORDER BY j.id DESC LIMIT 200",
            (AUTOMATE_JOB, str(version_id)),
        )
        rows = cur.fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"jobs": rows, "counts": counts}


@router.get("/cases/{case_id}/code")
def case_code(request: Request, case_id: UUID, draft: bool = False):
    """Read-only view of the case's committed test file (or its needs_fix draft)."""
    from testagent.services.cases import CaseService

    case = CaseService(request.app.state.db, request.app.state.bus).get(case_id)
    path = case["automation_draft_path"] if draft else case["code_path"]
    commit = case["automation_draft_commit"] if draft else case["code_commit"]
    if not path:
        raise AppError("NOT_FOUND", "This case has no automation code")
    repo = TestRepo(request.app.state.repos_root, case["sut_code"], str(case["sut_id"]))
    rel = repo.resolve_test_path(path)
    content = None
    if commit and repo.initialized:
        proc = repo.git("show", f"{commit}:{rel}", check=False)
        if proc.returncode == 0:
            content = proc.stdout
    if content is None and repo.exists(rel):
        content = (repo.path / rel).read_text(encoding="utf-8")
    if content is None:
        raise AppError("NOT_FOUND", f"does not exist in the test repo {rel}")
    return {
        "path": rel,
        "abs_path": str((repo.path / rel).resolve()),
        "repo_path": str(repo.path.resolve()),
        "commit": commit,
        "content": content,
    }


@router.post("/cases/{case_id}/bind-code")
def bind_code(request: Request, case_id: UUID, body: BindIn):
    return _automation(request).bind_existing(case_id, body.code_path)


@router.get("/suts/{sut_id}/repo")
def repo_info(request: Request, sut_id: UUID):
    return _repo(request, sut_id).info()


@router.post("/suts/{sut_id}/repo/init")
def repo_init(request: Request, sut_id: UUID):
    return _repo(request, sut_id).ensure()


def _repo(request: Request, sut_id: UUID) -> TestRepo:
    with request.app.state.db.tx() as cur:
        cur.execute("SELECT code FROM sut WHERE id=%s", (sut_id,))
        row = cur.fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "SUT not found")
    return TestRepo(request.app.state.repos_root, row["code"], str(sut_id))


MEDIA = {b"\x89PNG": "image/png", b"PK\x03\x04": "application/zip", b"\x1aE\xdf\xa3": "video/webm"}


@router.get("/artifacts/{digest}")
def get_artifact(request: Request, digest: str):
    data = request.app.state.artifacts.get(digest)
    media = next((m for sig, m in MEDIA.items() if data.startswith(sig)), "application/octet-stream")
    return Response(
        content=data,
        media_type=media,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
