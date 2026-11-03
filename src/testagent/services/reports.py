"""Reports (T-11.3..T-11.5): immutable snapshots for a task run or a version (§6.3). The optional
AI summary (`summarize_report`) is objective only; without a model the report is still made."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from testagent.agent.runtime import Entry
from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.stats import (
    EXECUTED,
    aggregate_people,
    aggregate_requirements,
    executed_by_requirement,
    load_weights,
    requirement_rows,
    scoped_defects,
)

log = logging.getLogger("testagent.reports")


class SummaryOut(BaseModel):
    summary: str = Field(min_length=1, max_length=6000)


def summary_entry() -> Entry:
    return Entry(
        name="summarize_report",
        output_schema=SummaryOut,
        tools=(),
        instructions=(
            "Summarise the test report in the output language in a few short paragraphs: scope, pass rate "
            "(passed / executed; always state skipped, blocked and not-executed counts "
            "separately — they are not passes), "
            "main failures, requirements with the most/most severe defects. Describe facts "
            "objectively; do not judge or blame people and do not add facts that are not in the "
            "report."
        ),
    )


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _summary(statuses: list[str], total: int) -> dict:
    counts = {k: statuses.count(k) for k in ("passed", "failed", "error", "blocked", "skipped")}
    executed = counts["passed"] + counts["failed"] + counts["error"]
    return {
        "total": total,
        **counts,
        "not_executed": total - len(statuses),
        "executed": executed,
        # passed / executed (passed+failed+error); skipped, blocked and not run never count
        "pass_rate": (counts["passed"] / executed) if executed else None,
    }


class ReportService:
    def __init__(self, db, bus: EventBus, runtime=None, actor: str | None = None):
        self.db = db
        self.bus = bus
        self.runtime = runtime
        self.actor = actor or current_actor()

    # ------------------------------------------------------------ reads
    def get(self, report_id) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM report WHERE id=%s", (report_id,))
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Report not found")
        return row

    def list(self, scope_type=None, scope_id=None, version_id=None) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT r.id, r.scope_type, r.scope_id, r.created_at, r.created_by,"
                " r.content->'summary' AS summary, r.ai_summary IS NOT NULL AS has_ai_summary,"
                " COALESCE(t.version_id, v.id) AS version_id, t.name AS task_name,"
                " COALESCE(v.name, tv.name) AS version_name"
                " FROM report r"
                " LEFT JOIN task_run tr ON r.scope_type='task_run' AND tr.id=r.scope_id"
                " LEFT JOIN test_task t ON t.id=tr.task_id"
                " LEFT JOIN version tv ON tv.id=t.version_id"
                " LEFT JOIN version v ON r.scope_type='version' AND v.id=r.scope_id"
                " WHERE (%(st)s::text IS NULL OR r.scope_type=%(st)s)"
                " AND (%(si)s::uuid IS NULL OR r.scope_id=%(si)s::uuid)"
                " AND (%(v)s::uuid IS NULL OR COALESCE(t.version_id, v.id)=%(v)s::uuid)"
                " ORDER BY r.created_at DESC LIMIT 200",
                {"st": scope_type, "si": scope_id, "v": version_id},
            )
            return cur.fetchall()

    # ------------------------------------------------------------ generation
    def for_run(self, run_id) -> dict:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT r.*, t.name AS task_name, t.version_id, v.name AS version_name,"
                " v.model_snapshot_id FROM task_run r JOIN test_task t ON t.id=r.task_id"
                " JOIN version v ON v.id=t.version_id WHERE r.id=%s",
                (run_id,),
            )
            run = cur.fetchone()
            if run is None:
                raise AppError("NOT_FOUND", "Run not found")
            if run["status"] in ("queued", "running"):
                raise AppError("CONFLICT", "The run has not finished yet")
            cur.execute(
                "SELECT c.id::text AS id, c.code, c.title FROM task_case tc"
                " JOIN test_case c ON c.id=tc.case_id WHERE tc.task_id=%s ORDER BY tc.seq",
                (run["task_id"],),
            )
            cases = cur.fetchall()
            cur.execute(
                "SELECT e.id::text AS id, e.case_id::text AS case_id, e.status,"
                " e.failed_assertion, e.error FROM case_execution e"
                " WHERE e.task_run_id=%s ORDER BY e.created_at, e.id",
                (run_id,),
            )
            executions = cur.fetchall()
            known = {c["id"] for c in cases}
            cases += self._extra_cases(cur, [e["case_id"] for e in executions if e["case_id"] not in known])
            defects = scoped_defects(cur, execution_ids=[e["id"] for e in executions])
            scope = {
                "type": "task_run",
                "task_run_id": str(run_id),
                "task_name": run["task_name"],
                "version_id": str(run["version_id"]),
                "version_name": run["version_name"],
                "status": run["status"],
            }
            content = self._content(cur, scope, cases, executions, defects, None, run["model_snapshot_id"])
        return self._save("task_run", run_id, content)

    def for_version(self, version_id) -> dict:
        """Version report: the latest execution of every case in the version (T-11.5)."""
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM version WHERE id=%s", (version_id,))
            version = cur.fetchone()
            if version is None:
                raise AppError("NOT_FOUND", "Version not found")
            cur.execute(
                "SELECT DISTINCT c.id::text AS id, c.code, c.title FROM test_case c"
                " LEFT JOIN case_requirement_link l ON l.case_id=c.id"
                " LEFT JOIN requirement r ON r.id=l.requirement_id"
                " WHERE c.status <> 'deprecated'"
                " AND (r.version_id=%s OR c.origin_version_id=%s) ORDER BY c.code",
                (version_id, version_id),
            )
            cases = cur.fetchall()
            cur.execute(
                "SELECT DISTINCT ON (e.case_id) e.id::text AS id, e.case_id::text AS case_id,"
                " e.status, e.failed_assertion, e.error FROM case_execution e"
                " WHERE e.case_id = ANY(%s::uuid[]) AND e.status NOT IN ('queued','running')"
                " ORDER BY e.case_id, e.created_at DESC, e.id DESC",
                ([c["id"] for c in cases],),
            )
            order = {c["id"]: i for i, c in enumerate(cases)}
            executions = sorted(cur.fetchall(), key=lambda e: order[e["case_id"]])
            defects = scoped_defects(cur, version_id=version_id)
            cur.execute("SELECT id::text AS id FROM requirement WHERE version_id=%s", (version_id,))
            req_ids = [r["id"] for r in cur.fetchall()]
            scope = {
                "type": "version",
                "version_id": str(version_id),
                "version_name": version["name"],
                "version_status": version["status"],
            }
            content = self._content(cur, scope, cases, executions, defects, req_ids, version["model_snapshot_id"])
        return self._save("version", version_id, content)

    @staticmethod
    def _extra_cases(cur, case_ids) -> list[dict]:
        if not case_ids:
            return []
        cur.execute(
            "SELECT id::text AS id, code, title FROM test_case WHERE id = ANY(%s::uuid[])",
            (list(case_ids),),
        )
        return cur.fetchall()

    def _content(self, cur, scope, cases, executions, defects, req_ids, snapshot_id) -> dict:
        weights = load_weights(cur)
        case_ids = [c["id"] for c in cases]
        cur.execute(
            "SELECT l.case_id::text AS case_id, r.id::text AS rid, r.code"
            " FROM case_requirement_link l JOIN requirement r ON r.id=l.requirement_id"
            " WHERE l.case_id = ANY(%s::uuid[]) ORDER BY r.code",
            (case_ids,),
        )
        case_reqs: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            case_reqs.setdefault(row["case_id"], []).append(row)
        if req_ids is None:  # task run: the requirements its cases verify
            req_ids = sorted({r["rid"] for rows in case_reqs.values() for r in rows})
        reqs = requirement_rows(cur, req_ids)
        executed = executed_by_requirement(cur, executions)
        by_case = {c["id"]: c for c in cases}
        defects_by_execution: dict[str, list[str]] = {}
        for d in defects:
            if d["execution_id"]:
                defects_by_execution.setdefault(d["execution_id"], []).append(d["id"])
        failures = [
            {
                "case": by_case[e["case_id"]],
                "requirement_codes": [r["code"] for r in case_reqs.get(e["case_id"], [])],
                "status": e["status"],
                "failed_assertion": e["failed_assertion"],
                "error": e["error"],
                "execution_id": e["id"],
                "defect_ids": defects_by_execution.get(e["id"], []),
            }
            for e in executions
            if e["status"] in ("failed", "error")
        ]
        people = aggregate_people(cur, defects, weights)
        req_code = {
            r["id"]: r["code"] for r in requirement_rows(cur, {rid for d in defects for rid in d["requirement_ids"]})
        }
        cur.execute(
            "SELECT id::text AS id, name FROM person WHERE id = ANY(%s::uuid[])",
            (list({pid for d in defects for pid, _ in d["responsible"]}),),
        )
        names = {r["id"]: r["name"] for r in cur.fetchall()}
        return {
            "scope": scope,
            "summary": _summary([e["status"] for e in executions], len(cases)),
            "by_category": self._by_category(cur, cases, executions),
            "failures": failures,
            "by_requirement": aggregate_requirements(reqs, defects, executed, weights),
            "by_person": [
                {
                    **{
                        k: p[k]
                        for k in (
                            "person_id",
                            "name",
                            "attributed_count",
                            "attributed_score",
                            "attributed_by_role",
                            "related_count",
                        )
                    },
                    "top_requirements": [r["code"] for r in p["requirements"][:3]],
                }
                for p in people
            ],
            "defects": [
                {
                    "id": d["id"],
                    "code": d["code"],
                    "title": d["title"],
                    "severity": d["severity"],
                    "cause_category": d["cause_category"],
                    "status": d["status"],
                    "requirements": sorted(req_code.get(r, r) for r in d["requirement_ids"]),
                    "responsible": [{"name": names.get(pid, pid), "role": role} for pid, role in d["responsible"]],
                }
                for d in defects
            ],
            "code_links": self._code_links(cur, reqs),
            "executed_statuses": list(EXECUTED),
            "weights_used": weights,
            "snapshot_id": str(snapshot_id) if snapshot_id else None,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _by_category(cur, cases, executions) -> list[dict]:
        """Pass rate per case category (requirement / quality / regression)."""
        from testagent.services.task_binding import CATEGORIES, CATEGORY_LABEL

        cur.execute(
            "SELECT id::text AS id, category FROM test_case WHERE id = ANY(%s::uuid[])",
            ([c["id"] for c in cases],),
        )
        category = {r["id"]: r["category"] for r in cur.fetchall()}
        out = []
        for cat in CATEGORIES:
            ids = {c["id"] for c in cases if category.get(c["id"]) == cat}
            if not ids:
                continue
            statuses = [e["status"] for e in executions if e["case_id"] in ids]
            summary = _summary(statuses, len(ids))
            out.append({"category": cat, "label": CATEGORY_LABEL[cat], **summary})
        return out

    @staticmethod
    def _code_links(cur, reqs) -> list[dict]:
        out = []
        for r in reqs:
            cur.execute(
                "SELECT DISTINCT n.name, n.code_ref FROM requirement_node_link l"
                " JOIN model_node n ON n.id=l.node_id"
                " WHERE l.requirement_id=%s AND n.deleted_at IS NULL ORDER BY n.name",
                (r["id"],),
            )
            nodes = cur.fetchall()
            cur.execute(
                "SELECT DISTINCT a.method, a.path, a.code_ref FROM requirement_node_link l"
                " JOIN node_api_link na ON na.node_id=l.node_id AND na.invalid_at IS NULL"
                " JOIN api_endpoint a ON a.id=na.api_id"
                " WHERE l.requirement_id=%s ORDER BY a.path, a.method",
                (r["id"],),
            )
            out.append({"requirement_code": r["code"], "nodes": nodes, "apis": cur.fetchall()})
        return out

    def _ai_summary(self, content: dict) -> tuple[str | None, str | None]:
        if self.runtime is None:
            return None, None
        try:
            self.runtime.models.create()
        except AppError:
            return None, None  # no model: the report is still generated (T-11.4)
        brief = {k: content[k] for k in ("scope", "summary", "by_requirement", "by_person")}
        brief["failures"] = content["failures"][:30]
        brief["defects"] = content["defects"][:50]
        try:
            run = self.runtime.run("summarize_report", {"report": brief})
        except Exception:
            log.exception("summarize_report failed")
            return None, None
        if run["status"] != "succeeded":
            return None, str(run["id"])
        return SummaryOut.model_validate(run["result"]).summary, str(run["id"])

    def _save(self, scope_type: str, scope_id, content: dict) -> dict:
        summary, agent_run_id = self._ai_summary(content)
        with self.db.tx() as cur:
            cur.execute(
                "INSERT INTO report(scope_type, scope_id, content, ai_summary, weights_used,"
                " agent_run_id, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    scope_type,
                    scope_id,
                    Jsonb(content, dumps=_dumps),
                    summary,
                    Jsonb(content["weights_used"]),
                    agent_run_id,
                    self.actor,
                ),
            )
            row = cur.fetchone()
        self.bus.publish(
            "report.created",
            {"id": str(row["id"]), "scope_type": scope_type, "scope_id": str(scope_id)},
        )
        return row
