"""Requirements: codes, editing lock after freeze, responsible people, structure, confirmation."""

from __future__ import annotations

import re
from typing import Any

from psycopg.types.json import Jsonb

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human
from testagent.services.state import transition
from testagent.services.suggestions import NODE_NAME_SQL, with_node_name

PARTS = ("actor", "condition", "action", "result", "constraint")
ROLES = ("owner", "developer", "tester")
_CODE = re.compile(r"^REQ-(\d+)$")


def empty_structure() -> dict:
    return {p: [] for p in PARTS}


class RequirementService:
    def __init__(self, db, bus: EventBus, actor: str = "local-user"):
        self.db = db
        self.bus = bus
        self.actor = actor

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _version(cur, version_id, lock=False) -> dict:
        cur.execute("SELECT * FROM version WHERE id=%s" + (" FOR UPDATE" if lock else ""), (version_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Version not found")
        return row

    def _req(self, cur, req_id, *, editable=False, lock=False) -> dict:
        cur.execute(
            "SELECT r.*, v.status AS version_status, v.sut_id FROM requirement r"
            " JOIN version v ON v.id=r.version_id WHERE r.id=%s" + (" FOR UPDATE OF r" if lock else ""),
            (req_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Requirement not found")
        if editable and row["version_status"] != "planning":
            raise AppError(
                "CONFLICT", "The version's requirements are frozen; unfreeze them first (with a reason) to change them"
            )
        return row

    @staticmethod
    def _next_code(cur, version_id) -> str:
        cur.execute("SELECT code FROM requirement WHERE version_id=%s", (version_id,))
        numbers = [int(m.group(1)) for r in cur.fetchall() if (m := _CODE.match(r["code"]))]
        return f"REQ-{(max(numbers) if numbers else 0) + 1:03d}"

    def detail(self, req_id) -> dict:
        with self.db.tx() as cur:
            return self._detail(cur, req_id)

    def _detail(self, cur, req_id) -> dict:
        req = self._req(cur, req_id)
        cur.execute(
            "SELECT p.id AS person_id, p.name, p.active, rp.role FROM requirement_person rp"
            " JOIN person p ON p.id=rp.person_id WHERE rp.requirement_id=%s"
            " ORDER BY array_position(ARRAY['owner','developer','tester'], rp.role), p.name",
            (req_id,),
        )
        req["people"] = cur.fetchall()
        cur.execute(
            "SELECT l.role AS part, n.id AS node_id, n.kind, n.name, n.deleted_at"
            " FROM requirement_node_link l JOIN model_node n ON n.id=l.node_id"
            " WHERE l.requirement_id=%s ORDER BY l.role, n.name",
            (req_id,),
        )
        req["nodes"] = cur.fetchall()
        cur.execute(
            "SELECT l.role AS part, a.id AS attribute_id, a.name, a.display_name, a.data_type,"
            " a.unit, n.id AS node_id, n.name AS node_name, a.deleted_at"
            " FROM requirement_attribute_link l JOIN entity_attribute a ON a.id=l.attribute_id"
            " JOIN model_node n ON n.id=a.node_id WHERE l.requirement_id=%s"
            " ORDER BY l.role, n.name, a.name",
            (req_id,),
        )
        req["fields"] = cur.fetchall()
        cur.execute(
            "SELECT x.role AS part, l.id AS link_id, l.forward_name, l.reverse_name,"
            " l.cardinality, f.name AS from_name, t.name AS to_name, l.deleted_at"
            " FROM requirement_link_ref x JOIN model_link l ON l.id=x.link_id"
            " JOIN model_node f ON f.id=l.from_node_id JOIN model_node t ON t.id=l.to_node_id"
            " WHERE x.requirement_id=%s ORDER BY x.role, f.name, t.name",
            (req_id,),
        )
        req["links"] = cur.fetchall()
        cur.execute(
            f"SELECT s.*, {NODE_NAME_SQL} FROM model_suggestion s WHERE s.requirement_id=%s ORDER BY s.created_at",
            (req_id,),
        )
        req["suggestions"] = [with_node_name(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT c.id, c.code, c.title, c.status, c.scenario FROM case_requirement_link l"
            " JOIN test_case c ON c.id=l.case_id WHERE l.requirement_id=%s ORDER BY c.code",
            (req_id,),
        )
        req["cases"] = cur.fetchall()
        req["coverage"] = self._coverage(cur, req)
        return req

    @staticmethod
    def _coverage(cur, req: dict) -> dict:
        """Which of this requirement's cases cover each referenced element."""
        live = [str(c["id"]) for c in req["cases"] if c["status"] != "deprecated"]
        brief = {str(c["id"]): {"id": str(c["id"]), "code": c["code"], "title": c["title"]} for c in req["cases"]}
        cur.execute(
            "SELECT case_id::text AS case_id, node_id::text AS node_id FROM case_node_link"
            " WHERE case_id = ANY(%s::uuid[])",
            (live,),
        )
        by_node: dict[str, list[str]] = {}
        for row in cur.fetchall():
            by_node.setdefault(row["node_id"], []).append(row["case_id"])
        cur.execute(
            "SELECT c.id::text AS case_id, a.id::text AS attribute_id FROM test_case c"
            " JOIN entity_attribute a ON a.id = ANY(%s::uuid[])"
            " WHERE c.id = ANY(%s::uuid[]) AND (EXISTS (SELECT 1 FROM case_attribute_link l"
            "  WHERE l.case_id=c.id AND l.attribute_id=a.id)"
            "  OR (jsonb_typeof(c.test_data)='object' AND c.test_data ? a.name))",
            ([str(f["attribute_id"]) for f in req["fields"]], live),
        )
        by_attr: dict[str, list[str]] = {}
        for row in cur.fetchall():
            by_attr.setdefault(row["attribute_id"], []).append(row["case_id"])
        from testagent.services.cases import case_relations

        by_link: dict[str, list[str]] = {}
        for case_id, links in case_relations(cur, live).items():
            for link in links:
                by_link.setdefault(link["id"], []).append(case_id)

        def cases_of(ids: list[str]) -> list[dict]:
            return sorted((brief[i] for i in set(ids)), key=lambda c: c["code"])

        seen: set[str] = set()
        out: dict[str, list[dict]] = {"actions": [], "entities": [], "fields": [], "relations": []}
        for n in req["nodes"]:
            key = str(n["node_id"])
            if key in seen or n["kind"] not in ("action", "entity"):
                continue
            seen.add(key)
            out["actions" if n["kind"] == "action" else "entities"].append(
                {"id": key, "name": n["name"], "cases": cases_of(by_node.get(key, []))}
            )
        for f in req["fields"]:
            key = str(f["attribute_id"])
            if key in seen:
                continue
            seen.add(key)
            out["fields"].append(
                {
                    "id": key,
                    "name": f"{f['node_name']}.{f['name']}",
                    "node_id": str(f["node_id"]),
                    "cases": cases_of(by_attr.get(key, [])),
                }
            )
        for lk in req["links"]:
            key = str(lk["link_id"])
            if key in seen:
                continue
            seen.add(key)
            out["relations"].append(
                {
                    "id": key,
                    "name": f"{lk['from_name']} {lk['forward_name']} {lk['to_name']}",
                    "cases": cases_of(by_link.get(key, [])),
                }
            )
        return out

    # ------------------------------------------------------------ CRUD
    def create(self, version_id, data: dict[str, Any]) -> dict:
        with self.db.tx() as cur:
            version = self._version(cur, version_id, lock=True)  # serializes code allocation
            if version["status"] != "planning":
                raise AppError("CONFLICT", "The version's requirements are frozen; no new requirements")
            code = data.get("code") or self._next_code(cur, version_id)
            cur.execute(
                "INSERT INTO requirement(version_id, code, title, raw_text, priority)"
                " VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (version_id, code, data["title"], data.get("raw_text"), data.get("priority", "P1")),
            )
            req_id = cur.fetchone()["id"]
            log_change(cur, "requirement", req_id, "create", self.actor, {**data, "code": code})
            row = self._detail(cur, req_id)
        self.bus.publish("requirement.created", {"id": str(req_id)})
        return row

    def list(self, version_id) -> list[dict]:
        with self.db.tx() as cur:
            self._version(cur, version_id)
            cur.execute(
                "SELECT r.*, coalesce((SELECT jsonb_agg(jsonb_build_object("
                " 'person_id', p.id, 'name', p.name, 'role', rp.role) ORDER BY rp.role, p.name)"
                " FROM requirement_person rp JOIN person p ON p.id=rp.person_id"
                " WHERE rp.requirement_id=r.id), '[]'::jsonb) AS people"
                " FROM requirement r WHERE version_id=%s ORDER BY code",
                (version_id,),
            )
            return cur.fetchall()

    def update(self, req_id, data: dict[str, Any]) -> dict:
        with self.db.tx() as cur:
            req = self._req(cur, req_id, editable=True, lock=True)
            values = {k: v for k, v in data.items() if k in ("title", "raw_text", "priority")}
            if values:
                if req["status"] == "confirmed":  # content changed: needs re-confirmation
                    values["status"] = transition("requirement", "confirmed", "structured")
                    values["confirmed_at"] = None
                sets = ", ".join(f"{k}=%s" for k in values)
                cur.execute(f"UPDATE requirement SET {sets} WHERE id=%s", (*values.values(), req_id))
                log_change(cur, "requirement", req_id, "update", self.actor, values)
            row = self._detail(cur, req_id)
        self.bus.publish("requirement.updated", {"id": str(req_id)})
        return row

    def delete(self, req_id) -> None:
        with self.db.tx() as cur:
            self._req(cur, req_id, editable=True, lock=True)
            cur.execute("DELETE FROM requirement WHERE id=%s", (req_id,))
            log_change(cur, "requirement", req_id, "delete", self.actor)
        self.bus.publish("requirement.deleted", {"id": str(req_id)})

    # ------------------------------------------------------------ people
    def set_people(self, req_id, people: list[dict]) -> dict:
        pairs = list(dict.fromkeys((str(p["person_id"]), p["role"]) for p in people))
        if any(role not in ROLES for _, role in pairs):
            raise AppError("VALIDATION", "Role must be owner/developer/tester")
        with self.db.tx() as cur:
            self._req(cur, req_id, editable=True, lock=True)
            cur.execute(
                "SELECT person_id::text AS pid, role FROM requirement_person WHERE requirement_id=%s",
                (req_id,),
            )
            existing = {r["pid"] for r in cur.fetchall()}
            ids = list({pid for pid, _ in pairs})
            cur.execute(
                "SELECT id::text AS id, name, active FROM person WHERE id = ANY(%s::uuid[])",
                (ids,),
            )
            found = {r["id"]: r for r in cur.fetchall()}
            missing = [pid for pid in ids if pid not in found]
            if missing:
                raise AppError("NOT_FOUND", "Person not found", related=missing)
            newly_inactive = [found[pid]["name"] for pid in ids if not found[pid]["active"] and pid not in existing]
            if newly_inactive:
                raise AppError(
                    "VALIDATION",
                    "Deactivated people cannot be assigned to requirements",
                    related=sorted(newly_inactive),
                )
            cur.execute("DELETE FROM requirement_person WHERE requirement_id=%s", (req_id,))
            for pid, role in pairs:
                cur.execute(
                    "INSERT INTO requirement_person(requirement_id, person_id, role) VALUES (%s,%s,%s)",
                    (req_id, pid, role),
                )
            log_change(
                cur,
                "requirement",
                req_id,
                "set_people",
                self.actor,
                {"people": [{"person_id": p, "role": r} for p, r in pairs]},
            )
            row = self._detail(cur, req_id)
        self.bus.publish("requirement.people_changed", {"id": str(req_id)})
        return row

    def person_requirements(self, person_id) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute("SELECT 1 FROM person WHERE id=%s", (person_id,))
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "Person not found")
            cur.execute(
                "SELECT r.id, r.code, r.title, r.status, r.version_id, v.name AS version_name,"
                " s.code AS sut_code, array_agg(rp.role ORDER BY rp.role) AS roles"
                " FROM requirement_person rp JOIN requirement r ON r.id=rp.requirement_id"
                " JOIN version v ON v.id=r.version_id JOIN sut s ON s.id=v.sut_id"
                " WHERE rp.person_id=%s GROUP BY r.id, v.name, s.code"
                " ORDER BY s.code, v.name, r.code",
                (person_id,),
            )
            return cur.fetchall()

    # ------------------------------------------------------------ structure
    def _write_structure(self, cur, req, structure: dict, *, agent_run_id=None) -> None:
        """Replace structure + node/field links. Items: {text, node_id?, attribute_id?|missing}.

        An item may point at an entity field (attribute_id, e.g. PurchaseOrder.amount); its entity is
        then linked as the item's node as well."""
        attr_ids = {
            str(i["attribute_id"]) for part in PARTS for i in structure.get(part) or [] if i.get("attribute_id")
        }
        attrs: dict[str, dict] = {}
        if attr_ids:
            cur.execute(
                "SELECT a.id::text AS id, a.node_id::text AS node_id FROM entity_attribute a"
                " JOIN model_node n ON n.id=a.node_id WHERE a.id = ANY(%s::uuid[])"
                " AND a.sut_id=%s AND a.deleted_at IS NULL AND n.deleted_at IS NULL",
                (list(attr_ids), req["sut_id"]),
            )
            attrs = {r["id"]: r for r in cur.fetchall()}
            bad = sorted(attr_ids - set(attrs))
            if bad:
                raise AppError("VALIDATION", "The structure references a field that does not exist", related=bad)
        link_ids = {str(i["link_id"]) for part in PARTS for i in structure.get(part) or [] if i.get("link_id")}
        links: dict[str, dict] = {}
        if link_ids:
            cur.execute(
                "SELECT id::text AS id, from_node_id::text AS node_id FROM model_link"
                " WHERE id = ANY(%s::uuid[]) AND sut_id=%s AND deleted_at IS NULL",
                (list(link_ids), req["sut_id"]),
            )
            links = {r["id"]: r for r in cur.fetchall()}
            bad = sorted(link_ids - set(links))
            if bad:
                raise AppError("VALIDATION", "The structure references a link that does not exist", related=bad)
        clean = empty_structure()
        node_ids = set()
        for part in PARTS:
            for item in structure.get(part) or []:
                attr_id = str(item["attribute_id"]) if item.get("attribute_id") else None
                link_id = str(item["link_id"]) if item.get("link_id") else None
                node_id = item.get("node_id")
                if attr_id and not node_id:
                    node_id = attrs[attr_id]["node_id"]
                if link_id and not node_id:
                    node_id = links[link_id]["node_id"]
                entry = {"text": item["text"], "node_id": str(node_id) if node_id else None}
                if attr_id:
                    entry["attribute_id"] = attr_id
                if link_id:
                    entry["link_id"] = link_id
                entry["missing"] = node_id is None
                clean[part].append(entry)
                if node_id:
                    node_ids.add(str(node_id))
        if node_ids:
            cur.execute(
                "SELECT id::text AS id FROM model_node WHERE id = ANY(%s::uuid[]) AND sut_id=%s AND deleted_at IS NULL",
                (list(node_ids), req["sut_id"]),
            )
            valid = {r["id"] for r in cur.fetchall()}
            bad = sorted(node_ids - valid)
            if bad:
                raise AppError("VALIDATION", "The structure references a node that does not exist", related=bad)
        cur.execute("DELETE FROM requirement_node_link WHERE requirement_id=%s", (req["id"],))
        cur.execute("DELETE FROM requirement_attribute_link WHERE requirement_id=%s", (req["id"],))
        cur.execute("DELETE FROM requirement_link_ref WHERE requirement_id=%s", (req["id"],))
        for part, items in clean.items():
            for nid in dict.fromkeys(str(i["node_id"]) for i in items if i["node_id"]):
                cur.execute(
                    "INSERT INTO requirement_node_link(requirement_id, node_id, role) VALUES (%s,%s,%s)",
                    (req["id"], nid, part),
                )
            for lid in dict.fromkeys(i["link_id"] for i in items if i.get("link_id")):
                cur.execute(
                    "INSERT INTO requirement_link_ref(requirement_id, link_id, role) VALUES (%s,%s,%s)",
                    (req["id"], lid, part),
                )
            for aid in dict.fromkeys(i["attribute_id"] for i in items if i.get("attribute_id")):
                cur.execute(
                    "INSERT INTO requirement_attribute_link(requirement_id, attribute_id, role) VALUES (%s,%s,%s)",
                    (req["id"], aid, part),
                )
        status = req["status"]
        if status != "structured":
            status = transition("requirement", status, "structured")
        cur.execute(
            "UPDATE requirement SET structured=%s, status=%s, confirmed_at=NULL,"
            " agent_run_id=coalesce(%s, agent_run_id) WHERE id=%s",
            (Jsonb(clean), status, agent_run_id, req["id"]),
        )

    def set_structure(self, req_id, structure: dict) -> dict:
        with self.db.tx() as cur:
            req = self._req(cur, req_id, editable=True, lock=True)
            self._write_structure(cur, req, structure)
            log_change(cur, "requirement", req_id, "structure", self.actor, structure)
            row = self._detail(cur, req_id)
        self.bus.publish("requirement.structured", {"id": str(req_id)})
        return row

    def confirm(self, req_id) -> dict:
        ensure_human(self.actor, "Confirm requirements")
        with self.db.tx() as cur:
            req = self._req(cur, req_id, editable=True, lock=True)
            transition("requirement", req["status"], "confirmed")
            cur.execute(
                "SELECT count(*) AS n FROM requirement_person WHERE requirement_id=%s AND role='owner'",
                (req_id,),
            )
            if cur.fetchone()["n"] < 1:
                raise AppError(
                    "VALIDATION",
                    "A requirement needs at least 1 owner before it can be confirmed",
                    field_errors=[{"field": "people", "msg": "Missing owner"}],
                )
            cur.execute(
                "UPDATE requirement SET status='confirmed', confirmed_at=now(), confirmed_by=%s WHERE id=%s",
                (self.actor, req_id),
            )
            log_change(cur, "requirement", req_id, "confirm", self.actor)
            row = self._detail(cur, req_id)
        self.bus.publish("requirement.confirmed", {"id": str(req_id)})
        return row
