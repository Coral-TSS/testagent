"""/api/v1 persons, suts, environments, modules."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response

from testagent.api.schemas import (
    EnvironmentIn,
    EnvironmentPatch,
    ModuleIn,
    ModulePatch,
    PersonIn,
    PersonPatch,
    SutIn,
    SutPatch,
)
from testagent.services.registry import (
    EnvironmentService,
    ModuleService,
    PersonService,
    SutService,
)

router = APIRouter(prefix="/api/v1")


def _svc(request: Request, cls):
    return cls(request.app.state.db, request.app.state.bus)


def _patch(body) -> dict:
    return body.model_dump(exclude_unset=True)


# ---- persons
@router.get("/persons")
def list_persons(request: Request, active: bool | None = None):
    return _svc(request, PersonService).list({"active": active} if active is not None else None)


@router.post("/persons", status_code=201)
def create_person(request: Request, body: PersonIn):
    return _svc(request, PersonService).create(body.model_dump())


@router.get("/persons/{id_}")
def get_person(request: Request, id_: UUID):
    return _svc(request, PersonService).get(id_)


@router.patch("/persons/{id_}")
def patch_person(request: Request, id_: UUID, body: PersonPatch):
    return _svc(request, PersonService).update(id_, _patch(body))


@router.post("/persons/{id_}/deactivate")
def deactivate_person(request: Request, id_: UUID):
    return _svc(request, PersonService).update(id_, {"active": False})


# ---- suts
@router.get("/suts")
def list_suts(request: Request):
    return _svc(request, SutService).list()


@router.post("/suts", status_code=201)
def create_sut(request: Request, body: SutIn):
    return _svc(request, SutService).create(body.model_dump())


@router.get("/suts/{id_}")
def get_sut(request: Request, id_: UUID):
    return _svc(request, SutService).get(id_)


@router.patch("/suts/{id_}")
def patch_sut(request: Request, id_: UUID, body: SutPatch):
    return _svc(request, SutService).update(id_, _patch(body))


@router.delete("/suts/{id_}", status_code=204)
def delete_sut(request: Request, id_: UUID):
    _svc(request, SutService).delete(id_)
    return Response(status_code=204)


# ---- environments
@router.get("/suts/{sut_id}/environments")
def list_environments(request: Request, sut_id: UUID):
    _svc(request, SutService).get(sut_id)
    return _svc(request, EnvironmentService).list({"sut_id": sut_id}, order="name")


@router.post("/suts/{sut_id}/environments", status_code=201)
def create_environment(request: Request, sut_id: UUID, body: EnvironmentIn):
    return _svc(request, EnvironmentService).create({"sut_id": sut_id, **body.model_dump()})


@router.patch("/environments/{id_}")
def patch_environment(request: Request, id_: UUID, body: EnvironmentPatch):
    return _svc(request, EnvironmentService).update(id_, _patch(body))


@router.get("/environments/{id_}/check")
def check_environment(request: Request, id_: UUID):
    """Preflight: can the platform connect to the environment's base URL?"""
    from testagent.services.environments import probe, unreachable_message

    env = _svc(request, EnvironmentService).get(id_)
    ok, _ = probe(env["base_url"])
    running = request.app.state.env_processes.running(id_)
    return {
        "reachable": ok,
        "started_by_platform": running,
        "message": "Environment reachable" if ok else unreachable_message(env),
    }


@router.post("/environments/{id_}/start")
def start_environment(request: Request, id_: UUID):
    """Run the environment's start command (local systems such as the procurement demo)."""
    env = _svc(request, EnvironmentService).get(id_)
    return request.app.state.env_processes.start(env)


@router.delete("/environments/{id_}", status_code=204)
def delete_environment(request: Request, id_: UUID):
    _svc(request, EnvironmentService).delete(id_)
    return Response(status_code=204)


# ---- modules (optional node grouping, no owner)
@router.get("/suts/{sut_id}/modules")
def list_modules(request: Request, sut_id: UUID):
    _svc(request, SutService).get(sut_id)
    return _svc(request, ModuleService).list({"sut_id": sut_id}, order="name")


@router.post("/suts/{sut_id}/modules", status_code=201)
def create_module(request: Request, sut_id: UUID, body: ModuleIn):
    return _svc(request, ModuleService).create({"sut_id": sut_id, **body.model_dump()})


@router.patch("/modules/{id_}")
def patch_module(request: Request, id_: UUID, body: ModulePatch):
    return _svc(request, ModuleService).update(id_, _patch(body))


@router.delete("/modules/{id_}", status_code=204)
def delete_module(request: Request, id_: UUID):
    _svc(request, ModuleService).delete(id_)
    return Response(status_code=204)
