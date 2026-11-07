"""/api/v1 test cases, AI generation, coverage, export and corrections (M1-07)."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from testagent.services.case_gen import CaseGenerationService
from testagent.services.cases import CaseService

router = APIRouter(prefix="/api/v1")
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Tag = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepIn(_In):
    action: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    data: str | None = None
    expected: str | None = None


class CaseFields(_In):
    test_point: str | None = None
    priority: Literal["P0", "P1", "P2"] | None = None
    type_tag: Tag | None = None
    scenario: Literal["normal", "boundary", "exception"] | None = None
    category: Literal["requirement", "quality", "regression"] | None = None
    """requirement / quality (idempotency, concurrency, repeatability…) / regression;
    input validation is requirement."""
    quality_tags: list[Tag] | None = None
    mode: Literal["manual", "automated"] | None = None
    preconditions: str | None = None
    steps: list[StepIn] | None = None
    test_data: dict[str, Any] | None = None
    expected: str | None = None
    code_path: str | None = None
    requirement_ids: list[UUID] | None = None
    node_ids: list[UUID] | None = None
    attribute_ids: list[UUID] | None = None


class CaseIn(CaseFields):
    title: Title
    origin_version_id: UUID | None = None


class CasePatch(CaseFields):
    title: Title | None = None


class CaseStatusIn(_In):
    status: Literal["draft", "ready", "deprecated"]


class GenerateIn(_In):
    requirement_ids: list[UUID] | None = None
    automate: bool | None = None
    """None = agent config default (auto_automate, on by default)."""
    environment_id: UUID | None = None


class SuggestionIn(_In):
    accept: bool


class AcceptIn(_In):
    fields: list[str] | None = None
    """None = every proposed field."""


class BatchIn(_In):
    case_ids: list[UUID] = Field(min_length=1, max_length=500)
    action: Literal["ready", "draft", "deprecated", "automate", "complete", "add_to_task"]
    task_id: UUID | None = None
    environment_id: UUID | None = None


def _cases(r: Request) -> CaseService:
    return CaseService(r.app.state.db, r.app.state.bus)


def _completion(r: Request):
    from testagent.services.case_complete import CaseCompletionService

    return CaseCompletionService(r.app.state.db, r.app.state.bus, r.app.state.agent.runtime)


@router.get("/suts/{sut_id}/cases")
def list_cases(
    request: Request,
    sut_id: UUID,
    version_id: UUID | None = None,
    requirement_id: UUID | None = None,
    status: Literal["draft", "ready", "deprecated"] | None = None,
    q: str | None = None,
):
    return _cases(request).list(
        sut_id, version_id=version_id, requirement_id=requirement_id, status=status, q=q or None
    )


@router.post("/suts/{sut_id}/cases", status_code=201)
def create_case(request: Request, sut_id: UUID, body: CaseIn):
    return _cases(request).create(sut_id, body.model_dump(mode="json", exclude_none=True))


def with_paths(request: Request, case: dict) -> dict:
    """Absolute locations in the local test repository (2a)."""
    from testagent.integrations.git_repo import TestRepo

    repo = TestRepo(request.app.state.repos_root, case["sut_code"]).path.resolve()
    case["repo_path"] = str(repo)
    case["code_abs_path"] = str(repo / case["code_path"]) if case.get("code_path") else None
    draft = case.get("automation_draft_path")
    case["draft_abs_path"] = str(repo / draft) if draft else None
    return case


@router.get("/cases/{case_id}")
def get_case(request: Request, case_id: UUID):
    return with_paths(request, _cases(request).get(case_id))


@router.patch("/cases/{case_id}")
def update_case(request: Request, case_id: UUID, body: CasePatch):
    return _cases(request).update(case_id, body.model_dump(mode="json", exclude_unset=True))


@router.post("/cases/{case_id}/status")
def set_case_status(request: Request, case_id: UUID, body: CaseStatusIn):
    return _cases(request).set_status(case_id, body.status)


@router.post("/cases/{case_id}/ai-complete")
def ai_complete_case(request: Request, case_id: UUID):
    """AI completion: stores a proposal on the case; nothing changes until a human accepts."""
    return _completion(request).complete(case_id)


@router.post("/cases/{case_id}/ai-complete/accept")
def accept_ai_completion(request: Request, case_id: UUID, body: AcceptIn):
    return with_paths(request, _completion(request).accept(case_id, body.fields))


@router.post("/cases/{case_id}/ai-complete/reject")
def reject_ai_completion(request: Request, case_id: UUID):
    return with_paths(request, _completion(request).reject(case_id))


@router.post("/cases/batch")
def batch_cases(request: Request, body: BatchIn):
    """Batch actions on the case list. Each case is handled on its own: one failure
    (e.g. a deprecated case cannot become executable) does not stop the others."""
    from testagent.core.errors import AppError
    from testagent.services.case_complete import enqueue_completion
    from testagent.services.case_gen import enqueue_automation
    from testagent.services.tasks import TaskService

    db = request.app.state.db
    ids = list(dict.fromkeys(str(i) for i in body.case_ids))
    with db.tx() as cur:
        cur.execute(
            "SELECT c.id::text AS id, c.code, c.title, c.status, coalesce(c.origin_version_id,"
            " (SELECT r.version_id FROM case_requirement_link l JOIN requirement r"
            "  ON r.id=l.requirement_id WHERE l.case_id=c.id ORDER BY r.code LIMIT 1))"
            " AS version_id FROM test_case c WHERE c.id = ANY(%s::uuid[]) ORDER BY c.code",
            (ids,),
        )
        cases = cur.fetchall()
    found = {c["id"] for c in cases}
    failed = [{"id": i, "code": None, "error": "Test case not found"} for i in ids if i not in found]
    ok: list[dict] = []
    skipped: list[dict] = []
    queued = 0
    brief = lambda c: {"id": c["id"], "code": c["code"]}  # noqa: E731
    if body.action in ("ready", "draft", "deprecated"):
        svc = _cases(request)
        for c in cases:
            if c["status"] == body.action:
                feedback = {"task_binding": svc.get(c["id"])["task_binding"]} if body.action == "ready" else {}
                skipped.append({**brief(c), "reason": "Already in the target state", **feedback})
                continue
            try:
                updated = svc.set_status(c["id"], body.action)
                feedback = {"task_binding": updated["task_binding"]} if body.action == "ready" else {}
                ok.append({**brief(c), **feedback})
            except AppError as exc:
                failed.append({**brief(c), "error": exc.message})
    elif body.action == "automate":
        live = [c for c in cases if c["status"] != "deprecated"]
        skipped += [{**brief(c), "reason": "Deprecated"} for c in cases if c["status"] == "deprecated"]
        by_version: dict[str | None, list[str]] = {}
        for c in live:
            by_version.setdefault(str(c["version_id"]) if c["version_id"] else None, []).append(c["id"])
        for version_id, group in by_version.items():
            queued += enqueue_automation(request.app.state.jobs, group, version_id, body.environment_id)["queued"]
        ok += [brief(c) for c in live]
    elif body.action == "complete":
        live = [c for c in cases if c["status"] != "deprecated"]
        skipped += [{**brief(c), "reason": "Deprecated"} for c in cases if c["status"] == "deprecated"]
        queued = enqueue_completion(request.app.state.jobs, [c["id"] for c in live])["queued"]
        ok += [brief(c) for c in live]
    else:  # add_to_task
        if body.task_id is None:
            raise AppError("VALIDATION", "Choose the task to add to")
        tasks = TaskService(db, request.app.state.bus, default_tz=request.app.state.timezone)
        task = tasks.get(body.task_id)
        existing = [str(c["id"]) for c in task["cases"]]
        live = [c for c in cases if c["status"] != "deprecated"]
        skipped += [{**brief(c), "reason": "Deprecated"} for c in cases if c["status"] == "deprecated"]
        skipped += [{**brief(c), "reason": "Already in the task"} for c in live if c["id"] in existing]
        new = [c for c in live if c["id"] not in existing]
        if new:
            tasks.set_cases(body.task_id, [*existing, *(c["id"] for c in new)])
        ok += [brief(c) for c in new]
    return {"action": body.action, "ok": ok, "skipped": skipped, "failed": failed, "queued": queued}


@router.get("/cases/{case_id}/revisions")
def case_revisions(request: Request, case_id: UUID):
    return _cases(request).revisions(case_id)


@router.post("/versions/{version_id}/cases/generate")
def generate_cases(request: Request, version_id: UUID, body: GenerateIn):
    service = CaseGenerationService(request.app.state.db, request.app.state.bus, request.app.state.agent.runtime)
    return service.generate(
        version_id,
        body.requirement_ids,
        automate=body.automate,
        environment_id=body.environment_id,
        jobs=request.app.state.jobs,
    )


@router.get("/versions/{version_id}/coverage")
def coverage(request: Request, version_id: UUID):
    return _cases(request).coverage(version_id)


@router.post("/versions/{version_id}/coverage", status_code=201)
def save_coverage(request: Request, version_id: UUID):
    return _cases(request).save_coverage(version_id)


@router.get("/versions/{version_id}/coverage/reports")
def coverage_reports(request: Request, version_id: UUID):
    return _cases(request).coverage_reports(version_id)


@router.get("/versions/{version_id}/cases/export")
def export_cases(request: Request, version_id: UUID, format: Literal["csv", "md"] = Query("csv")):
    text, media = _cases(request).export(version_id, format)
    return Response(
        content=text.encode("utf-8"),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="cases-{version_id}.{format}"'},
    )


@router.post("/cases/{case_id}/category-suggestion")
def resolve_category_suggestion(request: Request, case_id: UUID, body: SuggestionIn):
    from testagent.services.task_binding import TaskBindingService

    service = TaskBindingService(request.app.state.db, request.app.state.bus)
    return service.resolve_suggestion(case_id, accept=body.accept)
