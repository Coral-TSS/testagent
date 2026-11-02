"""Ontology model: entity / action nodes, edges, link types, references, graph queries, snapshots.

Relations are link types (services/links.py); legacy relation nodes are archived."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.attributes import AttributeService
from testagent.services.changelog import log_change
from testagent.services.io_spec import validate_params
from testagent.services.links import LinkService

KINDS = ("entity", "action", "relation")
END_ROLES = ("source", "target")
MAX_DEPTH = 5
NODE_COLUMNS = (
    "id, sut_id, module_id, kind, name, description, data_schema, attributes, code_ref, "
    "inputs, outputs, input_format, output_format, preconditions, effects, deleted_at,"
    " created_at, updated_at"
)
RULE_KEYS = ("preconditions", "effects")
RELATION_GONE = (
    "Links are no longer nodes: create a link under “Links” in the model "
    "(both side names, cardinality, foreign-key field)"
)
IO_KEYS = ("inputs", "outputs", "input_format", "output_format")


class AttrItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    expr: str | None = Field(default=None, max_length=2000)


class NodeAttributes(BaseModel):
    """Conditions, states and constraints are node attributes (not separate nodes)."""

    model_config = ConfigDict(extra="forbid")
    conditions: list[AttrItem] = Field(default_factory=list)
    states: list[AttrItem] = Field(default_factory=list)
    constraints: list[AttrItem] = Field(default_factory=list)


def validate_attributes(raw: Any) -> dict:
    try:
        return NodeAttributes.model_validate(raw or {}).model_dump(exclude_none=True)
    except ValidationError as exc:
        fields = [{"field": "attributes." + ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise AppError("VALIDATION", "Invalid node attributes", field_errors=fields) from exc


_PAREN = re.compile(r"[ ((][^))]*[))]")
_NOISE = re.compile(r"[\s/\\_\-·, , ,. .:: ]+")


def normalize_name(name: str) -> str:
    """'Approver (approval role)' → 'Approver'; used to avoid duplicate nodes (7d)."""
    text = _PAREN.sub("", str(name or ""))
    return _NOISE.sub("", text).lower()


def find_similar_node(cur, sut_id, kind: str | None, name: str) -> dict | None:
    """Existing node with the same normalized name, else one whose name contains / is contained
    in the other (min 2 chars). Exact matches win; then the closest length."""
    wanted = normalize_name(name)
    if len(wanted) < 2:
        return None
    cur.execute(
        "SELECT id, kind, name FROM model_node WHERE sut_id=%s AND deleted_at IS NULL"
        " AND (%s::text IS NULL OR kind=%s)",
        (sut_id, kind, kind),
    )
    best, best_score = None, None
    for row in cur.fetchall():
        have = normalize_name(row["name"])
        if len(have) < 2:
            continue
        if have == wanted:
            return row
        if wanted in have or have in wanted:
            score = abs(len(have) - len(wanted))
            if best_score is None or score < best_score:
                best, best_score = row, score
    return best


def _dumps(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False, sort_keys=True)


def _j(value):
    return None if value is None else Jsonb(value, dumps=_dumps)


def check_rules(cur, sut_id, kind: str, data: dict) -> dict:
    """Preconditions / effects (actions only)."""
    from testagent.services.action_rules import validate_rules

    if not any(k in data for k in RULE_KEYS):
        return {}
    out = validate_rules(cur, sut_id, {k: data[k] for k in RULE_KEYS if k in data})
    if kind != "action" and any(out.values()):
        raise AppError(
            "VALIDATION",
            "Only action nodes can have preconditions/effects",
            field_errors=[{"field": "preconditions"}],
        )
    return out


def check_io(cur, sut_id, kind: str, data: dict, *, strict: bool = True) -> dict:
    """Validate inputs/outputs/formats in `data` (only actions may have them)."""
    out = {}
    for key in ("inputs", "outputs"):
        if key in data:
            out[key] = validate_params(cur, sut_id, data[key], key, strict=strict)
    for key in ("input_format", "output_format"):
        if key in data:
            text = (data[key] or "").strip() or None
            out[key] = text[:500] if text else None
    if kind != "action" and (out.get("inputs") or out.get("outputs")):
        raise AppError("VALIDATION", "Only action nodes can have inputs/outputs", field_errors=[{"field": "inputs"}])
    return out


class ModelService:
    def __init__(self, db, bus: EventBus, actor: str = "local-user"):
        self.db = db
        self.bus = bus
        self.actor = actor

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _node(cur, node_id, *, sut_id=None, lock=False, include_deleted=False) -> dict:
        query = f"SELECT {NODE_COLUMNS} FROM model_node WHERE id=%s"
        if lock:
            query += " FOR UPDATE"
        cur.execute(query, (node_id,))
        row = cur.fetchone()
        if row is None or (row["deleted_at"] is not None and not include_deleted):
            raise AppError("NOT_FOUND", "Node not found")
        if sut_id is not None and str(row["sut_id"]) != str(sut_id):
            raise AppError("VALIDATION", "The node does not belong to this SUT")
        return row

    @staticmethod
    def _check_sut(cur, sut_id):
        cur.execute("SELECT 1 FROM sut WHERE id=%s", (sut_id,))
        if cur.fetchone() is None:
            raise AppError("NOT_FOUND", "SUT not found")

    @staticmethod
    def _check_module(cur, module_id, sut_id):
        if module_id is None:
            return
        cur.execute("SELECT sut_id FROM module WHERE id=%s", (module_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Group not found")
        if str(row["sut_id"]) != str(sut_id):
            raise AppError("VALIDATION", "The group does not belong to this SUT")

    def _insert_edge(self, cur, sut_id, source_id, target_id, role) -> dict:
        if str(source_id) == str(target_id):
            raise AppError("VALIDATION", "Both ends of an edge cannot be the same node")
        source = self._node(cur, source_id, sut_id=sut_id)
        target = self._node(cur, target_id, sut_id=sut_id)
        if role in END_ROLES:
            if source["kind"] != "relation":
                raise AppError("VALIDATION", "source/target edges can only start from link nodes")
            if target["kind"] == "relation":
                raise AppError("VALIDATION", "Both ends of a link node cannot be link nodes")
            cur.execute(
                "SELECT 1 FROM model_edge WHERE source_node_id=%s AND role=%s AND invalid_at IS NULL",
                (source_id, role),
            )
            if cur.fetchone():
                raise AppError("CONFLICT", f"A link node can only have one {role} end")
        elif role in ("actor", "object") and source["kind"] != "action":
            raise AppError("VALIDATION", "actor/object edges can only start from action nodes")
        cur.execute(
            "INSERT INTO model_edge(sut_id, source_node_id, target_node_id, role) VALUES (%s,%s,%s,%s) RETURNING *",
            (sut_id, source_id, target_id, role),
        )
        return cur.fetchone()

    # ------------------------------------------------------------------ nodes
    def create_node(self, sut_id, data: dict) -> dict:
        kind = data["kind"]
        if kind not in KINDS:
            raise AppError("VALIDATION", "Unknown node type", field_errors=[{"field": "kind"}])
        if kind == "relation":
            raise AppError("VALIDATION", RELATION_GONE, field_errors=[{"field": "kind"}])
        attributes = validate_attributes(data.get("attributes"))
        source_id, target_id = data.get("source_node_id"), data.get("target_node_id")
        if kind == "relation" and (source_id is None or target_id is None):
            raise AppError(
                "VALIDATION",
                "A link node must have exactly one source and one target",
                field_errors=[
                    {"field": f, "msg": "is required"}
                    for f in ("source_node_id", "target_node_id")
                    if data.get(f) is None
                ],
            )
        if kind != "relation" and (source_id or target_id):
            raise AppError("VALIDATION", "Only link nodes can have a source and target")
        with self.db.tx() as cur:
            self._check_sut(cur, sut_id)
            self._check_module(cur, data.get("module_id"), sut_id)
            io = check_io(cur, sut_id, kind, data)
            rules = check_rules(cur, sut_id, kind, data)
            cur.execute(
                "INSERT INTO model_node(sut_id, module_id, kind, name, description, data_schema,"
                " attributes, code_ref, inputs, outputs, input_format, output_format,"
                " preconditions, effects)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    sut_id,
                    data.get("module_id"),
                    kind,
                    data["name"],
                    data.get("description"),
                    _j(data.get("data_schema")),
                    _j(attributes),
                    data.get("code_ref"),
                    _j(io.get("inputs") or []),
                    _j(io.get("outputs") or []),
                    io.get("input_format"),
                    io.get("output_format"),
                    _j(rules.get("preconditions") or []),
                    _j(rules.get("effects") or []),
                ),
            )
            node_id = cur.fetchone()["id"]
            if kind == "relation":
                self._insert_edge(cur, sut_id, node_id, source_id, "source")
                self._insert_edge(cur, sut_id, node_id, target_id, "target")
            log_change(cur, "model_node", node_id, "create", self.actor, {**data, "attributes": attributes})
            detail = self._detail(cur, node_id)
        self.bus.publish("model_node.created", {"id": str(node_id), "sut_id": str(sut_id)})
        return detail

    def _detail(self, cur, node_id) -> dict:
        node = self._node(cur, node_id, include_deleted=True)
        cur.execute(
            "SELECT e.*, s.name AS source_name, t.name AS target_name FROM model_edge e"
            " JOIN model_node s ON s.id=e.source_node_id JOIN model_node t ON t.id=e.target_node_id"
            " WHERE (e.source_node_id=%s OR e.target_node_id=%s) AND e.invalid_at IS NULL"
            " ORDER BY e.created_at",
            (node_id, node_id),
        )
        edges = cur.fetchall()
        cur.execute(
            "SELECT a.* FROM node_api_link l JOIN api_endpoint a ON a.id=l.api_id"
            " WHERE l.node_id=%s AND l.invalid_at IS NULL ORDER BY a.path, a.method",
            (node_id,),
        )
        node["apis"] = cur.fetchall()
        node["edges"] = edges
        node["fields"] = AttributeService(self.db, self.bus).list_for_node(node_id, cur=cur)
        node["links"] = LinkService.list_rows(cur, node["sut_id"], node_id) if node["kind"] == "entity" else []
        if node["kind"] == "relation":
            ends = {e["role"]: e["target_node_id"] for e in edges if str(e["source_node_id"]) == str(node_id)}
            node["source_node_id"] = ends.get("source")
            node["target_node_id"] = ends.get("target")
        return node

    def get_node(self, node_id) -> dict:
        with self.db.tx() as cur:
            self._node(cur, node_id)
            return self._detail(cur, node_id)

    def update_node(self, node_id, data: dict) -> dict:
        if "kind" in data:
            raise AppError("VALIDATION", "The node type cannot be changed after creation")
        with self.db.tx() as cur:
            node = self._node(cur, node_id, lock=True)
            if "attributes" in data:
                data["attributes"] = validate_attributes(data["attributes"])
            if "module_id" in data:
                self._check_module(cur, data["module_id"], node["sut_id"])
            ends = {r: data.pop(f"{r}_node_id") for r in END_ROLES if f"{r}_node_id" in data}
            if ends and node["kind"] != "relation":
                raise AppError("VALIDATION", "Only link nodes can have a source and target")
            for role, other in ends.items():
                if other is None:
                    raise AppError("VALIDATION", "A link node must have exactly one source and one target")
                cur.execute(
                    "UPDATE model_edge SET invalid_at=now() WHERE source_node_id=%s AND role=%s AND invalid_at IS NULL",
                    (node_id, role),
                )
                self._insert_edge(cur, node["sut_id"], node_id, other, role)
            allowed = ("name", "description", "data_schema", "attributes", "code_ref", "module_id")
            values = {k: v for k, v in data.items() if k in allowed}
            values.update(check_io(cur, node["sut_id"], node["kind"], data))
            values.update(check_rules(cur, node["sut_id"], node["kind"], data))
            if values:
                sets = ", ".join(f"{k}=%s" for k in values)
                params = [
                    _j(v) if k in ("attributes", "data_schema", "inputs", "outputs", *RULE_KEYS) else v
                    for k, v in values.items()
                ]
                cur.execute(f"UPDATE model_node SET {sets} WHERE id=%s", (*params, node_id))
            log_change(cur, "model_node", node_id, "update", self.actor, {**values, **ends})
            detail = self._detail(cur, node_id)
        self.bus.publish("model_node.updated", {"id": str(node_id)})
        return detail

    def references(self, node_id) -> list[dict]:
        """Everything pointing at this node: edges, relation ends, APIs, requirements, cases."""
        with self.db.tx() as cur:
            self._node(cur, node_id)
            return self._references(cur, node_id)

    @staticmethod
    def _references(cur, node_id) -> list[dict]:
        refs: list[dict] = []
        cur.execute(
            "SELECT e.id, e.role, e.source_node_id, e.target_node_id,"
            " CASE WHEN e.source_node_id=%(n)s THEN t.name ELSE s.name END AS other_name"
            " FROM model_edge e JOIN model_node s ON s.id=e.source_node_id"
            " JOIN model_node t ON t.id=e.target_node_id"
            " WHERE (e.source_node_id=%(n)s OR e.target_node_id=%(n)s) AND e.invalid_at IS NULL",
            {"n": node_id},
        )
        for e in cur.fetchall():
            refs.append({"type": "edge", "id": str(e["id"]), "role": e["role"], "label": e["other_name"]})
        for lk in LinkService.list_rows_for_node(cur, node_id):
            refs.append(
                {
                    "type": "link",
                    "id": str(lk["id"]),
                    "role": "link",
                    "label": f"{lk['from_name']} {lk['forward_name']} {lk['to_name']}",
                }
            )
        cur.execute(
            "SELECT a.id, a.method, a.path FROM node_api_link l"
            " JOIN api_endpoint a ON a.id=l.api_id"
            " WHERE l.node_id=%s AND l.invalid_at IS NULL",
            (node_id,),
        )
        for a in cur.fetchall():
            refs.append({"type": "api", "id": str(a["id"]), "label": f"{a['method']} {a['path']}"})
        cur.execute(
            "SELECT r.id, r.code, r.title FROM requirement_node_link l"
            " JOIN requirement r ON r.id=l.requirement_id WHERE l.node_id=%s",
            (node_id,),
        )
        for r in cur.fetchall():
            refs.append({"type": "requirement", "id": str(r["id"]), "label": f"{r['code']} {r['title']}"})
        cur.execute(
            "SELECT c.id, c.code, c.title FROM case_node_link l JOIN test_case c ON c.id=l.case_id WHERE l.node_id=%s",
            (node_id,),
        )
        for c in cur.fetchall():
            refs.append({"type": "case", "id": str(c["id"]), "label": f"{c['code']} {c['title']}"})
        return refs

    def delete_node(self, node_id, *, confirm: bool = False) -> dict:
        """Without confirm, a referenced node is not deleted and the references are returned."""
        with self.db.tx() as cur:
            self._node(cur, node_id, lock=True)
            refs = self._references(cur, node_id)
            if refs and not confirm:
                raise AppError(
                    "CONFLICT",
                    f"This node is still referenced by {len(refs)} item(s); confirm to delete",
                    related=[f"{r['type']}:{r['id']}:{r['label']}" for r in refs],
                )
            cur.execute("UPDATE model_node SET deleted_at=now() WHERE id=%s", (node_id,))
            cur.execute(
                "UPDATE model_edge SET invalid_at=now() WHERE (source_node_id=%(n)s"
                " OR target_node_id=%(n)s) AND invalid_at IS NULL",
                {"n": node_id},
            )
            invalidated = cur.rowcount
            cur.execute(
                "UPDATE model_link SET deleted_at=now() WHERE deleted_at IS NULL"
                " AND %s IN (from_node_id, to_node_id, via_node_id)",
                (node_id,),
            )
            cur.execute(
                "UPDATE node_api_link SET invalid_at=now() WHERE node_id=%s AND invalid_at IS NULL",
                (node_id,),
            )
            log_change(cur, "model_node", node_id, "soft_delete", self.actor, {"references": len(refs)})
        self.bus.publish("model_node.deleted", {"id": str(node_id)})
        return {"deleted": True, "invalidated_edges": invalidated, "references": refs}

    def list_nodes(
        self,
        sut_id,
        *,
        kind: str | None = None,
        module_id=None,
        q: str | None = None,
        attr: str | None = None,
        attr_text: str | None = None,
    ) -> list[dict]:
        where, params = ["sut_id=%s", "deleted_at IS NULL"], [sut_id]
        if kind:
            where.append("kind=%s")
            params.append(kind)
        if module_id:
            where.append("module_id=%s")
            params.append(module_id)
        if q:
            where.append("(name ILIKE %s OR description ILIKE %s)")
            params += [f"%{q}%", f"%{q}%"]
        if attr_text:
            fields = [attr] if attr else ["conditions", "states", "constraints"]
            if any(f not in ("conditions", "states", "constraints") for f in fields):
                raise AppError("VALIDATION", "attr can only be conditions/states/constraints")
            where.append(
                "EXISTS (SELECT 1 FROM unnest(%s::text[]) f,"
                " jsonb_array_elements(attributes->f) item WHERE item->>'text' ILIKE %s)"
            )
            params += [fields, f"%{attr_text}%"]
        with self.db.tx() as cur:
            self._check_sut(cur, sut_id)
            cur.execute(
                f"SELECT {NODE_COLUMNS} FROM model_node WHERE {' AND '.join(where)} ORDER BY kind, name",
                params,
            )
            return cur.fetchall()

    def find_by_attribute(self, sut_id, attr: str, item: dict) -> list[dict]:
        """Exact attribute-item match; served by the GIN jsonb_path_ops index."""
        with self.db.tx() as cur:
            cur.execute(
                f"SELECT {NODE_COLUMNS} FROM model_node WHERE sut_id=%s AND deleted_at IS NULL"
                " AND attributes @> %s ORDER BY name",
                (sut_id, _j({attr: [item]})),
            )
            return cur.fetchall()

    # ------------------------------------------------------------------ edges
    def create_edge(self, sut_id, source_id, target_id, role) -> dict:
        if role not in ("source", "target", "actor", "object", "ref"):
            raise AppError("VALIDATION", "Unknown edge role")
        if role in END_ROLES:
            raise AppError("VALIDATION", RELATION_GONE, field_errors=[{"field": "role"}])
        with self.db.tx() as cur:
            self._check_sut(cur, sut_id)
            edge = self._insert_edge(cur, sut_id, source_id, target_id, role)
            log_change(cur, "model_edge", edge["id"], "create", self.actor, dict(edge))
        self.bus.publish("model_edge.created", {"id": str(edge["id"])})
        return edge

    def delete_edge(self, edge_id) -> None:
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM model_edge WHERE id=%s AND invalid_at IS NULL FOR UPDATE", (edge_id,))
            edge = cur.fetchone()
            if edge is None:
                raise AppError("NOT_FOUND", "Edge not found")
            if edge["role"] in END_ROLES:
                raise AppError(
                    "CONFLICT",
                    "A link node must keep its source and target; change them or delete the link node",
                )
            cur.execute("UPDATE model_edge SET invalid_at=now() WHERE id=%s", (edge_id,))
            log_change(cur, "model_edge", edge_id, "delete", self.actor)
        self.bus.publish("model_edge.deleted", {"id": str(edge_id)})

    # ------------------------------------------------------------------ graph
    def graph(self, sut_id, module_id=None) -> dict:
        with self.db.tx() as cur:
            self._check_sut(cur, sut_id)
            if module_id:
                self._check_module(cur, module_id, sut_id)
            cur.execute(
                f"SELECT {NODE_COLUMNS} FROM model_node WHERE sut_id=%s AND deleted_at IS NULL"
                " AND (%s::uuid IS NULL OR module_id=%s::uuid) ORDER BY kind, name",
                (sut_id, module_id, module_id),
            )
            nodes = cur.fetchall()
            ids = [n["id"] for n in nodes]
            cur.execute(
                "SELECT id, source_node_id, target_node_id, role FROM model_edge"
                " WHERE sut_id=%s AND invalid_at IS NULL"
                " AND source_node_id = ANY(%s::uuid[]) AND target_node_id = ANY(%s::uuid[])"
                " ORDER BY created_at",
                (sut_id, ids, ids),
            )
            edges = cur.fetchall()
            keep = {str(i) for i in ids}
            links = [
                lk
                for lk in LinkService.list_rows(cur, sut_id)
                if str(lk["from_node_id"]) in keep and str(lk["to_node_id"]) in keep
            ]
        return {"nodes": nodes, "edges": edges, "links": links}

    def neighbors(self, node_id, depth: int = 1) -> list[dict]:
        """Undirected breadth-first walk over active edges; depth capped at 5; cycle-safe."""
        if depth < 1 or depth > MAX_DEPTH:
            raise AppError("VALIDATION", f"depth must be between 1..{MAX_DEPTH}")
        with self.db.tx() as cur:
            self._node(cur, node_id)
            cur.execute(
                """
                WITH RECURSIVE adj AS (
                  SELECT e.source_node_id AS a, e.target_node_id AS b FROM model_edge e
                  JOIN model_node s ON s.id=e.source_node_id AND s.deleted_at IS NULL
                  JOIN model_node t ON t.id=e.target_node_id AND t.deleted_at IS NULL
                  WHERE e.invalid_at IS NULL
                  UNION ALL
                  SELECT e.target_node_id, e.source_node_id FROM model_edge e
                  JOIN model_node s ON s.id=e.source_node_id AND s.deleted_at IS NULL
                  JOIN model_node t ON t.id=e.target_node_id AND t.deleted_at IS NULL
                  WHERE e.invalid_at IS NULL
                  UNION ALL
                  SELECT l.from_node_id, l.to_node_id FROM model_link l WHERE l.deleted_at IS NULL
                  UNION ALL
                  SELECT l.to_node_id, l.from_node_id FROM model_link l WHERE l.deleted_at IS NULL
                ), walk(node_id, depth, path) AS (
                  SELECT %(start)s::uuid, 0, ARRAY[%(start)s::uuid]
                  UNION ALL
                  SELECT adj.b, w.depth + 1, w.path || adj.b FROM walk w
                  JOIN adj ON adj.a = w.node_id
                  WHERE w.depth < %(depth)s AND NOT adj.b = ANY(w.path)
                )
                SELECT n.id, n.kind, n.name, n.module_id, min(w.depth) AS depth
                FROM walk w JOIN model_node n ON n.id = w.node_id
                WHERE w.depth > 0
                GROUP BY n.id, n.kind, n.name, n.module_id
                ORDER BY depth, n.name
                """,
                {"start": node_id, "depth": depth},
            )
            return cur.fetchall()

    # ------------------------------------------------------------------ snapshot
    def snapshot_content(self, sut_id) -> dict:
        graph = self.graph(sut_id)
        with self.db.tx() as cur:
            cur.execute(
                "SELECT a.id, a.method, a.path, a.name, a.description, a.code_ref,"
                " a.request_schema, a.response_schema, a.request_content_type,"
                " a.response_content_type,"
                " coalesce(array_agg(l.node_id ORDER BY l.node_id)"
                "   FILTER (WHERE l.node_id IS NOT NULL AND l.invalid_at IS NULL), '{}')"
                " AS node_ids"
                " FROM api_endpoint a LEFT JOIN node_api_link l ON l.api_id=a.id"
                " WHERE a.sut_id=%s GROUP BY a.id ORDER BY a.method, a.path",
                (sut_id,),
            )
            apis = cur.fetchall()
            fields = [
                {
                    k: f[k]
                    for k in (
                        "id",
                        "node_id",
                        "name",
                        "display_name",
                        "data_type",
                        "unit",
                        "constraints",
                        "description",
                        "required",
                        "format",
                        "example",
                        "enum_values",
                        "ref_node_id",
                        "storage_name",
                    )
                }
                for f in AttributeService(self.db, self.bus).list_for_sut(sut_id, cur=cur)
            ]
        keep = (
            "id",
            "module_id",
            "kind",
            "name",
            "description",
            "data_schema",
            "attributes",
            "code_ref",
            *IO_KEYS,
            *RULE_KEYS,
        )
        link_keys = (
            "id",
            "from_node_id",
            "to_node_id",
            "forward_name",
            "reverse_name",
            "forward_api_name",
            "reverse_api_name",
            "cardinality",
            "fk_attribute_id",
            "via_node_id",
            "via_from_attribute_id",
            "via_to_attribute_id",
            "required",
            "description",
        )
        return json.loads(
            _dumps(
                {
                    "nodes": [{k: n[k] for k in keep} for n in graph["nodes"]],
                    "edges": graph["edges"],
                    "links": [{k: lk[k] for k in link_keys} for lk in graph["links"]],
                    "apis": apis,
                    "fields": fields,
                }
            )
        )

    def create_snapshot(self, sut_id, version_id=None, cur=None) -> dict:
        """Immutable model snapshot (used by version freeze in M1-05)."""
        content = self.snapshot_content(sut_id)
        digest = hashlib.sha256(_dumps(content).encode()).hexdigest()
        query = (
            "INSERT INTO model_snapshot(sut_id, version_id, content, digest)"
            " VALUES (%s,%s,%s,%s) RETURNING id, sut_id, version_id, digest, created_at"
        )
        params = (sut_id, version_id, _j(content), digest)
        if cur is not None:
            cur.execute(query, params)
            return cur.fetchone()
        with self.db.tx() as c:
            c.execute(query, params)
            return c.fetchone()
