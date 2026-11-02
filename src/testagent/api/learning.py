"""/api/v1 corrections, prompts, memories, skills and MCP registry (M1-12, P15)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from testagent.services.learning import (
    TARGET_TYPES,
    CorrectionService,
    MemoryService,
    PromptService,
    RegistryOnlyService,
)

router = APIRouter(prefix="/api/v1")
TargetType = Literal[TARGET_TYPES]  # type: ignore[valid-type]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CorrectionIn(_In):
    target_type: TargetType
    target_id: UUID
    content: str = Field(min_length=1, max_length=20000)  # stored verbatim (no trimming)
    kind: Literal["correction", "omission"] | None = None


class PromptVersionIn(_In):
    content: str = Field(max_length=20000)
    note: str | None = Field(default=None, max_length=500)


class MemoryPatch(_In):
    enabled: bool


class SkillIn(_In):
    name: Name
    description: str | None = Field(default=None, max_length=2000)
    content: str | None = Field(default=None, max_length=50000)
    source: str | None = Field(default=None, max_length=1000)
    enabled: bool = True


class SkillPatch(_In):
    description: str | None = None
    content: str | None = None
    source: str | None = None
    enabled: bool | None = None


class McpIn(_In):
    name: Name
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool = True


class McpPatch(_In):
    transport: Literal["stdio", "http"] | None = None
    command: str | None = None
    url: str | None = None
    description: str | None = None
    enabled: bool | None = None


def _corrections(r: Request) -> CorrectionService:
    return CorrectionService(r.app.state.db, r.app.state.bus)


def _prompts(r: Request) -> PromptService:
    names = [n for n in r.app.state.agent.runtime.entries if n != "digest_correction"]
    return PromptService(r.app.state.db, names)


# ------------------------------------------------------------------ corrections
@router.post("/corrections", status_code=201)
def create_correction(request: Request, body: CorrectionIn):
    return _corrections(request).create(body.target_type, body.target_id, body.content, body.kind)


@router.get("/corrections")
def list_corrections(
    request: Request,
    target_type: str | None = None,
    target_id: UUID | None = None,
    status: str | None = None,
    kind: str | None = None,
    sut_id: UUID | None = None,
):
    return _corrections(request).list(target_type, target_id, status, kind, sut_id)


@router.get("/corrections/{correction_id}")
def get_correction(request: Request, correction_id: UUID):
    return _corrections(request).get(correction_id)


@router.post("/corrections/{correction_id}/reprocess")
def reprocess_correction(request: Request, correction_id: UUID):
    return _corrections(request).reprocess(correction_id)


# ------------------------------------------------------------------ prompts
@router.get("/agent/prompts")
def list_prompts(request: Request):
    return _prompts(request).list()


@router.get("/agent/prompts/{name}")
def prompt_versions(request: Request, name: str):
    return _prompts(request).versions(name)


@router.post("/agent/prompts/{name}/versions", status_code=201)
def new_prompt_version(request: Request, name: str, body: PromptVersionIn):
    return _prompts(request).create(name, body.content, body.note)


@router.post("/agent/prompts/{name}/versions/{version}/activate")
def activate_prompt(request: Request, name: str, version: int):
    return _prompts(request).activate(name, version)


# ------------------------------------------------------------------ memories
@router.get("/agent/memories")
def list_memories(
    request: Request,
    scope: Literal["global", "sut"] | None = None,
    sut_id: UUID | None = None,
    enabled: bool | None = None,
):
    return MemoryService(request.app.state.db).list(scope, sut_id, enabled)


@router.patch("/agent/memories/{memory_id}")
def patch_memory(request: Request, memory_id: UUID, body: MemoryPatch):
    return MemoryService(request.app.state.db).set_enabled(memory_id, body.enabled)


# ------------------------------------------------------------------ skills / MCP (register only)
@router.get("/agent/skills")
def list_skills(request: Request):
    return RegistryOnlyService(request.app.state.db, "skill").list()


@router.post("/agent/skills", status_code=201)
def create_skill(request: Request, body: SkillIn):
    return RegistryOnlyService(request.app.state.db, "skill").create(body.model_dump())


@router.patch("/agent/skills/{item_id}")
def patch_skill(request: Request, item_id: UUID, body: SkillPatch):
    data = body.model_dump(exclude_unset=True)
    return RegistryOnlyService(request.app.state.db, "skill").update(item_id, data)


@router.get("/agent/mcp-servers")
def list_mcp(request: Request):
    return RegistryOnlyService(request.app.state.db, "mcp_server").list()


@router.post("/agent/mcp-servers", status_code=201)
def create_mcp(request: Request, body: McpIn):
    return RegistryOnlyService(request.app.state.db, "mcp_server").create(body.model_dump())


@router.patch("/agent/mcp-servers/{item_id}")
def patch_mcp(request: Request, item_id: UUID, body: McpPatch):
    data = body.model_dump(exclude_unset=True)
    return RegistryOnlyService(request.app.state.db, "mcp_server").update(item_id, data)
