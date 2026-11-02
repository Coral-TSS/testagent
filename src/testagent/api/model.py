"""/api/v1 ontology model (nodes, edges, graph) and API registry."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from testagent.api.schemas import (
    ApiIn,
    ApiPatch,
    EdgeIn,
    FieldIn,
    FieldPatch,
    LinkIn,
    LinkPatch,
    NodeApisIn,
    NodeIn,
    NodeIoFromApisIn,
    NodePatch,
    OpenApiImportIn,
)
from testagent.services.apis import ApiService
from testagent.services.attributes import AttributeService
from testagent.services.field_align import suggest_alignment
from testagent.services.links import LinkService, suggest_links
from testagent.services.model import ModelService
from testagent.services.openapi_import import OpenApiImportService

router = APIRouter(prefix="/api/v1")


def _model(request: Request) -> ModelService:
    return ModelService(request.app.state.db, request.app.state.bus)


def _apis(request: Request) -> ApiService:
    return ApiService(request.app.state.db, request.app.state.bus)


# ---- nodes
@router.get("/suts/{sut_id}/nodes")
def list_nodes(
    request: Request,
    sut_id: UUID,
    kind: Literal["entity", "action", "relation"] | None = None,
    module_id: UUID | None = None,
    q: str | None = None,
    attr: Literal["conditions", "states", "constraints"] | None = None,
    attr_text: str | None = None,
):
    return _model(request).list_nodes(sut_id, kind=kind, module_id=module_id, q=q, attr=attr, attr_text=attr_text)


@router.post("/suts/{sut_id}/nodes", status_code=201)
def create_node(request: Request, sut_id: UUID, body: NodeIn):
    return _model(request).create_node(sut_id, body.model_dump())


@router.get("/nodes/{node_id}")
def get_node(request: Request, node_id: UUID):
    return _model(request).get_node(node_id)


@router.patch("/nodes/{node_id}")
def patch_node(request: Request, node_id: UUID, body: NodePatch):
    return _model(request).update_node(node_id, body.model_dump(exclude_unset=True))


@router.get("/nodes/{node_id}/references")
def node_references(request: Request, node_id: UUID):
    return _model(request).references(node_id)


@router.delete("/nodes/{node_id}")
def delete_node(request: Request, node_id: UUID, confirm: bool = False):
    return _model(request).delete_node(node_id, confirm=confirm)


@router.get("/nodes/{node_id}/neighbors")
def node_neighbors(request: Request, node_id: UUID, depth: int = Query(1, ge=1, le=5)):
    return _model(request).neighbors(node_id, depth)


# ---- edges
@router.post("/suts/{sut_id}/edges", status_code=201)
def create_edge(request: Request, sut_id: UUID, body: EdgeIn):
    return _model(request).create_edge(sut_id, body.source_node_id, body.target_node_id, body.role)


@router.delete("/edges/{edge_id}", status_code=204)
def delete_edge(request: Request, edge_id: UUID):
    _model(request).delete_edge(edge_id)
    return Response(status_code=204)


# ---- graph
@router.get("/suts/{sut_id}/graph")
def graph(request: Request, sut_id: UUID, module: UUID | None = None):
    return _model(request).graph(sut_id, module)


# ---- API registry
@router.get("/suts/{sut_id}/apis")
def list_apis(request: Request, sut_id: UUID):
    return _apis(request).list_for_sut(sut_id)


@router.post("/suts/{sut_id}/apis", status_code=201)
def create_api(request: Request, sut_id: UUID, body: ApiIn):
    return _apis(request).create({"sut_id": sut_id, **body.model_dump(exclude_none=True)})


@router.patch("/apis/{api_id}")
def patch_api(request: Request, api_id: UUID, body: ApiPatch):
    return _apis(request).update(api_id, body.model_dump(exclude_unset=True))


@router.delete("/apis/{api_id}", status_code=204)
def delete_api(request: Request, api_id: UUID):
    _apis(request).delete(api_id)
    return Response(status_code=204)


@router.put("/nodes/{node_id}/apis")
def set_node_apis(request: Request, node_id: UUID, body: NodeApisIn):
    return _apis(request).set_node_apis(node_id, body.api_ids)


@router.post("/nodes/{node_id}/io/from-apis")
def node_io_from_apis(request: Request, node_id: UUID, body: NodeIoFromApisIn):
    """Fill the action's inputs/outputs (and an empty purpose / formats) from its linked APIs."""
    summary = _apis(request).inherit_io(node_id, replace=body.replace)
    return {**summary, "node": _model(request).get_node(node_id)}


@router.post("/suts/{sut_id}/apis/import-openapi")
def import_openapi(request: Request, sut_id: UUID, body: OpenApiImportIn):
    db, bus = request.app.state.db, request.app.state.bus
    result = OpenApiImportService(db, bus).import_from(sut_id, body.environment_id, body.url)
    # entity fields follow the API field names: propose renames / missing fields
    created = suggest_alignment(db, bus, sut_id)
    # reference / <resource>_id fields imply links
    links = suggest_links(db, bus, sut_id)
    return {**result, "field_suggestions": len(created), "link_suggestions": len(links)}


# ---- link types (relations between entities)
def _links(request: Request) -> LinkService:
    return LinkService(request.app.state.db, request.app.state.bus)


@router.get("/suts/{sut_id}/links")
def list_links(request: Request, sut_id: UUID, node_id: UUID | None = None):
    return _links(request).list(sut_id, node_id)


@router.post("/suts/{sut_id}/links", status_code=201)
def create_link(request: Request, sut_id: UUID, body: LinkIn):
    return _links(request).create(sut_id, body.model_dump(mode="json"))


@router.post("/suts/{sut_id}/links/suggest")
def suggest_sut_links(request: Request, sut_id: UUID):
    """Propose links for reference / <resource>_id fields (pending suggestions)."""
    created = suggest_links(request.app.state.db, request.app.state.bus, sut_id)
    return {"created": len(created), "suggestions": created}


@router.get("/links/{link_id}")
def get_link(request: Request, link_id: UUID):
    return _links(request).get(link_id)


@router.patch("/links/{link_id}")
def update_link(request: Request, link_id: UUID, body: LinkPatch):
    return _links(request).update(link_id, body.model_dump(mode="json", exclude_unset=True))


@router.delete("/links/{link_id}")
def delete_link(request: Request, link_id: UUID, confirm: bool = False):
    return _links(request).delete(link_id, confirm=confirm)


# ---- entity fields (attributes)
def _fields(request: Request) -> AttributeService:
    return AttributeService(request.app.state.db, request.app.state.bus)


@router.get("/suts/{sut_id}/fields")
def list_sut_fields(request: Request, sut_id: UUID):
    return _fields(request).list_for_sut(sut_id)


@router.get("/nodes/{node_id}/fields")
def list_node_fields(request: Request, node_id: UUID):
    return _fields(request).list_for_node(node_id)


@router.post("/nodes/{node_id}/fields", status_code=201)
def create_field(request: Request, node_id: UUID, body: FieldIn):
    return _fields(request).create(node_id, body.model_dump(mode="json", exclude_none=True))


@router.get("/fields/{field_id}")
def get_field(request: Request, field_id: UUID):
    return _fields(request).get(field_id)


@router.patch("/fields/{field_id}")
def patch_field(request: Request, field_id: UUID, body: FieldPatch):
    return _fields(request).update(field_id, body.model_dump(mode="json", exclude_unset=True))


@router.delete("/fields/{field_id}")
def delete_field(request: Request, field_id: UUID, confirm: bool = False):
    return _fields(request).delete(field_id, confirm=confirm)
