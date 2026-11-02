"""Test cases (M1-07): CRUD with revisions, human-only `ready`, coverage report and export."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from typing import Any

from psycopg.types.json import Jsonb

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human
from testagent.services.state import transition

CONTENT_FIELDS = (
    "title",
    "test_point",
    "priority",
    "type_tag",
    "scenario",
    "mode",
    "preconditions",
    "steps",
    "test_data",
    "expected",
    "code_path",
    "category",
    "quality_tags",
)
JSON_FIELDS = {"steps", "test_data", "quality_tags"}
SCENARIO_LABEL = {"normal": "Normal", "boundary": "Boundary", "exception": "Exception"}
STATUS_LABEL = {"draft": "Draft", "ready": "Ready", "deprecated": "Deprecated"}
MODE_LABEL = {"manual": "Manual", "automated": "Automated"}
EXPORT_COLUMNS = [
    "Code",
    "Title",
    "Test point",
    "Requirements",
    "Nodes",
    "Priority",
    "Type",
    "Scenario",
    "Preconditions",
    "Steps",
    "Test data",
    "Expected result",
    "Status",
    "Mode",
]


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def clean_steps(steps) -> list[dict]:
    return [{k: v for k, v in step.items() if v not in (None, "")} for step in steps or []]


def format_steps(steps: list[dict]) -> str:
    lines = []
    for i, step in enumerate(steps or [], start=1):
        line = f"{i}. {step.get('action', '')}"
        if step.get("data"):
            line += f" (data: {step['data']})"
        if step.get("expected"):
            line += f" → {step['expected']}"
        lines.append(line)
    return "\n".join(lines)


CASE_LINKS_SQL = (
    "SELECT DISTINCT x.case_id::text AS case_id, l.id::text AS id,"
    " f.name || ' ' || l.forward_name || ' ' || t.name AS name FROM ("
    "  SELECT cl.case_id, r.link_id FROM case_requirement_link cl"
    "  JOIN requirement_link_ref r ON r.requirement_id=cl.requirement_id"
    "  UNION SELECT ca.case_id, ml.id FROM case_attribute_link ca"
    "  JOIN model_link ml ON ml.fk_attribute_id=ca.attribute_id"
    " ) x JOIN model_link l ON l.id=x.link_id AND l.deleted_at IS NULL"
    " JOIN model_node f ON f.id=l.from_node_id JOIN model_node t ON t.id=l.to_node_id"
    " WHERE x.case_id = ANY(%s::uuid[]) ORDER BY name"
)


def case_relations(cur, case_ids) -> dict[str, list[dict]]:
    """Relations a case covers: referenced by its requirements, or whose foreign-key
    field the case exercises. {case_id: [{id, name}]}"""
    out: dict[str, list[dict]] = {}
    if not case_ids:
        return out
    cur.execute(CASE_LINKS_SQL, ([str(c) for c in case_ids],))
    for row in cur.fetchall():
        out.setdefault(row["case_id"], []).append({"id": row["id"], "name": row["name"]})
    return out


class CaseService:
    def __init__(self, db, bus: EventBus, actor: str = "local-user"):
        self.db = db
        self.bus = bus
        self.actor = actor

    @property
    def is_agent(self) -> bool:
        return self.actor == "agent" or self.actor.startswith("agent:")

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _case(cur, case_id, lock=False) -> dict:
        cur.execute("SELECT * FROM test_case WHERE id=%s" + (" FOR UPDATE" if lock else ""), (case_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Test case not found")
        return row

    @staticmethod
    def _check_links(cur, sut_id, requirement_ids: list, node_ids: list) -> None:
        errors = []
        if requirement_ids:
            cur.execute(
                "SELECT r.id::text AS id FROM requirement r JOIN version v ON v.id=r.version_id"
                " WHERE r.id = ANY(%s::uuid[]) AND v.sut_id=%s",
                ([str(r) for r in requirement_ids], sut_id),
            )
            known = {r["id"] for r in cur.fetchall()}
            errors += [
                {"field": "requirement_ids", "msg": f"Requirement {r} does not belong to this SUT"}
                for r in map(str, requirement_ids)
                if r not in known
            ]
        if node_ids:
            cur.execute(
                "SELECT id::text AS id FROM model_node WHERE id = ANY(%s::uuid[]) AND sut_id=%s AND deleted_at IS NULL",
                ([str(n) for n in node_ids], sut_id),
            )
            known = {r["id"] for r in cur.fetchall()}
            errors += [
                {"field": "node_ids", "msg": f"Node {n} does not belong to this SUT"}
                for n in map(str, node_ids)
                if n not in known
            ]
        if errors:
            raise AppError("VALIDATION", "The case's linked requirements or nodes are invalid", field_errors=errors)

    @staticmethod
    def _set_links(cur, case_id, requirement_ids=None, node_ids=None) -> None:
        if requirement_ids is not None:
            cur.execute("DELETE FROM case_requirement_link WHERE case_id=%s", (case_id,))
            for rid in dict.fromkeys(map(str, requirement_ids)):
                cur.execute(
                    "INSERT INTO case_requirement_link(case_id, requirement_id) VALUES (%s,%s)",
                    (case_id, rid),
                )
        if node_ids is not None:
            cur.execute("DELETE FROM case_node_link WHERE case_id=%s", (case_id,))
            for nid in dict.fromkeys(map(str, node_ids)):
                cur.execute("INSERT INTO case_node_link(case_id, node_id) VALUES (%s,%s)", (case_id, nid))

    @staticmethod
    def _set_fields(cur, case_id, sut_id, attribute_ids) -> None:
        if attribute_ids is None:
            return
        ids = list(dict.fromkeys(map(str, attribute_ids)))
        if ids:
            cur.execute(
                "SELECT id::text AS id FROM entity_attribute WHERE id = ANY(%s::uuid[])"
                " AND sut_id=%s AND deleted_at IS NULL",
                (ids, sut_id),
            )
            known = {r["id"] for r in cur.fetchall()}
            bad = [a for a in ids if a not in known]
            if bad:
                raise AppError(
                    "VALIDATION",
                    "The case's linked fields are invalid",
                    field_errors=[{"field": "attribute_ids", "msg": f"Field {a} does not exist"} for a in bad],
                )
        cur.execute("DELETE FROM case_attribute_link WHERE case_id=%s", (case_id,))
        for aid in ids:
            cur.execute(
                "INSERT INTO case_attribute_link(case_id, attribute_id) VALUES (%s,%s)",
                (case_id, aid),
            )

    @staticmethod
    def _fields(cur, case_id) -> list[dict]:
        cur.execute(
            "SELECT a.id, a.name, a.display_name, a.data_type, n.id AS node_id,"
            " n.name AS node_name FROM case_attribute_link l"
            " JOIN entity_attribute a ON a.id=l.attribute_id JOIN model_node n ON n.id=a.node_id"
            " WHERE l.case_id=%s ORDER BY n.name, a.name",
            (case_id,),
        )
        return cur.fetchall()

    @staticmethod
    def _links(cur, case_id) -> tuple[list[dict], list[dict]]:
        cur.execute(
            "SELECT r.id, r.code, r.title, r.version_id FROM case_requirement_link l"
            " JOIN requirement r ON r.id=l.requirement_id WHERE l.case_id=%s ORDER BY r.code",
            (case_id,),
        )
        reqs = cur.fetchall()
        cur.execute(
            "SELECT n.id, n.kind, n.name, n.deleted_at IS NOT NULL AS deleted FROM case_node_link l"
            " JOIN model_node n ON n.id=l.node_id WHERE l.case_id=%s ORDER BY n.kind, n.name",
            (case_id,),
        )
        return reqs, cur.fetchall()

    def _content(self, cur, case: dict) -> dict:
        reqs, nodes = self._links(cur, case["id"])
        content = {
            **{f: case.get(f) for f in CONTENT_FIELDS},
            "requirement_ids": [str(r["id"]) for r in reqs],
            "node_ids": [str(n["id"]) for n in nodes],
        }
        fields = self._fields(cur, case["id"])
        if fields:
            content["attribute_ids"] = [str(f["id"]) for f in fields]
        return content

    def _revise(self, cur, case_id, revision: int) -> None:
        case = self._case(cur, case_id)
        cur.execute(
            "INSERT INTO case_revision(case_id, revision, content, author) VALUES (%s,%s,%s,%s)",
            (case_id, revision, Jsonb(self._content(cur, case), dumps=_dumps), self.actor),
        )

    def _detail(self, cur, case_id) -> dict:
        case = self._case(cur, case_id)
        case["requirements"], case["nodes"] = self._links(cur, case_id)
        case["fields"] = self._fields(cur, case_id)
        case["relations"] = case_relations(cur, [case_id]).get(str(case_id), [])
        cur.execute("SELECT code FROM sut WHERE id=%s", (case["sut_id"],))
        case["sut_code"] = cur.fetchone()["code"]
        cur.execute(
            "SELECT t.id, t.name, t.version_id, tc.seq FROM task_case tc"
            " JOIN test_task t ON t.id=tc.task_id WHERE tc.case_id=%s ORDER BY t.created_at",
            (case_id,),
        )
        case["tasks"] = cur.fetchall()
        return case

    @staticmethod
    def _next_code(cur, sut_id) -> str:
        cur.execute("SELECT 1 FROM sut WHERE id=%s FOR UPDATE", (sut_id,))  # serialize codes
        if cur.fetchone() is None:
            raise AppError("NOT_FOUND", "SUT not found")
        cur.execute(
            "SELECT coalesce(max(substring(code from '^TC-(\\d+)$')::int), 0) AS n FROM test_case WHERE sut_id=%s",
            (sut_id,),
        )
        return f"TC-{cur.fetchone()['n'] + 1:03d}"

    # ------------------------------------------------------------ CRUD
    def create(self, sut_id, data: dict[str, Any], *, cur=None, agent_run_id=None) -> dict:
        if cur is None:
            with self.db.tx() as cur:
                row = self.create(sut_id, data, cur=cur, agent_run_id=agent_run_id)
            self.bus.publish("case.created", {"id": str(row["id"])})
            return row
        code = self._next_code(cur, sut_id)
        req_ids = list(data.get("requirement_ids") or [])
        node_ids = list(data.get("node_ids") or [])
        self._check_links(cur, sut_id, req_ids, node_ids)
        origin = data.get("origin_version_id")
        if origin is None and req_ids:
            cur.execute("SELECT version_id FROM requirement WHERE id=%s", (str(req_ids[0]),))
            origin = cur.fetchone()["version_id"]
        snapshot = None
        if origin is not None:
            cur.execute("SELECT model_snapshot_id FROM version WHERE id=%s", (origin,))
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", "Version not found")
            snapshot = row["model_snapshot_id"]
        values = {f: data.get(f) for f in CONTENT_FIELDS if data.get(f) is not None}
        values["steps"] = clean_steps(values.get("steps"))
        cols = list(values)
        params = [Jsonb(values[c], dumps=_dumps) if c in JSON_FIELDS else values[c] for c in cols]
        cur.execute(
            f"INSERT INTO test_case(sut_id, code, origin_version_id, snapshot_id, source,"
            f" agent_run_id, {', '.join(cols)}) VALUES (%s,%s,%s,%s,%s,%s" + ", %s" * len(cols) + ") RETURNING id",
            (
                sut_id,
                code,
                origin,
                snapshot,
                "agent" if agent_run_id else "human",
                agent_run_id,
                *params,
            ),
        )
        case_id = cur.fetchone()["id"]
        self._set_links(cur, case_id, req_ids, node_ids)
        self._set_fields(cur, case_id, sut_id, data.get("attribute_ids"))
        self._revise(cur, case_id, 1)
        log_change(cur, "test_case", case_id, "create", self.actor, {"code": code})
        return self._detail(cur, case_id)

    def get(self, case_id) -> dict:
        with self.db.tx() as cur:
            return self._detail(cur, case_id)

    def list(
        self,
        sut_id,
        *,
        version_id=None,
        requirement_id=None,
        status: str | None = None,
        q: str | None = None,
    ) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT c.id, c.code, c.title, c.test_point, c.priority, c.type_tag, c.scenario,"
                " c.mode, c.status, c.source, c.revision, c.updated_at, c.automation_status,"
                " c.automation_note, c.category, c.quality_tags, c.category_suggestion,"
                " coalesce((SELECT array_agg(r.code ORDER BY r.code) FROM case_requirement_link l"
                "   JOIN requirement r ON r.id=l.requirement_id WHERE l.case_id=c.id), '{}')"
                "   AS requirement_codes,"
                " (SELECT count(*) FROM case_node_link l WHERE l.case_id=c.id) AS node_count,"
                " coalesce((SELECT jsonb_agg(jsonb_build_object('id', n.id, 'name', n.name)"
                "   ORDER BY n.name) FROM case_node_link l JOIN model_node n ON n.id=l.node_id"
                "   WHERE l.case_id=c.id AND n.kind='action'), '[]') AS cov_actions,"
                " coalesce((SELECT jsonb_agg(jsonb_build_object('id', n.id, 'name', n.name)"
                "   ORDER BY n.name) FROM case_node_link l JOIN model_node n ON n.id=l.node_id"
                "   WHERE l.case_id=c.id AND n.kind='entity'), '[]') AS cov_entities,"
                " coalesce((SELECT jsonb_agg(jsonb_build_object('id', a.id, 'name',"
                "   n.name || '.' || a.name, 'node_id', n.id) ORDER BY n.name, a.name)"
                "   FROM case_attribute_link l JOIN entity_attribute a ON a.id=l.attribute_id"
                "   JOIN model_node n ON n.id=a.node_id WHERE l.case_id=c.id), '[]') AS cov_fields"
                " FROM test_case c WHERE c.sut_id=%(sut)s"
                " AND (%(status)s::text IS NULL OR c.status=%(status)s)"
                " AND (%(q)s::text IS NULL OR c.title ILIKE %(like)s OR c.code ILIKE %(like)s"
                "      OR c.test_point ILIKE %(like)s)"
                " AND (%(req)s::uuid IS NULL OR EXISTS (SELECT 1 FROM case_requirement_link l"
                "      WHERE l.case_id=c.id AND l.requirement_id=%(req)s::uuid))"
                " AND (%(ver)s::uuid IS NULL OR c.origin_version_id=%(ver)s::uuid"
                "      OR EXISTS (SELECT 1 FROM case_requirement_link l JOIN requirement r"
                "        ON r.id=l.requirement_id WHERE l.case_id=c.id"
                "        AND r.version_id=%(ver)s::uuid))"
                " ORDER BY c.code",
                {
                    "sut": sut_id,
                    "status": status,
                    "q": q,
                    "like": f"%{q}%",
                    "req": str(requirement_id) if requirement_id else None,
                    "ver": str(version_id) if version_id else None,
                },
            )
            rows = cur.fetchall()
            relations = case_relations(cur, [r["id"] for r in rows])
        for row in rows:
            row["coverage"] = {
                "actions": row.pop("cov_actions"),
                "entities": row.pop("cov_entities"),
                "fields": row.pop("cov_fields"),
                "relations": relations.get(str(row["id"]), []),
            }
        return rows

    def update(self, case_id, data: dict[str, Any]) -> dict:
        with self.db.tx() as cur:
            case = self._case(cur, case_id, lock=True)
            if case["status"] == "deprecated":
                raise AppError("CONFLICT", "The case is deprecated and cannot be modified")
            before = self._content(cur, case)
            self._check_links(cur, case["sut_id"], data.get("requirement_ids") or [], data.get("node_ids") or [])
            fields = {f: data[f] for f in CONTENT_FIELDS if f in data}
            if "steps" in fields:
                fields["steps"] = clean_steps(fields["steps"])
            if fields:
                sets = ", ".join(f"{f}=%s" for f in fields)
                cur.execute(
                    f"UPDATE test_case SET {sets} WHERE id=%s",
                    (
                        *[Jsonb(v, dumps=_dumps) if f in JSON_FIELDS else v for f, v in fields.items()],
                        case_id,
                    ),
                )
            self._set_links(cur, case_id, data.get("requirement_ids"), data.get("node_ids"))
            self._set_fields(cur, case_id, case["sut_id"], data.get("attribute_ids"))
            after = self._content(cur, self._case(cur, case_id))
            if after != before:
                status = case["status"]
                if self.is_agent and status == "ready":
                    status = "draft"  # agent edits always go back to human review (C01)
                cur.execute(
                    "UPDATE test_case SET revision=revision+1, status=%s, updated_at=now()"
                    " WHERE id=%s RETURNING revision",
                    (status, case_id),
                )
                revision = cur.fetchone()["revision"]
                self._revise(cur, case_id, revision)
                changed = {k: after[k] for k in after if after[k] != before.get(k)}
                log_change(cur, "test_case", case_id, "update", self.actor, changed)
            row = self._detail(cur, case_id)
        self.bus.publish("case.updated", {"id": str(case_id)})
        return row

    def set_status(self, case_id, target: str) -> dict:
        if target == "ready":
            ensure_human(self.actor, "Set case ready")
        with self.db.tx() as cur:
            case = self._case(cur, case_id, lock=True)
            transition("case", case["status"], target)
            cur.execute("UPDATE test_case SET status=%s, updated_at=now() WHERE id=%s", (target, case_id))
            log_change(cur, "test_case", case_id, "status", self.actor, {"status": target})
            row = self._detail(cur, case_id)
        self.bus.publish(f"case.{target}", {"id": str(case_id)})
        return row

    def revisions(self, case_id) -> list[dict]:
        with self.db.tx() as cur:
            self._case(cur, case_id)
            cur.execute(
                "SELECT revision, content, author, created_at FROM case_revision"
                " WHERE case_id=%s ORDER BY revision DESC",
                (case_id,),
            )
            return cur.fetchall()

    # ------------------------------------------------------------ coverage
    @staticmethod
    def _version(cur, version_id) -> dict:
        cur.execute("SELECT * FROM version WHERE id=%s", (version_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Version not found")
        return row

    def _coverage(self, cur, version_id) -> dict:
        version = self._version(cur, version_id)
        cur.execute(
            "SELECT r.id, r.code, r.title, (SELECT count(*) FROM case_requirement_link l"
            "  JOIN test_case c ON c.id=l.case_id WHERE l.requirement_id=r.id"
            "  AND c.status <> 'deprecated') AS cases,"
            " coalesce((SELECT jsonb_agg(jsonb_build_object('id', c.id, 'code', c.code,"
            "   'title', c.title) ORDER BY c.code) FROM case_requirement_link l"
            "  JOIN test_case c ON c.id=l.case_id WHERE l.requirement_id=r.id"
            "  AND c.status <> 'deprecated'), '[]') AS case_list"
            " FROM requirement r WHERE r.version_id=%s ORDER BY r.code",
            (version_id,),
        )
        reqs = cur.fetchall()
        # cases in scope: active cases linked to this version's requirements or created for it
        cur.execute(
            "SELECT c.id, c.priority, c.type_tag, c.scenario FROM test_case c"
            " WHERE c.status <> 'deprecated' AND (c.origin_version_id=%(v)s OR EXISTS ("
            "  SELECT 1 FROM case_requirement_link l JOIN requirement r ON r.id=l.requirement_id"
            "  WHERE l.case_id=c.id AND r.version_id=%(v)s))",
            {"v": version_id},
        )
        cases = cur.fetchall()
        ids = [c["id"] for c in cases]
        cur.execute(
            "SELECT n.id, n.name, (SELECT count(*) FROM case_node_link l"
            "  WHERE l.node_id=n.id AND l.case_id = ANY(%(ids)s::uuid[])) AS cases,"
            " coalesce((SELECT jsonb_agg(jsonb_build_object('id', c.id, 'code', c.code,"
            "   'title', c.title) ORDER BY c.code) FROM case_node_link l"
            "  JOIN test_case c ON c.id=l.case_id WHERE l.node_id=n.id"
            "  AND l.case_id = ANY(%(ids)s::uuid[])), '[]') AS case_list"
            " FROM model_node n WHERE n.sut_id=%(sut)s AND n.kind='action'"
            " AND n.deleted_at IS NULL ORDER BY n.name",
            {"ids": ids, "sut": version["sut_id"]},
        )
        actions = cur.fetchall()
        # fields referenced by this version's requirements; covered by a linked case or by a
        # case whose test data sets that field
        cur.execute(
            "SELECT DISTINCT a.id, n.name || '.' || a.name AS name, n.id AS node_id,"
            " (SELECT count(*) FROM test_case c WHERE c.id = ANY(%(ids)s::uuid[]) AND ("
            "   EXISTS (SELECT 1 FROM case_attribute_link cl WHERE cl.case_id=c.id"
            "     AND cl.attribute_id=a.id)"
            "   OR (jsonb_typeof(c.test_data)='object' AND c.test_data ? a.name))) AS cases,"
            " coalesce((SELECT jsonb_agg(jsonb_build_object('id', c.id, 'code', c.code,"
            "   'title', c.title) ORDER BY c.code) FROM test_case c"
            "  WHERE c.id = ANY(%(ids)s::uuid[]) AND ("
            "   EXISTS (SELECT 1 FROM case_attribute_link cl WHERE cl.case_id=c.id"
            "     AND cl.attribute_id=a.id)"
            "   OR (jsonb_typeof(c.test_data)='object' AND c.test_data ? a.name))), '[]')"
            "   AS case_list"
            " FROM requirement_attribute_link l JOIN requirement r ON r.id=l.requirement_id"
            " JOIN entity_attribute a ON a.id=l.attribute_id JOIN model_node n ON n.id=a.node_id"
            " WHERE r.version_id=%(v)s AND a.deleted_at IS NULL ORDER BY name",
            {"ids": ids, "v": version_id},
        )
        fields = cur.fetchall()
        # relations referenced by this version's requirements; covered by cases in scope
        cur.execute(
            "SELECT DISTINCT l.id, f.name || ' ' || l.forward_name || ' ' || t.name AS name"
            " FROM requirement_link_ref x JOIN requirement r ON r.id=x.requirement_id"
            " JOIN model_link l ON l.id=x.link_id AND l.deleted_at IS NULL"
            " JOIN model_node f ON f.id=l.from_node_id JOIN model_node t ON t.id=l.to_node_id"
            " WHERE r.version_id=%s ORDER BY name",
            (version_id,),
        )
        relation_rows = cur.fetchall()
        by_case = case_relations(cur, ids)
        codes = {}
        if ids:
            cur.execute(
                "SELECT id::text AS id, code, title FROM test_case WHERE id = ANY(%s::uuid[])",
                (ids,),
            )
            codes = {r["id"]: r for r in cur.fetchall()}
        relations = []
        for row in relation_rows:
            covering = sorted(
                (codes[cid] for cid, links in by_case.items() if any(lk["id"] == str(row["id"]) for lk in links)),
                key=lambda c: c["code"],
            )
            relations.append({**row, "cases": len(covering), "case_list": covering})

        def block(items: list[dict], key: str) -> dict:
            return {
                "total": len(items),
                "covered": sum(1 for i in items if i["cases"]),
                "uncovered": [
                    {
                        "id": str(i["id"]),
                        key: i[key],
                        **({"title": i["title"]} if "title" in i else {}),
                    }
                    for i in items
                    if not i["cases"]
                ],
                "items": [
                    {
                        "id": str(i["id"]),
                        key: i[key],
                        **({"title": i["title"]} if "title" in i else {}),
                        **({"node_id": str(i["node_id"])} if i.get("node_id") else {}),
                        "cases": i["cases"],
                        "case_list": [
                            {"id": str(c["id"]), "code": c["code"], "title": c["title"]}
                            for c in i.get("case_list") or []
                        ],
                    }
                    for i in items
                ],
            }

        def dist(field: str) -> dict:
            return dict(Counter(c[field] for c in cases if c[field]))

        return {
            "version_id": str(version_id),
            "sut_id": str(version["sut_id"]),
            "snapshot_id": str(version["model_snapshot_id"]) if version["model_snapshot_id"] else None,
            "cases": len(cases),
            "requirements": block(reqs, "code"),
            "actions": block(actions, "name"),
            "fields": block(fields, "name"),
            "relations": block(relations, "name"),
            "by_priority": dist("priority"),
            "by_type": dist("type_tag"),
            "by_scenario": dist("scenario"),
        }

    def coverage(self, version_id) -> dict:
        with self.db.tx() as cur:
            return self._coverage(cur, version_id)

    def save_coverage(self, version_id, *, cur=None, agent_run_id=None) -> dict:
        if cur is None:
            with self.db.tx() as cur:
                return self.save_coverage(version_id, cur=cur, agent_run_id=agent_run_id)
        content = self._coverage(cur, version_id)
        cur.execute(
            "INSERT INTO coverage_report(version_id, content, source, agent_run_id) VALUES (%s,%s,%s,%s) RETURNING *",
            (
                version_id,
                Jsonb(content, dumps=_dumps),
                "agent" if agent_run_id else "human",
                agent_run_id,
            ),
        )
        return cur.fetchone()

    def coverage_reports(self, version_id) -> list[dict]:
        with self.db.tx() as cur:
            self._version(cur, version_id)
            cur.execute(
                "SELECT id, source, agent_run_id, created_at,"
                " content->'requirements'->>'covered' AS req_covered,"
                " content->'requirements'->>'total' AS req_total, (content->>'cases')::int AS cases"
                " FROM coverage_report WHERE version_id=%s ORDER BY created_at DESC LIMIT 50",
                (version_id,),
            )
            return cur.fetchall()

    # ------------------------------------------------------------ export
    def export_rows(self, version_id) -> list[list[str]]:
        with self.db.tx() as cur:
            version = self._version(cur, version_id)
        rows = []
        for item in self.list(version["sut_id"], version_id=version_id):
            if item["status"] == "deprecated":
                continue
            with self.db.tx() as cur:
                case = self._detail(cur, item["id"])
            rows.append(
                [
                    case["code"],
                    case["title"],
                    case["test_point"] or "",
                    ", ".join(r["code"] for r in case["requirements"]),
                    ", ".join(n["name"] for n in case["nodes"]),
                    case["priority"],
                    case["type_tag"],
                    SCENARIO_LABEL.get(case["scenario"] or "", ""),
                    case["preconditions"] or "",
                    format_steps(case["steps"]),
                    _dumps(case["test_data"]) if case["test_data"] is not None else "",
                    case["expected"] or "",
                    STATUS_LABEL[case["status"]],
                    MODE_LABEL[case["mode"]],
                ]
            )
        return rows

    def export(self, version_id, fmt: str) -> tuple[str, str]:
        rows = self.export_rows(version_id)
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\r\n")
            writer.writerow(EXPORT_COLUMNS)
            writer.writerows(rows)
            return "\ufeff" + buf.getvalue(), "text/csv; charset=utf-8"  # BOM for Excel

        def cell(v: str) -> str:
            return v.replace("|", "\\|").replace("\r", "").replace("\n", "<br>")

        lines = [
            "| " + " | ".join(EXPORT_COLUMNS) + " |",
            "|" + "---|" * len(EXPORT_COLUMNS),
            *("| " + " | ".join(cell(v) for v in r) + " |" for r in rows),
        ]
        return "\n".join(lines) + "\n", "text/markdown; charset=utf-8"
