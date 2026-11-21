"""/api/v1 navigation and model review."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from testagent.services import navigation
from testagent.services.model_review import ModelReviewService

router = APIRouter(prefix="/api/v1")

Kind = Literal["sut", "version", "requirement", "task", "run", "case", "execution", "defect", "report"]


class MarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["entity", "action", "link"]
    target_id: UUID
    reviewed: bool = True
    note: str | None = Field(default=None, max_length=500)


@router.get("/nav/context")
def nav_context(request: Request, kind: Kind, id: UUID):  # noqa: A002 - query name
    """Breadcrumb chain of a detail object with readable labels and page paths."""
    return navigation.context(request.app.state.db, kind, id)


@router.get("/suts/{sut_id}/progress")
def sut_progress(request: Request, sut_id: UUID, version_id: UUID | None = None):
    """Main-flow steps of a system for one version (latest open one by default)."""
    s = request.app.state
    return navigation.progress(s.db, sut_id, version_id, repos_root=s.repos_root)


def _sut_of(db, version_id):
    from testagent.core.errors import AppError

    with db.tx() as cur:
        cur.execute("SELECT sut_id FROM version WHERE id=%s", (version_id,))
        row = cur.fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Version not found")
    return row["sut_id"]


@router.get("/suts/{sut_id}/model-review")
def model_review(request: Request, sut_id: UUID, version_id: UUID | None = None):
    return ModelReviewService(request.app.state.db).get(sut_id, version_id)


@router.get("/versions/{version_id}/model-review")
def version_model_review(request: Request, version_id: UUID):
    db = request.app.state.db
    return ModelReviewService(db).get(_sut_of(db, version_id), version_id)


@router.put("/suts/{sut_id}/model-review/marks")
def mark_reviewed(request: Request, sut_id: UUID, body: MarkIn, version_id: UUID | None = None):
    """Reviewer's per-element mark (a UI aid; it does not accept any suggestion)."""
    return ModelReviewService(request.app.state.db).mark(sut_id, body.model_dump(mode="json"), version_id)


@router.put("/versions/{version_id}/model-review/marks")
def version_mark_reviewed(request: Request, version_id: UUID, body: MarkIn):
    db = request.app.state.db
    return ModelReviewService(db).mark(_sut_of(db, version_id), body.model_dump(mode="json"), version_id)


@router.get("/suts/{sut_id}/model-review.md")
def model_review_markdown(request: Request, sut_id: UUID, version_id: UUID | None = None):
    text, filename = ModelReviewService(request.app.state.db).markdown(sut_id, version_id)
    return Response(
        content=text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/versions/{version_id}/model-review.md")
def version_model_review_markdown(request: Request, version_id: UUID):
    db = request.app.state.db
    text, filename = ModelReviewService(db).markdown(_sut_of(db, version_id), version_id)
    return Response(
        content=text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
