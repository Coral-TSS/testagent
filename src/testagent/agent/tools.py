"""Tool registry (EP-07). Entries see only their whitelisted tools; `submit_result` is the only
write path and is handled by the runtime, not registered here."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from testagent.core.errors import AppError
from testagent.services.apis import ApiService
from testagent.services.cases import CaseService
from testagent.services.model import ModelService


@dataclass
class ToolSpec:
    name: str
    group: str
    description: str
    args_schema: type[BaseModel]
    func: Callable[..., Any]
    writes: bool = False
    needs_ctx: bool = False
    """Called as func(ctx=..., **args); ctx carries run inputs and per-run resources."""


@dataclass
class ToolRegistry:
    tools: dict[str, ToolSpec] = field(default_factory=dict)
    resolver: Callable[[str, dict, dict], dict] | None = None
    """Normalizes tool arguments before a call: fills the run's current sut/version and turns
    codes/names (REQ-001, TC-002, a SUT code, a node name) into IDs."""

    def resolve(self, name: str, args: dict, ctx: dict) -> dict:
        return self.resolver(name, args, ctx) if self.resolver else args

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self.tools:
            raise ValueError(f"tool {spec.name} already registered")
        if spec.name == "submit_result":
            raise ValueError("submit_result is reserved")
        self.tools[spec.name] = spec

    def names(self) -> list[str]:
        return sorted(self.tools)

    def subset(self, names: tuple[str, ...] | list[str]) -> dict[str, ToolSpec]:
        unknown = [n for n in names if n not in self.tools]
        if unknown:
            raise KeyError(f"unknown tools: {unknown}")
        return {n: self.tools[n] for n in names}

    @staticmethod
    def as_langchain(spec: ToolSpec) -> StructuredTool:
        return StructuredTool.from_function(
            func=spec.func,
            name=spec.name,
            description=spec.description,
            args_schema=spec.args_schema,
        )


def to_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


# ---------------------------------------------------------------- id resolution
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def is_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value.strip()))


def _sid(ctx: dict) -> str | None:
    return str(ctx["sut_id"]) if ctx.get("sut_id") else None


class IdResolver:
    """Agents often pass a code where a UUID is expected (DeepSeek: get_requirement("REQ-001"),
    list_apis(sut_id=<version id>)). A run bound to a system always works inside that system."""

    def __init__(self, db):
        self.db = db

    def _one(self, sql: str, params: tuple) -> str | None:
        with self.db.tx() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return str(row["id"]) if row else None

    def version_of(self, ctx: dict) -> str | None:
        if "version_id" in ctx:
            return ctx["version_id"]
        inputs = ctx.get("inputs") or {}
        version = inputs.get("version_id")
        if not version and inputs.get("requirement_id"):
            version = self._one(
                "SELECT version_id AS id FROM requirement WHERE id::text=%s",
                (str(inputs["requirement_id"]),),
            )
        ctx["version_id"] = str(version) if version else None
        return ctx["version_id"]

    def sut(self, value: Any, ctx: dict) -> str:
        if ctx.get("sut_id"):
            return str(ctx["sut_id"])  # never leave the run's system
        text = str(value or "").strip()
        if not text:
            raise AppError("VALIDATION", "sut_id is required (no current system for this run)")
        found = self._one("SELECT id FROM sut WHERE id::text=%s OR lower(code)=lower(%s)", (text, text))
        if found is None:
            raise AppError("NOT_FOUND", f"SUT not found: {text} (pass the SUT code or UUID)")
        return found

    def version(self, value: Any, ctx: dict) -> str:
        text = str(value or "").strip()
        if not text:
            current = self.version_of(ctx)
            if current is None:
                raise AppError("VALIDATION", "version_id is required (no current version)")
            return current
        if is_uuid(text):
            return text
        found = self._one(
            "SELECT id FROM version WHERE sut_id::text=%s AND lower(name)=lower(%s)",
            (_sid(ctx), text),
        )
        if found is None:
            raise AppError("NOT_FOUND", f"Version not found: {text}")
        return found

    def requirement(self, value: Any, ctx: dict) -> str:
        text = str(value or "").strip()
        if is_uuid(text):
            return text
        version = self.version_of(ctx)
        found = self._one(
            "SELECT r.id FROM requirement r JOIN version v ON v.id=r.version_id"
            " WHERE upper(r.code)=upper(%s) AND (%s::text IS NULL OR r.version_id::text=%s)"
            " AND (%s::text IS NULL OR v.sut_id::text=%s) ORDER BY r.created_at DESC LIMIT 1",
            (text, version, version, _sid(ctx), _sid(ctx)),
        )
        if found is None:
            raise AppError(
                "NOT_FOUND", f"Requirement not found: {text} (pass a requirement code such as REQ-001 or a UUID)"
            )
        return found

    def case(self, value: Any, ctx: dict) -> str:
        text = str(value or "").strip()
        if is_uuid(text):
            return text
        found = self._one(
            "SELECT id FROM test_case WHERE upper(code)=upper(%s) AND (%s::text IS NULL OR sut_id::text=%s)",
            (text, _sid(ctx), _sid(ctx)),
        )
        if found is None:
            raise AppError("NOT_FOUND", f"Test case not found: {text} (pass a case code such as TC-001 or a UUID)")
        return found

    def node(self, value: Any, ctx: dict) -> str:
        text = str(value or "").strip()
        if is_uuid(text):
            return text
        found = self._one(
            "SELECT id FROM model_node WHERE lower(name)=lower(%s) AND deleted_at IS NULL"
            " AND (%s::text IS NULL OR sut_id::text=%s) ORDER BY kind LIMIT 1",
            (text, _sid(ctx), _sid(ctx)),
        )
        if found is None:
            raise AppError("NOT_FOUND", f"Node not found: {text} (pass a node name or UUID)")
        return found

    def __call__(self, name: str, args: dict, ctx: dict) -> dict:
        out = dict(args)
        if "sut_id" in out or name in SUT_SCOPED:
            if ctx.get("sut_id") or out.get("sut_id"):
                out["sut_id"] = self.sut(out.get("sut_id"), ctx)
            elif name in SUT_OPTIONAL:
                out.pop("sut_id", None)
            else:
                out["sut_id"] = self.sut(None, ctx)
        if "version_id" in out or name in VERSION_SCOPED:
            out["version_id"] = self.version(out.get("version_id"), ctx)
        if out.get("requirement_id"):
            out["requirement_id"] = self.requirement(out["requirement_id"], ctx)
        if out.get("case_id"):
            out["case_id"] = self.case(out["case_id"], ctx)
        if out.get("node_id"):
            out["node_id"] = self.node(out["node_id"], ctx)
        return out


SUT_SCOPED = {"list_nodes", "search_nodes", "list_apis", "list_cases", "list_fields", "list_links"}
SUT_OPTIONAL = {"search_memory"}
VERSION_SCOPED = {"list_requirements", "get_coverage"}


# ---------------------------------------------------------------- read tools
SUT_DESC = "optional: defaults to the current system; a system code also works"


class SutArgs(BaseModel):
    sut_id: str | None = Field(default=None, description=SUT_DESC)


class NodeArgs(BaseModel):
    node_id: str = Field(description="node UUID or exact node name")


class SearchNodesArgs(BaseModel):
    query: str = Field(description="name/description substring")
    kind: str | None = Field(default=None, description="entity|action|relation")
    sut_id: str | None = Field(default=None, description=SUT_DESC)


class NeighborArgs(BaseModel):
    node_id: str = Field(description="node UUID or exact node name")
    depth: int = Field(default=1, ge=1, le=5)


class RequirementArgs(BaseModel):
    requirement_id: str = Field(description="requirement UUID or code such as REQ-001")


class VersionArgs(BaseModel):
    version_id: str | None = Field(
        default=None, description="optional: defaults to the current version; name also works"
    )


class CaseListArgs(BaseModel):
    sut_id: str | None = Field(default=None, description=SUT_DESC)
    requirement_id: str | None = Field(default=None, description="UUID or code such as REQ-001")


class CaseArgs(BaseModel):
    case_id: str = Field(description="case UUID or code such as TC-001")


class MemoryArgs(BaseModel):
    query: str
    sut_id: str | None = None


class ApiSchemaArgs(BaseModel):
    api: str = Field(description='API UUID or "METHOD /path", e.g. "POST /orders"')


def _field(f: dict) -> dict:
    keys = ("id", "name", "display_name", "data_type", "unit", "format", "enum_values")
    out = {k: f.get(k) for k in keys}
    if f.get("required"):
        out["required"] = True
    if f.get("ref_node_name"):
        out["references"] = f["ref_node_name"]
    if f.get("storage_name"):
        out["storage_name"] = f["storage_name"]
    if f.get("constraints"):
        out["constraints"] = f["constraints"]
    return {k: v for k, v in out.items() if v not in (None, [])}


def _param(p: dict) -> dict:
    """Compact action/API parameter for prompts."""
    keys = ("name", "display_name", "data_type", "location", "format", "enum_values", "field")
    out = {k: p.get(k) for k in keys}
    if p.get("required"):
        out["required"] = True
    if p.get("description"):
        out["description"] = p["description"][:200]
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def _io(node: dict) -> dict:
    """Purpose, inputs, outputs and formats of an action (empty keys dropped)."""
    out = {
        "inputs": [_param(p) for p in node.get("inputs") or []],
        "outputs": [_param(p) for p in node.get("outputs") or []],
        "input_format": node.get("input_format"),
        "output_format": node.get("output_format"),
    }
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def _rules(node: dict, link_names: dict[str, str] | None = None) -> dict:
    """Preconditions / effects of an action as readable lines."""
    from testagent.services.action_rules import effect_text, precondition_text

    out = {}
    pre = [precondition_text(p) for p in node.get("preconditions") or []]
    if pre:
        out["preconditions"] = pre
    eff = [effect_text(e, link_names) for e in node.get("effects") or []]
    if eff:
        out["effects"] = eff
    return out


def _link_names(cur, sut_id) -> dict[str, str]:
    from testagent.services.links import LinkService

    return {
        str(lk["id"]): f"{lk['from_name']} {lk['forward_name']} {lk['to_name']}"
        for lk in LinkService.list_rows(cur, sut_id)
    }


def link_summaries(db, sut_id) -> list[dict]:
    """Links between entities (both readings, cardinality, foreign key / junction entity)."""
    from testagent.services.links import LinkService, link_summary

    with db.tx() as cur:
        return [link_summary(lk) for lk in LinkService.list_rows(cur, sut_id)]


def _slim(node: dict, fields: list[dict] | None = None, links: dict | None = None) -> dict:
    keys = ("id", "kind", "name", "description", "module_id", "attributes")
    out = {k: node.get(k) for k in keys}
    if fields:
        out["fields"] = [_field(f) for f in fields]
    if node.get("kind") == "action":
        out.update(_io(node))
        out.update(_rules(node, links))
    return out


def body_fields(request_schema: dict | None) -> dict | None:
    """{"required": [...], "properties": {name: type}} summary of a JSON request body."""
    body = (request_schema or {}).get("body")
    if not isinstance(body, dict) or not isinstance(body.get("properties"), dict):
        return None
    props = {}
    for name, prop in body["properties"].items():
        types = prop.get("type") or [a.get("type") for a in prop.get("anyOf", []) if a.get("type")]
        props[name] = types
    return {
        "required": body.get("required", []),
        "properties": props,
        "extra_allowed": body.get("additionalProperties", True) is not False,
    }


def api_summaries(db, sut_id, limit: int = 40) -> list[dict]:
    """Registered APIs with purpose, request-body fields and response fields, injected into
    case generation/automation."""
    from testagent.services.io_spec import api_io

    with db.tx() as cur:
        cur.execute(
            "SELECT method, path, name, description, request_schema, response_schema,"
            " request_content_type, response_content_type FROM api_endpoint"
            " WHERE sut_id=%s ORDER BY path, method",
            (sut_id,),
        )
        rows = cur.fetchall()
    out = []
    for r in rows[:limit]:
        item = {"method": r["method"], "path": r["path"], "name": r["name"]}
        if r["description"]:
            item["purpose"] = r["description"][:300]
        body = body_fields(r["request_schema"])
        if body:
            item["body"] = body
        io = api_io(r)
        if io["outputs"]:
            item["response_fields"] = {p["name"]: p["data_type"] for p in io["outputs"]}
        if io["output_format"]:
            item["response_format"] = io["output_format"]
        if not (r["request_schema"] or r["response_schema"]):
            item["schema"] = "unknown"
        out.append(item)
    return out


def action_summaries(db, sut_id, node_ids: list | None = None, limit: int = 40) -> list[dict]:
    """Actions with purpose, inputs/outputs (bound to Entity.field) and linked APIs; injected into
    case generation (all actions of the system) and automation (the case's actions)."""
    with db.tx() as cur:
        cur.execute(
            "SELECT n.id, n.name, n.description, n.inputs, n.outputs, n.input_format,"
            " n.output_format, n.preconditions, n.effects,"
            " coalesce(array_agg(a.method || ' ' || a.path ORDER BY a.path)"
            "   FILTER (WHERE a.id IS NOT NULL), '{}') AS apis"
            " FROM model_node n"
            " LEFT JOIN node_api_link l ON l.node_id=n.id AND l.invalid_at IS NULL"
            " LEFT JOIN api_endpoint a ON a.id=l.api_id"
            " WHERE n.sut_id=%s AND n.kind='action' AND n.deleted_at IS NULL"
            " AND (%s::uuid[] IS NULL OR n.id = ANY(%s::uuid[]))"
            " GROUP BY n.id ORDER BY n.name",
            (sut_id, node_ids, node_ids),
        )
        rows = cur.fetchall()
        names = _link_names(cur, sut_id)
    out = []
    for r in rows[:limit]:
        item = {"action": r["name"]}
        if r["description"]:
            item["purpose"] = r["description"][:300]
        item.update(_io(r))
        item.update(_rules(r, names))
        if r["apis"]:
            item["apis"] = r["apis"]
        out.append(item)
    return out


API_REF = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s, . ,;; ))\]'\"]*)")


def check_request_bodies(db, sut_id, steps: list[tuple[str, str, str | None]]) -> list[str]:
    """steps: (label, action text, data text). A step naming "METHOD /path" of an API with a
    known JSON body schema must send only known fields and all required ones (5a)."""
    with db.tx() as cur:
        cur.execute(
            "SELECT method, path, request_schema FROM api_endpoint WHERE sut_id=%s AND request_schema ? 'body'",
            (sut_id,),
        )
        apis = cur.fetchall()
    if not apis:
        return []
    compiled = [(a, re.compile("^" + re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(a["path"])) + "/?$")) for a in apis]
    errors = []
    for label, action, data in steps:
        match = API_REF.search(action or "") or API_REF.search(data or "")
        if not match or not data:
            continue
        method, path = match.group(1), match.group(2).split("?")[0]
        api = next((a for a, rx in compiled if a["method"] == method and rx.match(path)), None)
        if api is None:
            continue
        try:
            body = json.loads(data)
        except (TypeError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        summary = body_fields(api["request_schema"]) or {}
        props = summary.get("properties", {})
        unknown = [k for k in body if k not in props]
        missing = [k for k in summary.get("required", []) if k not in body]
        if unknown or missing:
            errors.append(
                f"{label}: body for {method} {api['path']} does not match its schema"
                + (f"; unknown fields {unknown}" if unknown else "")
                + (f"; missing required {missing}" if missing else "")
                + f"; allowed fields {props} (use get_api_schema)"
            )
    return errors


def model_catalog(db, sut_id) -> dict:
    """Compact model summary injected into structuring/completion inputs (names, not just IDs)."""
    from testagent.services.attributes import AttributeService

    with db.tx() as cur:
        cur.execute("SELECT code, name FROM sut WHERE id=%s", (sut_id,))
        sut = cur.fetchone()
        cur.execute(
            "SELECT id, kind, name, description, inputs, outputs, input_format, output_format,"
            " preconditions, effects FROM model_node WHERE sut_id=%s AND deleted_at IS NULL"
            " AND kind <> 'relation' ORDER BY kind, name",
            (sut_id,),
        )
        nodes = cur.fetchall()
        cur.execute(
            "SELECT l.node_id, a.method || ' ' || a.path AS api FROM node_api_link l"
            " JOIN api_endpoint a ON a.id=l.api_id WHERE a.sut_id=%s AND l.invalid_at IS NULL",
            (sut_id,),
        )
        linked: dict[str, list] = {}
        for row in cur.fetchall():
            linked.setdefault(str(row["node_id"]), []).append(row["api"])
        fields = AttributeService(db, None).list_for_sut(sut_id, cur=cur)
        names = _link_names(cur, sut_id)
    by_node: dict[str, list] = {}
    for f in fields:
        by_node.setdefault(str(f["node_id"]), []).append(_field(f))
    return {
        "system": {"id": str(sut_id), **(sut or {})},
        "nodes": [
            {
                "id": str(n["id"]),
                "kind": n["kind"],
                "name": n["name"],
                **({"description": n["description"]} if n["description"] else {}),
                **({"fields": by_node[str(n["id"])]} if str(n["id"]) in by_node else {}),
                **(_io(n) if n["kind"] == "action" else {}),
                **(_rules(n, names) if n["kind"] == "action" else {}),
                **({"apis": linked[str(n["id"])]} if str(n["id"]) in linked else {}),
            }
            for n in nodes
        ],
        "links": link_summaries(db, sut_id),
    }


def register_read_tools(registry: ToolRegistry, db, bus) -> ToolRegistry:
    from testagent.services.attributes import AttributeService

    model = ModelService(db, bus, actor="agent")
    apis = ApiService(db, bus, actor="agent")
    attrs = AttributeService(db, bus, actor="agent")
    registry.resolver = IdResolver(db)

    def fields_by_node(sut_id) -> dict[str, list]:
        out: dict[str, list] = {}
        for f in attrs.list_for_sut(sut_id):
            out.setdefault(str(f["node_id"]), []).append(f)
        return out

    def list_nodes(sut_id: str | None = None) -> str:
        fields = fields_by_node(sut_id)
        with db.tx() as cur:
            names = _link_names(cur, sut_id)
        return to_text([_slim(n, fields.get(str(n["id"])), names) for n in model.list_nodes(sut_id)])

    def get_node(node_id: str) -> str:
        from testagent.services.links import link_summary

        node = model.get_node(node_id)
        with db.tx() as cur:
            names = _link_names(cur, node["sut_id"])
        return to_text(
            {
                **_slim(node, node.get("fields"), names),
                **({"links": [link_summary(lk) for lk in node["links"]]} if node["links"] else {}),
                "edges": [
                    {
                        "role": e["role"],
                        "source": e["source_name"],
                        "target": e["target_name"],
                    }
                    for e in node["edges"]
                ],
                "apis": [
                    {
                        "id": str(a["id"]),
                        "method": a["method"],
                        "path": a["path"],
                        "name": a["name"],
                        **({"purpose": a["description"]} if a.get("description") else {}),
                    }
                    for a in node["apis"]
                ],
            }
        )

    def search_nodes(query: str, kind: str | None = None, sut_id: str | None = None) -> str:
        fields = fields_by_node(sut_id)
        rows = model.list_nodes(sut_id, kind=kind, q=query)
        seen = {str(r["id"]) for r in rows}
        for f in attrs.list_for_sut(sut_id):  # a field match returns its entity
            hay = f"{f['name']} {f.get('display_name') or ''}".lower()
            if query.lower() in hay and str(f["node_id"]) not in seen:
                rows += [n for n in model.list_nodes(sut_id) if str(n["id"]) == str(f["node_id"])]
                seen.add(str(f["node_id"]))
        with db.tx() as cur:
            names = _link_names(cur, sut_id)
        return to_text([_slim(n, fields.get(str(n["id"])), names) for n in rows])

    def get_graph_neighbors(node_id: str, depth: int = 1) -> str:
        return to_text(model.neighbors(node_id, depth))

    def list_fields(sut_id: str | None = None) -> str:
        return to_text(
            [
                {**_field(f), "entity": f["node_name"], "entity_id": str(f["node_id"])}
                for f in attrs.list_for_sut(sut_id)
            ]
        )

    def list_links(sut_id: str | None = None) -> str:
        return to_text(link_summaries(db, sut_id))

    def list_apis(sut_id: str | None = None) -> str:
        rows = apis.list_for_sut(sut_id)
        out = []
        for r in rows:
            item = {k: r[k] for k in ("id", "method", "path", "name", "node_names")}
            if r.get("description"):
                item["purpose"] = r["description"][:300]
            item["has_schema"] = bool(r.get("request_schema") or r.get("response_schema"))
            body = body_fields(r.get("request_schema"))
            if body:
                item["body"] = body
            out.append(item)
        return to_text(out)

    def get_api_schema(api: str, ctx: dict) -> str:
        sut_id = ctx.get("sut_id")
        text = api.strip()
        with db.tx() as cur:
            if is_uuid(text):
                cur.execute("SELECT * FROM api_endpoint WHERE id=%s", (text,))
            else:
                method, _, path = text.partition(" ")
                cur.execute(
                    "SELECT * FROM api_endpoint WHERE upper(method)=upper(%s) AND path=%s"
                    " AND (%s::uuid IS NULL OR sut_id=%s)",
                    (method, path.strip(), sut_id, sut_id),
                )
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", f"API not found: {text} (use list_apis first)")
        from testagent.services.io_spec import api_io

        io = api_io(row)
        return to_text(
            {
                "id": str(row["id"]),
                "method": row["method"],
                "path": row["path"],
                "name": row["name"],
                "purpose": row["description"],
                "request_content_type": row["request_content_type"],
                "response_content_type": row["response_content_type"],
                "request_fields": [_param(p) for p in io["inputs"]],
                "response_fields": [_param(p) for p in io["outputs"]],
                "input_format": io["input_format"],
                "output_format": io["output_format"],
                "request": row["request_schema"],
                "responses": row["response_schema"],
                "note": None
                if row["request_schema"] or row["response_schema"]
                else "no schema registered; import the system's OpenAPI in the API registry",
            }
        )

    def get_requirement(requirement_id: str) -> str:
        with db.tx() as cur:
            cur.execute(
                "SELECT r.id, r.version_id, v.sut_id, v.name AS version, r.code, r.title,"
                " r.raw_text, r.structured, r.priority, r.status FROM requirement r"
                " JOIN version v ON v.id=r.version_id WHERE r.id=%s",
                (requirement_id,),
            )
            return to_text(cur.fetchone())

    def list_requirements(version_id: str | None = None) -> str:
        with db.tx() as cur:
            cur.execute(
                "SELECT id, code, title, priority, status FROM requirement WHERE version_id=%s ORDER BY code",
                (version_id,),
            )
            return to_text(cur.fetchall())

    def get_requirement_people(requirement_id: str) -> str:
        with db.tx() as cur:
            cur.execute(
                "SELECT p.id, p.name, rp.role FROM requirement_person rp"
                " JOIN person p ON p.id=rp.person_id WHERE rp.requirement_id=%s"
                " ORDER BY rp.role, p.name",
                (requirement_id,),
            )
            return to_text(cur.fetchall())

    cases = CaseService(db, bus, actor="agent")

    def list_cases(sut_id: str | None = None, requirement_id: str | None = None) -> str:
        rows = cases.list(sut_id, requirement_id=requirement_id)
        keys = ("id", "code", "title", "test_point", "scenario", "status", "requirement_codes")
        return to_text([{k: r[k] for k in keys} for r in rows if r["status"] != "deprecated"])

    def get_case(case_id: str) -> str:
        return to_text(cases.get(case_id))

    def get_coverage(version_id: str | None = None) -> str:
        return to_text(cases.coverage(version_id))

    def search_memory(query: str, sut_id: str | None = None) -> str:
        with db.tx() as cur:
            cur.execute(
                "SELECT id, scope, content, tags FROM agent_memory WHERE enabled"
                " AND (scope='global' OR sut_id=%s) AND content ILIKE %s"
                " ORDER BY created_at DESC LIMIT 20",
                (sut_id, f"%{query}%"),
            )
            return to_text(cur.fetchall())

    for name, group, desc, schema, func in [
        (
            "list_nodes",
            "model",
            "List all model nodes (with entity fields) of the system.",
            SutArgs,
            list_nodes,
        ),
        (
            "get_node",
            "model",
            "Get a node: entity fields and links, or action purpose/inputs/outputs, "
            "preconditions/effects, edges, linked APIs.",
            NodeArgs,
            get_node,
        ),
        (
            "search_nodes",
            "model",
            "Search nodes by name/description or by a field name (e.g. amount).",
            SearchNodesArgs,
            search_nodes,
        ),
        (
            "get_graph_neighbors",
            "model",
            "Nodes reachable within depth (1-5).",
            NeighborArgs,
            get_graph_neighbors,
        ),
        (
            "list_fields",
            "model",
            "List entity fields (entity.field) of the system.",
            SutArgs,
            list_fields,
        ),
        (
            "list_links",
            "model",
            "List links (relations) between entities: both readings with their prepositions "
            "(PurchaseOrder belongs to Supplier / Supplier supplies PurchaseOrder), cardinality (1:1, N:1, 1:N, M:N), "
            "required, foreign-key field or junction entity.",
            SutArgs,
            list_links,
        ),
        (
            "list_apis",
            "model",
            "List registered APIs of the system (purpose, request body fields when known).",
            SutArgs,
            list_apis,
        ),
        (
            "get_requirement",
            "requirement",
            "Get one requirement.",
            RequirementArgs,
            get_requirement,
        ),
        (
            "list_requirements",
            "requirement",
            "List requirements of a version.",
            VersionArgs,
            list_requirements,
        ),
        (
            "get_requirement_people",
            "requirement",
            "People responsible for a requirement (owner/developer/tester).",
            RequirementArgs,
            get_requirement_people,
        ),
        (
            "list_cases",
            "case",
            "List test cases of the system (optionally one requirement).",
            CaseListArgs,
            list_cases,
        ),
        ("get_case", "case", "Get one test case with links.", CaseArgs, get_case),
        (
            "get_coverage",
            "case",
            "Coverage of a version's requirements/actions/fields.",
            VersionArgs,
            get_coverage,
        ),
        ("search_memory", "memory", "Search enabled agent memories.", MemoryArgs, search_memory),
    ]:
        registry.register(ToolSpec(name, group, desc, schema, func))
    registry.register(
        ToolSpec(
            "get_api_schema",
            "model",
            "Request/response JSON schema of one API. Request bodies MUST follow it exactly.",
            ApiSchemaArgs,
            get_api_schema,
            needs_ctx=True,
        )
    )
    return registry
