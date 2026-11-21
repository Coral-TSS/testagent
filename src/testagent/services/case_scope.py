"""Load the ontology, compute a per-requirement scope, and store the snapshot.

Generation reads the stored snapshot. A fresh POST replaces it. A PUT applies the
tester's adds, removes and depth without silently recomputing over those edits.
"""

from __future__ import annotations

import json

from psycopg.types.json import Jsonb

from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.services.links import LinkService
from testagent.services.scope_manifest import (
    MISSING_REFS,
    ActionRec,
    ApiRec,
    EntityRec,
    FieldRec,
    Graph,
    Item,
    LinkRec,
    RequirementRefs,
    add_manual,
    compute_manifest,
    drop_item,
    manifest_from,
    prepare,
    prompt_scope,
    refresh_states,
)
from testagent.services.scope_manifest import items_from_manifest as items_of

DEPTHS = (0, 1, 2)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        return json.loads(value)
    return list(value)


class CaseScopeService:
    def __init__(self, db, actor: str | None = None):
        self.db = db
        self.actor = actor or current_actor()

    # ---------------------------------------------------------------- graph
    def load_graph(self, cur, sut_id) -> Graph:
        graph = Graph()
        cur.execute(
            "SELECT id::text AS id, name, attributes FROM model_node"
            " WHERE sut_id=%s AND kind='entity' AND deleted_at IS NULL",
            (sut_id,),
        )
        for row in cur.fetchall():
            attrs = row["attributes"] or {}
            from testagent.services.scope_manifest import entity_constraints, entity_states

            graph.entities[row["id"]] = EntityRec(
                row["id"], row["name"], entity_states(attrs), entity_constraints(attrs)
            )
        cur.execute(
            "SELECT a.id::text AS id, a.node_id::text AS entity_id, a.name, a.required, n.name AS entity"
            " FROM entity_attribute a JOIN model_node n ON n.id=a.node_id"
            " WHERE a.sut_id=%s AND a.deleted_at IS NULL AND n.deleted_at IS NULL",
            (sut_id,),
        )
        for row in cur.fetchall():
            graph.fields[row["id"]] = FieldRec(
                row["id"], row["entity_id"], row["entity"], row["name"], bool(row["required"])
            )
        cur.execute(
            "SELECT id::text AS id, name, preconditions, effects, inputs, outputs FROM model_node"
            " WHERE sut_id=%s AND kind='action' AND deleted_at IS NULL",
            (sut_id,),
        )
        for row in cur.fetchall():
            graph.actions[row["id"]] = ActionRec(
                row["id"],
                row["name"],
                _as_list(row["preconditions"]),
                _as_list(row["effects"]),
                _as_list(row["inputs"]),
                _as_list(row["outputs"]),
            )
        cur.execute(
            "SELECT source_node_id::text AS source, target_node_id::text AS target, role FROM model_edge"
            " WHERE sut_id=%s AND invalid_at IS NULL",
            (sut_id,),
        )
        for row in cur.fetchall():
            action = graph.actions.get(row["source"])
            if action is None:
                continue
            if row["role"] == "actor":
                action.actor_ids.append(row["target"])
            elif row["role"] == "object":
                action.object_ids.append(row["target"])
            elif row["role"] == "ref":
                action.ref_ids.append(row["target"])
        cur.execute(
            "SELECT a.id::text AS id, a.method, a.path, l.node_id::text AS action_id FROM node_api_link l"
            " JOIN api_endpoint a ON a.id=l.api_id WHERE a.sut_id=%s AND l.invalid_at IS NULL",
            (sut_id,),
        )
        for row in cur.fetchall():
            graph.apis[row["id"]] = ApiRec(row["id"], row["method"], row["path"], row["action_id"])
            action = graph.actions.get(row["action_id"])
            if action is not None:
                action.api_ids.append(row["id"])
        for link in LinkService.list_rows(cur, sut_id):
            graph.links[str(link["id"])] = LinkRec(
                str(link["id"]),
                str(link["from_node_id"]),
                str(link["to_node_id"]),
                link["from_name"],
                link["to_name"],
                link["forward_name"],
                link["cardinality"],
                bool(link["required"]),
                str(link["fk_attribute_id"]) if link.get("fk_attribute_id") else None,
            )
        return prepare(graph)

    def load_refs(self, cur, req: dict) -> RequirementRefs:
        cur.execute(
            "SELECT l.node_id::text AS id, l.role FROM requirement_node_link l"
            " JOIN model_node n ON n.id=l.node_id AND n.deleted_at IS NULL"
            " WHERE l.requirement_id=%s AND n.kind IN ('entity','action')",
            (req["id"],),
        )
        nodes = [(r["id"], r["role"]) for r in cur.fetchall()]
        cur.execute(
            "SELECT l.attribute_id::text AS id, l.role FROM requirement_attribute_link l"
            " JOIN entity_attribute a ON a.id=l.attribute_id AND a.deleted_at IS NULL"
            " WHERE l.requirement_id=%s",
            (req["id"],),
        )
        fields = [(r["id"], r["role"]) for r in cur.fetchall()]
        cur.execute(
            "SELECT l.link_id::text AS id, l.role FROM requirement_link_ref l"
            " JOIN model_link k ON k.id=l.link_id AND k.deleted_at IS NULL"
            " WHERE l.requirement_id=%s",
            (req["id"],),
        )
        links = [(r["id"], r["role"]) for r in cur.fetchall()]
        return RequirementRefs(str(req["id"]), req["code"], req["title"], nodes, fields, links)

    def default_depth(self, cur) -> int:
        cur.execute("SELECT default_scope_depth FROM agent_config WHERE id='default'")
        row = cur.fetchone()
        if row is None or row["default_scope_depth"] is None:
            return 1
        return int(row["default_scope_depth"])

    def _depth(self, cur, req: dict, override) -> int:
        if override is not None:
            if int(override) not in DEPTHS:
                raise AppError("VALIDATION", "范围深度只能是 0、1 或 2")
            return int(override)
        if req.get("scope_depth") is not None:
            return int(req["scope_depth"])
        return self.default_depth(cur)

    def _version(self, cur, version_id) -> dict:
        cur.execute("SELECT * FROM version WHERE id=%s", (version_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Version not found")
        return row

    def _requirements(self, cur, version_id, requirement_ids) -> list[dict]:
        cur.execute(
            "SELECT * FROM requirement WHERE version_id=%s"
            " AND (%s::uuid[] IS NULL OR id = ANY(%s::uuid[])) ORDER BY code",
            (
                version_id,
                [str(r) for r in requirement_ids] if requirement_ids else None,
                [str(r) for r in requirement_ids] if requirement_ids else None,
            ),
        )
        rows = cur.fetchall()
        if requirement_ids and len(rows) != len(set(map(str, requirement_ids))):
            raise AppError("NOT_FOUND", "Some requirements do not exist or do not belong to this version")
        return rows

    def _save_depth(self, cur, version: dict, req_id, depth: int | None) -> None:
        if depth is None or version["status"] != "planning":
            return
        cur.execute("UPDATE requirement SET scope_depth=%s WHERE id=%s", (depth, req_id))

    def _upsert(self, cur, version_id, req_id, depth: int, manifest: dict, *, edited: bool) -> dict:
        cur.execute(
            "INSERT INTO case_gen_scope(version_id, requirement_id, depth, manifest, edited)"
            " VALUES (%s,%s,%s,%s,%s)"
            " ON CONFLICT (requirement_id) DO UPDATE SET version_id=EXCLUDED.version_id,"
            " depth=EXCLUDED.depth, manifest=EXCLUDED.manifest, edited=EXCLUDED.edited,"
            " confirmed_at=NULL, confirmed_by=NULL, updated_at=now() RETURNING *",
            (version_id, req_id, depth, Jsonb(manifest, dumps=_dumps), edited),
        )
        return cur.fetchone()

    @staticmethod
    def _view(row: dict | None, manifest: dict) -> dict:
        if row is None:
            return {
                "id": None,
                "requirement_id": manifest["requirement"]["id"],
                "depth": manifest["depth"],
                "edited": False,
                "confirmed": False,
                "manifest": prompt_scope(manifest),
                "remove": manifest.get("suppress") or [],
                "add": manifest.get("manual") or [],
                "message": manifest.get("message"),
            }
        return {
            "id": str(row["id"]),
            "requirement_id": str(row["requirement_id"]),
            "depth": row["depth"],
            "edited": row["edited"],
            "confirmed": row["confirmed_at"] is not None,
            "confirmed_at": row["confirmed_at"],
            "confirmed_by": row["confirmed_by"],
            "manifest": prompt_scope(row["manifest"]),
            "remove": (row["manifest"] or {}).get("suppress") or [],
            "add": (row["manifest"] or {}).get("manual") or [],
            "message": (row["manifest"] or {}).get("message"),
        }

    def _build(self, graph: Graph, refs: RequirementRefs, depth: int) -> dict:
        manifest = compute_manifest(graph, refs, depth)
        if not manifest.get("blocked"):
            manifest["suppress"] = []
            manifest["manual"] = []
        return manifest

    def _apply(self, graph: Graph, refs: RequirementRefs, depth: int, manifest: dict, remove, add) -> dict:
        if manifest.get("blocked"):
            raise AppError("VALIDATION", manifest.get("message") or f"需求 {refs.code} {MISSING_REFS}")
        included: dict[tuple[str, str], Item] = items_of(manifest)
        for item in remove or []:
            drop_item(graph, included, item["kind"], str(item["id"]))
        manual = list(manifest.get("manual") or [])
        for item in add or []:
            try:
                add_manual(graph, included, item["kind"], str(item["id"]), cover=not item.get("reference_only", False))
            except KeyError:
                raise AppError("VALIDATION", "要加入范围的对象不存在或不属于本系统") from None
            manual.append(
                {"kind": item["kind"], "id": str(item["id"]), "reference_only": bool(item.get("reference_only"))}
            )
        refresh_states(graph, included)
        suppress = list(manifest.get("suppress") or [])
        suppress += [{"kind": i["kind"], "id": str(i["id"])} for i in remove or []]
        # de-duplicate while keeping order
        seen = set()
        unique = []
        for row in suppress:
            key = (row["kind"], row["id"])
            if key in seen:
                continue
            seen.add(key)
            unique.append({"kind": row["kind"], "id": row["id"]})
        seen_add = set()
        unique_add = []
        for row in manual:
            key = (row["kind"], row["id"])
            if key in seen_add:
                continue
            seen_add.add(key)
            unique_add.append(row)
        return manifest_from(graph, refs, depth, included, suppress=unique, manual=unique_add)

    # ---------------------------------------------------------------- API
    def compute(self, version_id, requirement_ids=None, depths: dict | None = None) -> dict:
        """Fresh manifests from the current refs and depth. Replaces any previous edits."""
        depths = {str(k): v for k, v in (depths or {}).items()}
        with self.db.tx() as cur:
            version = self._version(cur, version_id)
            reqs = self._requirements(cur, version_id, requirement_ids)
            if not reqs:
                raise AppError("VALIDATION", "This version has no requirements yet")
            graph = self.load_graph(cur, version["sut_id"])
            views = []
            for req in reqs:
                depth = self._depth(cur, req, depths.get(str(req["id"])))
                refs = self.load_refs(cur, req)
                manifest = self._build(graph, refs, depth)
                if depths.get(str(req["id"])) is not None:
                    self._save_depth(cur, version, req["id"], depth)
                if manifest.get("blocked"):
                    views.append(self._view(None, manifest))
                    continue
                row = self._upsert(cur, version_id, req["id"], depth, manifest, edited=False)
                views.append(self._view(row, manifest))
        return {"version_id": str(version_id), "default_depth": self._default_outside(), "scopes": views}

    def _default_outside(self) -> int:
        with self.db.tx() as cur:
            return self.default_depth(cur)

    def update(self, version_id, requirement_id, *, depth=None, recompute=False, remove=None, add=None) -> dict:
        with self.db.tx() as cur:
            version = self._version(cur, version_id)
            reqs = self._requirements(cur, version_id, [requirement_id])
            req = reqs[0]
            graph = self.load_graph(cur, version["sut_id"])
            refs = self.load_refs(cur, req)
            chosen = self._depth(cur, req, depth)
            if depth is not None:
                self._save_depth(cur, version, req["id"], chosen)
            cur.execute("SELECT * FROM case_gen_scope WHERE requirement_id=%s", (req["id"],))
            current = cur.fetchone()
            stored = (current["manifest"] if current else None) or {}
            if recompute or current is None or stored.get("blocked"):
                base = self._build(graph, refs, chosen)
                remove = [*(stored.get("suppress") or []), *(remove or [])]
                add = [*(stored.get("manual") or []), *(add or [])]
            else:
                base = stored
                base["depth"] = chosen
            if base.get("blocked"):
                return {"version_id": str(version_id), "scopes": [self._view(None, base)]}
            manifest = self._apply(graph, refs, chosen, base, remove, add)
            edited = bool(manifest.get("suppress") or manifest.get("manual"))
            row = self._upsert(cur, version_id, req["id"], chosen, manifest, edited=edited)
        return {"version_id": str(version_id), "scopes": [self._view(row, manifest)]}

    def confirm(self, version_id, requirement_ids) -> dict:
        with self.db.tx() as cur:
            self._version(cur, version_id)
            reqs = self._requirements(cur, version_id, requirement_ids)
            views = []
            for req in reqs:
                cur.execute("SELECT * FROM case_gen_scope WHERE requirement_id=%s", (req["id"],))
                row = cur.fetchone()
                if row is None:
                    raise AppError("VALIDATION", f"需求 {req['code']} 还没有范围清单，请先计算范围。")
                if (row["manifest"] or {}).get("blocked"):
                    raise AppError(
                        "VALIDATION", (row["manifest"] or {}).get("message") or f"需求 {req['code']} {MISSING_REFS}"
                    )
                cur.execute(
                    "UPDATE case_gen_scope SET confirmed_at=now(), confirmed_by=%s WHERE id=%s RETURNING *",
                    (self.actor, row["id"]),
                )
                saved = cur.fetchone()
                views.append(self._view(saved, saved["manifest"]))
        return {"version_id": str(version_id), "scopes": views}

    def for_generate(self, version_id, reqs: list[dict], *, require_confirmed: bool) -> list[dict]:
        """Manifests the generator must use. Computes a default snapshot when none is stored."""
        with self.db.tx() as cur:
            version = self._version(cur, version_id)
            graph = self.load_graph(cur, version["sut_id"])
            out = []
            blocked = []
            for req in reqs:
                cur.execute("SELECT * FROM requirement WHERE id=%s", (req["id"],))
                full = cur.fetchone() or req
                cur.execute("SELECT * FROM case_gen_scope WHERE requirement_id=%s", (full["id"],))
                row = cur.fetchone()
                refs = self.load_refs(cur, full)
                if row is None:
                    depth = self._depth(cur, full, None)
                    manifest = self._build(graph, refs, depth)
                    if not manifest.get("blocked"):
                        row = self._upsert(cur, version_id, full["id"], depth, manifest, edited=False)
                else:
                    manifest = row["manifest"]
                if manifest.get("blocked") or not refs.has_refs():
                    blocked.append(manifest.get("message") or f"需求 {full['code']} {MISSING_REFS}")
                    continue
                if require_confirmed and (row is None or row["confirmed_at"] is None):
                    raise AppError("CONFLICT", "请先预览并确认用例范围后再生成。")
                view = self._view(row, manifest)
                view["fingerprint"] = manifest.get("fingerprint")
                view["full"] = manifest
                out.append(view)
        if blocked:
            raise AppError("VALIDATION", "；".join(blocked))
        return out


def scope_allowed(scopes: list[dict] | None) -> dict[str, set[str]] | None:
    """Id sets a case-generation run may read. None means the run is not scope-bound."""
    if not scopes:
        return None
    allowed = {"node": set(), "field": set(), "link": set(), "api": set(), "requirement": set()}
    for scope in scopes:
        if scope.get("blocked"):
            continue
        req = scope.get("requirement") or {}
        if req.get("id"):
            allowed["requirement"].add(str(req["id"]))
        for node in scope.get("nodes") or []:
            allowed["node"].add(str(node["id"]))
        for row in scope.get("fields") or []:
            allowed["field"].add(str(row["id"]))
        for row in scope.get("links") or []:
            allowed["link"].add(str(row["id"]))
        for row in scope.get("apis") or []:
            allowed["api"].add(str(row["id"]))
    return allowed
