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


@router.get("/suts/{sut_id}/model-review")
def model_review(request: Request, sut_id: UUID):
    return ModelReviewService(request.app.state.db).get(sut_id)


@router.put("/suts/{sut_id}/model-review/marks")
def mark_reviewed(request: Request, sut_id: UUID, body: MarkIn):
    """Reviewer's per-element mark (a UI aid; it does not accept any suggestion)."""
    return ModelReviewService(request.app.state.db).mark(sut_id, body.model_dump(mode="json"))


@router.get("/suts/{sut_id}/model-review.md")
def model_review_markdown(request: Request, sut_id: UUID):
    text, filename = ModelReviewService(request.app.state.db).markdown(sut_id)
    return Response(
        content=text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
