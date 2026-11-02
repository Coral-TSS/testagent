"""AI draft tasks for M1-05: `structure_requirement` and `complete_model`.

The agent only drafts (C01): its validated output is written by these services with
source/agent_run_id bookkeeping; confirmation and freezing stay human-only."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from testagent.agent.runtime import AgentRuntime, Entry
from testagent.agent.tools import model_catalog
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.action_rules import Effect, Precondition
from testagent.services.changelog import log_change
from testagent.services.io_spec import DataType, IoParam
from testagent.services.model import find_similar_node
from testagent.services.requirements import PARTS, RequirementService
from testagent.services.suggestions import SuggestionService

Part = Literal["actor", "condition", "action", "result", "constraint"]
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class NodeSuggestion(BaseModel):
    kind: Literal["node"] = "node"
    node_kind: Literal["entity", "action"]
    name: Text
    description: str | None = Field(default=None, description="for an action: what it does")
    inputs: list[IoParam] = Field(default_factory=list, description="action inputs")
    outputs: list[IoParam] = Field(default_factory=list, description="action outputs")
    input_format: str | None = Field(default=None, max_length=500)
    output_format: str | None = Field(default=None, max_length=500)
    requirement_id: UUID | None = None
    part: Part | None = None
    reason: str | None = None


class AttributeSuggestion(BaseModel):
    kind: Literal["attribute"] = "attribute"
    node_id: UUID
    attr: Literal["conditions", "states", "constraints"]
    text: Text
    expr: str | None = None
    requirement_id: UUID | None = None
    part: Part | None = None
    reason: str | None = None


class FieldSuggestion(BaseModel):
    """A missing field on an existing entity, e.g. PurchaseOrder.amount (amount)."""

    kind: Literal["field"] = "field"
    node_id: UUID = Field(description="the entity that should own the field")
    name: Annotated[str, Field(min_length=1, max_length=100)]
    display_name: str | None = Field(default=None, max_length=100)
    data_type: DataType = Field(description="required; enum needs enum_values")
    unit: str | None = Field(default=None, max_length=50)
    required: bool = False
    format: str | None = Field(default=None, max_length=200)
    enum_values: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list)
    description: str | None = None
    rename_from: str | None = Field(
        default=None,
        max_length=100,
        description="existing field of the entity to rename to `name` (API name is canonical)",
    )
    requirement_id: UUID | None = None
    part: Part | None = None
    reason: str | None = None


class IoSuggestion(BaseModel):
    """Purpose / inputs / outputs for an existing action that lacks them (e.g. taken from the
    schema of its linked API)."""

    kind: Literal["io"] = "io"
    node_id: UUID = Field(description="the existing action node")
    description: str | None = Field(default=None, description="what the action does")
    inputs: list[IoParam] = Field(default_factory=list)
    outputs: list[IoParam] = Field(default_factory=list)
    input_format: str | None = Field(default=None, max_length=500)
    output_format: str | None = Field(default=None, max_length=500)
    requirement_id: UUID | None = None
    part: Part | None = None
    reason: str | None = None


class LinkSuggestion(BaseModel):
    """A relation between two existing entities, read in both directions."""

    kind: Literal["link"] = "link"
    from_node_id: UUID = Field(description="entity that reads the link with forward_name")
    to_node_id: UUID
    forward_name: Annotated[str, Field(min_length=1, max_length=50)] = Field(
        description="preposition/verb from → to, e.g. belongs to (PurchaseOrder belongs to Supplier)"
    )
    reverse_name: Annotated[str, Field(min_length=1, max_length=50)] = Field(
        description="preposition/verb to → from, e.g. supplies (Supplier supplies PurchaseOrder)"
    )
    forward_api_name: str | None = Field(default=None, pattern=r"^[a-z][A-Za-z0-9_]{0,99}$")
    reverse_api_name: str | None = Field(default=None, pattern=r"^[a-z][A-Za-z0-9_]{0,99}$")
    cardinality: Literal["one_to_one", "many_to_one", "one_to_many", "many_to_many"] = "many_to_one"
    fk_attribute_id: UUID | None = Field(
        default=None, description="foreign-key field (e.g. Payment.order_id) on the N side"
    )
    via_node_id: UUID | None = Field(default=None, description="junction entity for M:N")
    required: bool = False
    description: str | None = None
    requirement_id: UUID | None = None
    part: Part | None = None
    reason: str | None = None


class RulesSuggestion(BaseModel):
    """Preconditions / effects for an existing action (Palantir: submission criteria / rules)."""

    kind: Literal["rules"] = "rules"
    node_id: UUID = Field(description="the existing action node")
    preconditions: list[Precondition] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    requirement_id: UUID | None = None
    part: Part | None = None
    reason: str | None = None


Suggestion = Annotated[
    NodeSuggestion | AttributeSuggestion | FieldSuggestion | IoSuggestion | LinkSuggestion | RulesSuggestion,
    Field(discriminator="kind"),
]


class StructItem(BaseModel):
    part: Part
    text: Text
    node_id: UUID | None = None
    attribute_id: UUID | None = Field(
        default=None, description="entity field this item is about (e.g. PurchaseOrder.amount)"
    )
    link_id: UUID | None = Field(default=None, description="link this item is about (e.g. Payment pays PurchaseOrder)")
    missing: bool = False
    suggestion: Suggestion | None = None

    @model_validator(mode="after")
    def _node_or_missing(self):
        linked = self.node_id is not None or self.attribute_id is not None or self.link_id is not None
        if linked == self.missing:
            raise ValueError("each item needs node_id/attribute_id or missing=true (not both)")
        return self


class StructureOut(BaseModel):
    items: list[StructItem] = Field(min_length=1)
    io_suggestions: list[IoSuggestion] = Field(
        default_factory=list,
        description="purpose/inputs/outputs for linked actions whose inputs/outputs are empty",
    )


class CompleteOut(BaseModel):
    suggestions: list[Suggestion] = Field(default_factory=list)


def _check_nodes(db, sut_id, node_ids: set[str]) -> list[str]:
    if not node_ids:
        return []
    with db.tx() as cur:
        cur.execute(
            "SELECT id::text AS id FROM model_node WHERE id = ANY(%s::uuid[]) AND sut_id=%s AND deleted_at IS NULL",
            (list(node_ids), sut_id),
        )
        valid = {r["id"] for r in cur.fetchall()}
    return [f"node_id {n} does not exist in this system's model" for n in sorted(node_ids - valid)]


def _check_fields(db, sut_id, attr_ids: set[str]) -> list[str]:
    if not attr_ids:
        return []
    with db.tx() as cur:
        cur.execute(
            "SELECT id::text AS id FROM entity_attribute WHERE id = ANY(%s::uuid[])"
            " AND sut_id=%s AND deleted_at IS NULL",
            (list(attr_ids), sut_id),
        )
        valid = {r["id"] for r in cur.fetchall()}
    return [f"attribute_id {a} does not exist (see list_fields)" for a in sorted(attr_ids - valid)]


def _check_links(db, sut_id, link_ids: set[str]) -> list[str]:
    if not link_ids:
        return []
    with db.tx() as cur:
        cur.execute(
            "SELECT id::text AS id FROM model_link WHERE id = ANY(%s::uuid[]) AND sut_id=%s AND deleted_at IS NULL",
            (list(link_ids), sut_id),
        )
        valid = {r["id"] for r in cur.fetchall()}
    return [f"link_id {x} does not exist (see list_links)" for x in sorted(link_ids - valid)]


def _check_link_rules(db, sut_id, suggestions: list) -> list[str]:
    """Link ends must be entities; rules must target actions and resolve Entity.field."""
    from testagent.services.action_rules import validate_rules

    errors = []
    with db.tx() as cur:
        for s in suggestions:
            if s is None or s.kind not in ("link", "rules"):
                continue
            ids = (
                [s.from_node_id, s.to_node_id] + ([s.via_node_id] if s.via_node_id else [])
                if s.kind == "link"
                else [s.node_id]
            )
            want = "entity" if s.kind == "link" else "action"
            cur.execute(
                "SELECT count(DISTINCT id) AS n FROM model_node WHERE id = ANY(%s::uuid[])"
                " AND sut_id=%s AND kind=%s AND deleted_at IS NULL",
                ([str(i) for i in ids], sut_id, want),
            )
            if cur.fetchone()["n"] != len({str(i) for i in ids}):
                errors.append(f"{s.kind} suggestion: {ids} must be existing {want} nodes")
            if s.kind == "rules":
                data = s.model_dump(mode="json", include={"preconditions", "effects"})
                try:
                    validate_rules(cur, sut_id, data)
                except AppError as exc:
                    errors.append(
                        f"rules for {s.node_id}: {exc.message} {exc.field_errors or ''} "
                        "(field must be Entity.field from list_fields; enum values must exist)"
                    )
    return errors


def _check_field_owners(db, sut_id, suggestions: list) -> list[str]:
    ids = {str(s.node_id) for s in suggestions if s is not None and s.kind == "field"}
    if not ids:
        return []
    with db.tx() as cur:
        cur.execute(
            "SELECT id::text AS id FROM model_node WHERE id = ANY(%s::uuid[]) AND sut_id=%s"
            " AND kind='entity' AND deleted_at IS NULL",
            (list(ids), sut_id),
        )
        valid = {r["id"] for r in cur.fetchall()}
        errors = [f"field suggestion node {n} is not an entity of this system" for n in ids - valid]
        for s in suggestions:
            if s is None or s.kind != "field" or not s.rename_from:
                continue
            cur.execute(
                "SELECT 1 FROM entity_attribute WHERE node_id=%s AND deleted_at IS NULL AND lower(name)=lower(%s)",
                (str(s.node_id), s.rename_from),
            )
            if cur.fetchone() is None:
                errors.append(f"rename_from {s.rename_from}: no such field on node {s.node_id}")
    return errors


def _check_io_owners(db, sut_id, suggestions: list) -> list[str]:
    ids = {str(s.node_id) for s in suggestions if s is not None and s.kind == "io"}
    if not ids:
        return []
    with db.tx() as cur:
        cur.execute(
            "SELECT id::text AS id FROM model_node WHERE id = ANY(%s::uuid[]) AND sut_id=%s"
            " AND kind='action' AND deleted_at IS NULL",
            (list(ids), sut_id),
        )
        valid = {r["id"] for r in cur.fetchall()}
    return [f"io suggestion node {n} is not an action of this system" for n in ids - valid]


def _check_enum(suggestions: list) -> list[str]:
    errors = []
    for s in suggestions:
        if s is None:
            continue
        params = [*(getattr(s, "inputs", None) or []), *(getattr(s, "outputs", None) or [])]
        for p in params:
            if p.data_type == "enum" and not p.enum_values:
                errors.append(f"parameter {p.name}: data_type enum needs enum_values")
        if s.kind == "field" and s.data_type == "enum" and not s.enum_values:
            errors.append(f"field {s.name}: data_type enum needs enum_values")
    return errors


FIELD_NAMES = (
    "Entity fields are named like the code entity and its API fields (a database column may "
    "differ and is only noted as storage_name): use the API's field names (get_api_schema), "
    "e.g. amount_minor rather than amount. When an existing field has the meaning of an API "
    "field under another name, propose kind=field with the API name and rename_from = the "
    "existing field name instead of a second field."
)
LINKS_AND_RULES = (
    " Relations between entities are links (input `model.links`, list_links), not nodes: a "
    "link reads both ways with a preposition/verb on each side (PurchaseOrder belongs to Supplier / Supplier supplies "
    "PurchaseOrder), has a cardinality (one_to_one, many_to_one, one_to_many, many_to_many) and a "
    "foreign-key field named like the API field (Payment.order_id) or, for many_to_many, a "
    "junction entity. Propose a missing relation as kind=link. For actions, propose kind=rules "
    "with preconditions ({field: Entity.field, op: eq|ne|in|not_in|gt|gte|lt|lte|is_null|not_null, "
    "value, message}) and effects ({kind: set_field, field, values} / create_object / "
    "create_link with link_id) when the model lacks them — take them from the API behaviour "
    "or the requirement; enum values must be the field's enum values."
)


def build_entries(db) -> list[Entry]:
    def validate_structure(out: StructureOut, ctx: dict) -> list[str]:
        ids = {str(i.node_id) for i in out.items if i.node_id}
        ids |= {
            str(i.suggestion.node_id)
            for i in out.items
            if i.suggestion is not None and i.suggestion.kind in ("attribute", "field", "io")
        }
        ids |= {str(s.node_id) for s in out.io_suggestions}
        errors = _check_nodes(db, ctx["sut_id"], ids)
        errors += _check_fields(db, ctx["sut_id"], {str(i.attribute_id) for i in out.items if i.attribute_id})
        errors += _check_links(db, ctx["sut_id"], {str(i.link_id) for i in out.items if i.link_id})
        suggestions = [i.suggestion for i in out.items] + list(out.io_suggestions)
        errors += _check_link_rules(db, ctx["sut_id"], suggestions)
        errors += _check_field_owners(db, ctx["sut_id"], suggestions)
        errors += _check_io_owners(db, ctx["sut_id"], suggestions)
        errors += _check_enum(suggestions)
        return errors

    def validate_complete(out: CompleteOut, ctx: dict) -> list[str]:
        ids = {str(s.node_id) for s in out.suggestions if s.kind in ("attribute", "field", "io")}
        errors = _check_nodes(db, ctx["sut_id"], ids)
        errors += _check_field_owners(db, ctx["sut_id"], out.suggestions)
        errors += _check_io_owners(db, ctx["sut_id"], out.suggestions)
        errors += _check_enum(out.suggestions)
        errors += _check_link_rules(db, ctx["sut_id"], out.suggestions)
        req_ids = {str(s.requirement_id) for s in out.suggestions if s.requirement_id}
        if req_ids:
            with db.tx() as cur:
                cur.execute(
                    "SELECT r.id::text AS id FROM requirement r JOIN version v ON v.id=r.version_id"
                    " WHERE r.id = ANY(%s::uuid[]) AND v.sut_id=%s",
                    (list(req_ids), ctx["sut_id"]),
                )
                valid = {r["id"] for r in cur.fetchall()}
            errors += [f"requirement_id {r} does not exist" for r in sorted(req_ids - valid)]
        return errors

    model_tools = (
        "list_nodes",
        "get_node",
        "search_nodes",
        "get_graph_neighbors",
        "list_fields",
        "list_links",
        "list_apis",
        "get_api_schema",
    )
    return [
        Entry(
            name="structure_requirement",
            output_schema=StructureOut,
            tools=(*model_tools, "get_requirement", "search_memory"),
            template="system",
            instructions=(
                "Break the requirement into actor / condition / action / result / constraint "
                "items. The input `model` lists every node of the current system with its "
                "fields; link each item to an existing node (node_id) and, when the item is "
                "about a value such as an amount or a status, also to the entity field "
                "(attribute_id, e.g. PurchaseOrder.amount). Prefer existing nodes even when the wording "
                "differs (Approver = approval role, Create purchase order = submit order). Only when nothing fits, set "
                "missing=true and propose a suggestion: a field on an existing entity "
                "(kind=field), an attribute on an existing node (conditions/states/constraints) "
                "or, last, a new entity/action node. Never invent IDs. A new field always has a "
                "data_type (enum with enum_values, reference for links to another entity). For "
                "every linked action whose inputs/outputs are empty in `model`, add an "
                "io_suggestion: its purpose (description), inputs and outputs (name, "
                "display_name, data_type, required, format, field = Entity.field when it maps to an "
                "entity field) and the input/output format — take them from its linked API "
                "(get_api_schema) when it has one; a new action suggestion carries the same. An "
                "item about a relation between entities links to it with link_id. " + FIELD_NAMES + LINKS_AND_RULES
            ),
            validate=validate_structure,
        ),
        Entry(
            name="complete_model",
            output_schema=CompleteOut,
            tools=(*model_tools, "list_requirements", "get_requirement", "search_memory"),
            template="system",
            instructions=(
                "Compare the requirements with the model (input `model`, with entity fields) and "
                "propose what is missing: fields on existing entities (kind=field), attributes "
                "(conditions, states, constraints) on existing nodes, and only then new "
                "entity/action nodes. Do not repeat nodes, fields or attributes that already "
                "exist, and do not propose a node whose meaning duplicates an existing one. "
                "Every field needs a data_type (enum with enum_values; reference for a link to "
                "another entity). For actions without inputs/outputs or purpose propose kind=io "
                "with description (what the action does), inputs, outputs (name, display_name, "
                "data_type, required, format, field = Entity.field when it maps to an entity field) "
                "and input_format/output_format; use the linked API's schema (get_api_schema). "
                + FIELD_NAMES
                + LINKS_AND_RULES
            ),
            validate=validate_complete,
        ),
    ]


class AiTaskService:
    def __init__(self, db, bus: EventBus, runtime: AgentRuntime):
        self.db = db
        self.bus = bus
        self.runtime = runtime

    @staticmethod
    def _summary(run: dict) -> dict:
        return {
            "agent_run_id": str(run["id"]),
            "status": run["status"],
            "error_code": run["error_code"],
        }

    def structure_requirement(self, req_id) -> dict:
        reqs = RequirementService(self.db, self.bus)
        with self.db.tx() as cur:
            req = reqs._req(cur, req_id, editable=True)
        run = self.runtime.run(
            "structure_requirement",
            {
                "requirement_id": str(req_id),
                "version_id": str(req["version_id"]),
                "code": req["code"],
                "title": req["title"],
                "text": req["raw_text"],
                "model": model_catalog(self.db, req["sut_id"]),
            },
            sut_id=req["sut_id"],
            context={"requirement": {"code": req["code"], "title": req["title"]}},
        )
        result = self._summary(run)
        if run["status"] != "succeeded":
            return result
        out = StructureOut.model_validate(run["result"])
        actor = f"agent:{run['id']}"
        structure: dict = {p: [] for p in PARTS}
        suggestions = []
        for item in out.items:
            node_id = str(item.node_id) if item.node_id else None
            attr_id = str(item.attribute_id) if item.attribute_id else None
            sugg = item.suggestion if item.missing else None
            if item.missing and (sugg is None or sugg.kind == "node"):
                default_kind = {"actor": "entity", "action": "action"}.get(item.part)
                kind = sugg.node_kind if sugg is not None else default_kind
                name = sugg.name if sugg is not None else item.text
                similar = None
                if kind:
                    with self.db.tx() as cur:  # 7(d): link an existing similar node instead
                        similar = find_similar_node(cur, req["sut_id"], kind, name)
                if similar is not None:
                    node_id, sugg = str(similar["id"]), None
                elif sugg is None and kind:
                    sugg = NodeSuggestion(node_kind=kind, name=item.text)
            entry = {"text": item.text, "node_id": node_id}
            if attr_id:
                entry["attribute_id"] = attr_id
            if item.link_id:
                entry["link_id"] = str(item.link_id)
            structure[item.part].append(entry)
            if node_id is None and attr_id is None and not item.link_id and sugg is not None:
                data = sugg.model_dump(mode="json")
                data.update(requirement_id=str(req_id), part=item.part, source_text=item.text)
                suggestions.append(data)
        for io in out.io_suggestions:
            data = io.model_dump(mode="json")
            data.update(requirement_id=str(req_id))
            suggestions.append(data)
        with self.db.tx() as cur:
            req = reqs._req(cur, req_id, editable=True, lock=True)
            reqs._write_structure(cur, req, structure, agent_run_id=run["id"])
            created = SuggestionService(self.db, self.bus).add_many(
                cur, req["sut_id"], suggestions, agent_run_id=run["id"]
            )
            log_change(cur, "requirement", req_id, "structure", actor, structure)
        self.bus.publish("requirement.structured", {"id": str(req_id), "agent_run_id": result["agent_run_id"]})
        return {**result, "requirement": reqs.detail(req_id), "suggestions": created}

    def complete_model(self, sut_id, version_id=None) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT 1 FROM sut WHERE id=%s", (sut_id,))
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "SUT not found")
        inputs = {
            "sut_id": str(sut_id),
            "version_id": str(version_id) if version_id else None,
            "model": model_catalog(self.db, sut_id),
        }
        run = self.runtime.run("complete_model", inputs, sut_id=sut_id)
        result = self._summary(run)
        if run["status"] != "succeeded":
            return result
        out = CompleteOut.model_validate(run["result"])
        items = [s.model_dump(mode="json") for s in out.suggestions]
        with self.db.tx() as cur:
            created = SuggestionService(self.db, self.bus).add_many(cur, sut_id, items, agent_run_id=run["id"])
        return {**result, "suggestions": created, "skipped": len(items) - len(created)}
