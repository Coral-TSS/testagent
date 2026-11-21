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
    case_covers_target,
    compute_manifest,
    drop_item,
    manifest_from,
    prepare,
    prompt_scope,
    refresh_states,
    target_label,
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
    def load_graph(self, cur, sut_id, version_id=None) -> Graph:
        from testagent.services.model_scope import AUTO, resolve_version

        version_id = resolve_version(cur, sut_id, AUTO if version_id is None else version_id)
        graph = Graph()
        cur.execute(
            "SELECT id::text AS id, name, attributes FROM model_node"
            " WHERE sut_id=%s AND kind='entity' AND deleted_at IS NULL"
            " AND version_id IS NOT DISTINCT FROM %s",
            (sut_id, version_id),
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
            " WHERE a.sut_id=%s AND a.deleted_at IS NULL AND n.deleted_at IS NULL"
            " AND n.version_id IS NOT DISTINCT FROM %s",
            (sut_id, version_id),
        )
        for row in cur.fetchall():
            graph.fields[row["id"]] = FieldRec(
                row["id"], row["entity_id"], row["entity"], row["name"], bool(row["required"])
            )
        cur.execute(
            "SELECT id::text AS id, name, preconditions, effects, inputs, outputs FROM model_node"
            " WHERE sut_id=%s AND kind='action' AND deleted_at IS NULL"
            " AND version_id IS NOT DISTINCT FROM %s",
            (sut_id, version_id),
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
            " WHERE sut_id=%s AND invalid_at IS NULL AND version_id IS NOT DISTINCT FROM %s",
            (sut_id, version_id),
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
            " JOIN api_endpoint a ON a.id=l.api_id"
            " JOIN model_node n ON n.id=l.node_id AND n.version_id IS NOT DISTINCT FROM %s"
            " WHERE a.sut_id=%s AND l.invalid_at IS NULL",
            (version_id, sut_id),
        )
        for row in cur.fetchall():
            graph.apis[row["id"]] = ApiRec(row["id"], row["method"], row["path"], row["action_id"])
            action = graph.actions.get(row["action_id"])
            if action is not None:
                action.api_ids.append(row["id"])
        for link in LinkService.list_rows(cur, sut_id, version_id=version_id):
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
            graph = self.load_graph(cur, version["sut_id"], version["id"])
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

    def update(
        self, version_id, requirement_id, *, depth=None, recompute=False, remove=None, add=None, waivers=None
    ) -> dict:
        with self.db.tx() as cur:
            version = self._version(cur, version_id)
            reqs = self._requirements(cur, version_id, [requirement_id])
            req = reqs[0]
            graph = self.load_graph(cur, version["sut_id"], version["id"])
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
            edited = bool(manifest.get("suppress") or manifest.get("manual") or waivers)
            row = self._upsert(cur, version_id, req["id"], chosen, manifest, edited=edited)
            if waivers is not None:
                save_human_waivers(cur, version_id, req["id"], manifest["fingerprint"], waivers, self.actor)
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
            graph = self.load_graph(cur, version["sut_id"], version["id"])
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


def confirmed_waivers(cur, scopes: list[dict]) -> dict[tuple[str, str], set[str]]:
    """(requirement id, fingerprint) -> target ids a person has confirmed."""
    out: dict[tuple[str, str], set[str]] = {}
    for scope in scopes:
        req = (scope.get("requirement") or {}).get("id")
        fp = scope.get("fingerprint")
        if not req or not fp:
            continue
        cur.execute(
            "SELECT target_id FROM coverage_waiver WHERE requirement_id=%s AND fingerprint=%s"
            " AND confirmed_at IS NOT NULL",
            (req, fp),
        )
        out[(str(req), fp)] = {r["target_id"] for r in cur.fetchall()}
    return out


def record_agent_waivers(cur, version_id, scopes: list[dict], waivers: list) -> None:
    """Remember a model's waiver. It does not satisfy the gate until a person confirms it."""
    by_req = {str((s.get("requirement") or {}).get("id")): s for s in scopes}
    for waiver in waivers:
        target = waiver.target_id if hasattr(waiver, "target_id") else waiver["target_id"]
        reason = (waiver.reason if hasattr(waiver, "reason") else waiver["reason"]).strip()
        code = getattr(waiver, "requirement_code", None) or (
            waiver.get("requirement_code") if isinstance(waiver, dict) else None
        )
        scope = None
        if code:
            scope = next((s for s in scopes if (s.get("requirement") or {}).get("code") == code), None)
        if scope is None and len(scopes) == 1:
            scope = scopes[0]
        if scope is None:
            scope = next(
                (s for s in scopes if any(t["id"] == target for t in s.get("targets") or [])),
                None,
            )
        if scope is None or not reason:
            continue
        req_id = (scope.get("requirement") or {}).get("id")
        fp = scope.get("fingerprint")
        if not req_id or not fp or req_id not in by_req and str(req_id) not in by_req:
            continue
        cur.execute(
            "INSERT INTO coverage_waiver(version_id, requirement_id, target_id, reason, proposed_by, fingerprint)"
            " VALUES (%s,%s,%s,%s,'agent',%s)"
            " ON CONFLICT (requirement_id, target_id, fingerprint) DO UPDATE SET reason=EXCLUDED.reason"
            " WHERE coverage_waiver.confirmed_at IS NULL",
            (version_id, req_id, target, reason, fp),
        )


def save_human_waivers(cur, version_id, requirement_id, fingerprint: str, waivers: list[dict], actor: str) -> None:
    """A person confirming a waiver in the preview. Each entry is confirmed immediately."""
    for waiver in waivers:
        reason = str(waiver.get("reason") or "").strip()
        target = str(waiver.get("target_id") or "")
        if not reason or not target:
            continue
        cur.execute(
            "INSERT INTO coverage_waiver(version_id, requirement_id, target_id, reason, proposed_by,"
            " confirmed_by, confirmed_at, fingerprint) VALUES (%s,%s,%s,%s,'human',%s,now(),%s)"
            " ON CONFLICT (requirement_id, target_id, fingerprint) DO UPDATE SET reason=EXCLUDED.reason,"
            " proposed_by='human', confirmed_by=EXCLUDED.confirmed_by, confirmed_at=now()",
            (version_id, requirement_id, target, reason, actor, fingerprint),
        )


def confirm_waiver_rows(cur, requirement_id, target_ids: list[str], actor: str) -> int:
    cur.execute(
        "UPDATE coverage_waiver SET confirmed_at=now(), confirmed_by=%s"
        " WHERE requirement_id=%s AND target_id = ANY(%s) AND confirmed_at IS NULL RETURNING id",
        (actor, requirement_id, target_ids),
    )
    return len(cur.fetchall())


def target_coverage(cur, version_id) -> dict:
    """Per-requirement coverage of the stored manifest. Empty when no scope has been computed."""
    cur.execute(
        "SELECT s.requirement_id::text AS requirement_id, s.manifest, r.code, r.title"
        " FROM case_gen_scope s JOIN requirement r ON r.id=s.requirement_id"
        " WHERE s.version_id=%s ORDER BY r.code",
        (version_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return {"requirements": []}
    cur.execute(
        "SELECT c.id::text AS id, c.code, c.title, c.covers,"
        " coalesce((SELECT array_agg(l.requirement_id::text) FROM case_requirement_link l"
        "   WHERE l.case_id=c.id), '{}') AS reqs,"
        " coalesce((SELECT array_agg(l.node_id::text) FROM case_node_link l WHERE l.case_id=c.id), '{}') AS nodes,"
        " coalesce((SELECT array_agg(l.attribute_id::text) FROM case_attribute_link l"
        "   WHERE l.case_id=c.id), '{}') AS attrs"
        " FROM test_case c WHERE c.status <> 'deprecated' AND (c.origin_version_id=%s OR EXISTS ("
        "  SELECT 1 FROM case_requirement_link l JOIN requirement r ON r.id=l.requirement_id"
        "  WHERE l.case_id=c.id AND r.version_id=%s))",
        (version_id, version_id),
    )
    cases = []
    for row in cur.fetchall():
        cases.append(
            {
                "id": row["id"],
                "code": row["code"],
                "title": row["title"],
                "covers": row["covers"] or [],
                "requirement_ids": set(row["reqs"] or []),
                "node_ids": row["nodes"] or [],
                "attribute_ids": row["attrs"] or [],
                "requirement_codes": [],
            }
        )
    # requirement codes for the hit check
    cur.execute("SELECT id::text AS id, code FROM requirement WHERE version_id=%s", (version_id,))
    codes = {r["id"]: r["code"] for r in cur.fetchall()}
    for case in cases:
        case["requirement_codes"] = [codes[i] for i in case["requirement_ids"] if i in codes]
    cur.execute(
        "SELECT requirement_id::text AS requirement_id, target_id, reason, proposed_by,"
        " confirmed_at IS NOT NULL AS confirmed, fingerprint FROM coverage_waiver WHERE version_id=%s",
        (version_id,),
    )
    waivers: dict[tuple[str, str, str], dict] = {}
    for row in cur.fetchall():
        waivers[(row["requirement_id"], row["fingerprint"], row["target_id"])] = row
    requirements = []
    for row in rows:
        manifest = row["manifest"] or {}
        if manifest.get("blocked"):
            requirements.append(
                {
                    "id": row["requirement_id"],
                    "code": row["code"],
                    "title": row["title"],
                    "blocked": True,
                    "message": manifest.get("message"),
                    "targets": [],
                }
            )
            continue
        fp = manifest.get("fingerprint")
        items = []
        for target in manifest.get("targets") or []:
            hits = [
                {"id": c["id"], "code": c["code"], "title": c["title"]}
                for c in cases
                if row["code"] in c["requirement_codes"] and case_covers_target(target, c)
            ]
            waiver = waivers.get((row["requirement_id"], fp, target["id"]))
            items.append(
                {
                    "id": target["id"],
                    "type": target["type"],
                    "label": target_label(target),
                    "covered": bool(hits) or bool(waiver and waiver["confirmed"]),
                    "cases": hits,
                    "waiver": None
                    if waiver is None
                    else {
                        "reason": waiver["reason"],
                        "proposed_by": waiver["proposed_by"],
                        "confirmed": waiver["confirmed"],
                    },
                }
            )
        requirements.append({"id": row["requirement_id"], "code": row["code"], "title": row["title"], "targets": items})
    return {"requirements": requirements}


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
