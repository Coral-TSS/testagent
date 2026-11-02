"""Defects (M1-10): CRUD + state machine, requirement ownership inferred from the case, and
responsibility attribution by cause category (BR-07). Only people decide the final cause (C01)."""

from __future__ import annotations

from typing import Any

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.attribution import AttributionRules
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human
from testagent.services.state import transition

FIELDS = ("title", "description", "severity", "analysis")
FAILED = ("failed", "error")


class DefectService:
    def __init__(self, db, bus: EventBus, actor: str = "local-user", rules=None):
        self.db = db
        self.bus = bus
        self.actor = actor
        self.rules = rules or AttributionRules()

    @property
    def is_agent(self) -> bool:
        return self.actor == "agent" or self.actor.startswith("agent:")

    # ------------------------------------------------------------ lookups
    @staticmethod
    def _defect(cur, defect_id, lock=False) -> dict:
        cur.execute("SELECT * FROM defect WHERE id=%s" + (" FOR UPDATE" if lock else ""), (defect_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Defect not found")
        return row

    @staticmethod
    def _check_requirements(cur, requirement_ids: list, sut_id) -> list[str]:
        ids = list(dict.fromkeys(str(r) for r in requirement_ids))
        if not ids:
            return []
        cur.execute(
            "SELECT r.id::text AS id, v.sut_id FROM requirement r JOIN version v"
            " ON v.id=r.version_id WHERE r.id = ANY(%s::uuid[])",
            (ids,),
        )
        found = {r["id"]: r for r in cur.fetchall()}
        missing = [i for i in ids if i not in found]
        if missing:
            raise AppError("NOT_FOUND", "Requirement not found", related=missing)
        if any(str(r["sut_id"]) != str(sut_id) for r in found.values()):
            raise AppError("VALIDATION", "The requirement does not belong to this SUT")
        return ids

    def _detail(self, cur, defect_id) -> dict:
        d = self._defect(cur, defect_id)
        cur.execute(
            "SELECT r.id, r.code, r.title, r.version_id, dr.inferred FROM defect_requirement dr"
            " JOIN requirement r ON r.id=dr.requirement_id WHERE dr.defect_id=%s ORDER BY r.code",
            (defect_id,),
        )
        d["requirements"] = cur.fetchall()
        cur.execute(
            "SELECT p.id AS person_id, p.name AS person_name, dr.role, dr.inferred"
            " FROM defect_responsible dr JOIN person p ON p.id=dr.person_id"
            " WHERE dr.defect_id=%s ORDER BY dr.role, p.name",
            (defect_id,),
        )
        d["responsible"] = cur.fetchall()
        cur.execute(
            "SELECT l.target_type, l.target_id,"
            " CASE l.target_type WHEN 'node' THEN n.name"
            "  ELSE a.method || ' ' || a.path END AS name,"
            " CASE l.target_type WHEN 'node' THEN n.code_ref ELSE a.code_ref END AS code_ref"
            " FROM defect_link l"
            " LEFT JOIN model_node n ON l.target_type='node' AND n.id=l.target_id"
            " LEFT JOIN api_endpoint a ON l.target_type='api' AND a.id=l.target_id"
            " WHERE l.defect_id=%s ORDER BY l.target_type DESC, name",
            (defect_id,),
        )
        d["links"] = cur.fetchall()
        d["case"] = None
        if d["case_id"]:
            cur.execute("SELECT id, code, title FROM test_case WHERE id=%s", (d["case_id"],))
            d["case"] = cur.fetchone()
        d["execution"] = None
        if d["execution_id"]:
            cur.execute(
                "SELECT id, status, executor, failed_assertion, task_run_id, created_at"
                " FROM case_execution WHERE id=%s",
                (d["execution_id"],),
            )
            d["execution"] = cur.fetchone()
        return d

    def get(self, defect_id) -> dict:
        with self.db.tx() as cur:
            return self._detail(cur, defect_id)

    def list(self, filters: dict[str, Any] | None = None) -> list[dict]:
        f = {k: v for k, v in (filters or {}).items() if v not in (None, "")}
        where, args = ["true"], []
        for key in ("sut_id", "version_id", "status", "severity", "cause_category", "case_id"):
            if key in f:
                where.append(f"d.{key}=%s")
                args.append(f[key])
        if "execution_id" in f:
            where.append("d.execution_id=%s")
            args.append(f["execution_id"])
        if "requirement_id" in f:
            where.append("EXISTS (SELECT 1 FROM defect_requirement x WHERE x.defect_id=d.id AND x.requirement_id=%s)")
            args.append(f["requirement_id"])
        if "person_id" in f:
            where.append("EXISTS (SELECT 1 FROM defect_responsible x WHERE x.defect_id=d.id AND x.person_id=%s)")
            args.append(f["person_id"])
        if "created_by" in f:
            where.append("d.created_by=%s")
            args.append(f["created_by"])
        if "q" in f:
            where.append("(d.title ILIKE %s OR d.code ILIKE %s OR d.description ILIKE %s)")
            args += [f"%{f['q']}%"] * 3
        with self.db.tx() as cur:
            cur.execute(
                "SELECT d.id, d.code, d.sut_id, d.version_id, d.title, d.severity, d.status,"
                " d.cause_category, d.suggested_cause, d.created_by, d.case_id, d.execution_id,"
                " d.created_at, d.updated_at,"
                " COALESCE((SELECT jsonb_agg(r.code ORDER BY r.code) FROM defect_requirement x"
                "  JOIN requirement r ON r.id=x.requirement_id WHERE x.defect_id=d.id),"
                "  '[]'::jsonb) AS requirement_codes,"
                " COALESCE((SELECT jsonb_agg(DISTINCT p.name) FROM defect_responsible x"
                "  JOIN person p ON p.id=x.person_id WHERE x.defect_id=d.id),"
                "  '[]'::jsonb) AS responsible_names"
                f" FROM defect d WHERE {' AND '.join(where)}"
                " ORDER BY d.created_at DESC, d.code DESC LIMIT 500",
                args,
            )
            return cur.fetchall()

    def for_execution(self, execution_id) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT id, code, title, status, severity FROM defect WHERE execution_id=%s ORDER BY created_at",
                (execution_id,),
            )
            return cur.fetchall()

    # ------------------------------------------------------------ create
    def _next_code(self, cur, sut_id) -> str:
        cur.execute("SELECT id FROM sut WHERE id=%s FOR UPDATE", (sut_id,))
        if cur.fetchone() is None:
            raise AppError("NOT_FOUND", "SUT not found")
        cur.execute(
            "SELECT max(substring(code FROM 5)::int) AS n FROM defect WHERE sut_id=%s AND code ~ '^DEF-[0-9]+$'",
            (sut_id,),
        )
        return f"DEF-{(cur.fetchone()['n'] or 0) + 1:03d}"

    def create(self, data: dict[str, Any], *, cur=None, agent_run_id=None) -> dict:
        if cur is None:
            with self.db.tx() as c:
                row = self.create(data, cur=c, agent_run_id=agent_run_id)
            self.bus.publish("defect.created", {"id": str(row["id"])})
            return row
        cause = data.get("cause_category") or "unknown"
        if cause != "unknown" and self.is_agent:
            raise AppError("VALIDATION", "The agent can only suggest a cause category, not set it (C01)")
        sut_id = data["sut_id"]
        version_id = data.get("version_id")
        if version_id is not None:
            cur.execute("SELECT sut_id FROM version WHERE id=%s", (version_id,))
            v = cur.fetchone()
            if v is None or str(v["sut_id"]) != str(sut_id):
                raise AppError("VALIDATION", "The version does not belong to this SUT")
        inferred_reqs = data.get("requirement_ids") is None
        req_ids = self._check_requirements(
            cur,
            data.get("inferred_requirement_ids", []) if inferred_reqs else data["requirement_ids"],
            sut_id,
        )
        cur.execute(
            "INSERT INTO defect(sut_id, version_id, execution_id, case_id, code, title,"
            " description, severity, cause_category, suggested_cause, created_by,"
            " created_by_actor, analysis, agent_run_id)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                sut_id,
                version_id,
                data.get("execution_id"),
                data.get("case_id"),
                self._next_code(cur, sut_id),
                data["title"],
                data.get("description"),
                data.get("severity") or "major",
                cause,
                data.get("suggested_cause"),
                "agent" if self.is_agent else "human",
                self.actor,
                data.get("analysis"),
                agent_run_id,
            ),
        )
        defect_id = cur.fetchone()["id"]
        for rid in req_ids:
            cur.execute(
                "INSERT INTO defect_requirement(defect_id, requirement_id, inferred) VALUES (%s,%s,%s)",
                (defect_id, rid, inferred_reqs),
            )
        for link in data.get("links") or []:
            cur.execute(
                "INSERT INTO defect_link(defect_id, target_type, target_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (defect_id, link["target_type"], link["target_id"]),
            )
        self._infer(cur, defect_id)
        log_change(cur, "defect", defect_id, "create", self.actor, {"title": data["title"]})
        return self._detail(cur, defect_id)

    def create_from_execution(self, execution_id, data: dict[str, Any], *, agent_run_id=None):
        with self.db.tx() as cur:
            cur.execute(
                "SELECT e.*, c.sut_id, c.code AS case_code, c.title AS case_title,"
                " c.origin_version_id, t.version_id AS run_version_id FROM case_execution e"
                " JOIN test_case c ON c.id=e.case_id"
                " LEFT JOIN task_run r ON r.id=e.task_run_id"
                " LEFT JOIN test_task t ON t.id=r.task_id WHERE e.id=%s",
                (execution_id,),
            )
            ex = cur.fetchone()
            if ex is None:
                raise AppError("NOT_FOUND", "Execution not found")
            if ex["status"] not in FAILED:
                raise AppError("CONFLICT", "Defects can only be created from failed or errored executions")
            cur.execute(
                "SELECT r.id::text AS id, r.version_id FROM case_requirement_link l"
                " JOIN requirement r ON r.id=l.requirement_id WHERE l.case_id=%s ORDER BY r.code",
                (ex["case_id"],),
            )
            reqs = cur.fetchall()
            cur.execute(
                "SELECT 'node' AS target_type, l.node_id AS target_id FROM case_node_link l"
                " WHERE l.case_id=%s UNION"
                " SELECT 'api', na.api_id FROM case_node_link l"
                " JOIN node_api_link na ON na.node_id=l.node_id WHERE l.case_id=%s",
                (ex["case_id"], ex["case_id"]),
            )
            links = cur.fetchall()
            version_id = (
                data.get("version_id")
                or ex["run_version_id"]
                or ex["origin_version_id"]
                or (reqs[0]["version_id"] if reqs else None)
            )
            reason = ex["failed_assertion"] or ex["error"] or "Execution failed"
            body = {
                "sut_id": ex["sut_id"],
                "version_id": version_id,
                "execution_id": execution_id,
                "case_id": ex["case_id"],
                "title": data.get("title") or f"[{ex['case_code']}] {reason}"[:300],
                "description": data.get("description")
                or f"Case {ex['case_code']} {ex['case_title']} Execution failed: {reason}",
                "severity": data.get("severity"),
                "cause_category": data.get("cause_category"),
                "suggested_cause": data.get("suggested_cause"),
                "analysis": data.get("analysis"),
                "links": links,
                "requirement_ids": data.get("requirement_ids"),
                "inferred_requirement_ids": [r["id"] for r in reqs],
            }
            row = self.create(body, cur=cur, agent_run_id=agent_run_id)
        self.bus.publish("defect.created", {"id": str(row["id"])})
        return row

    # ------------------------------------------------------------ edits
    def update(self, defect_id, data: dict[str, Any]) -> dict:
        with self.db.tx() as cur:
            d = self._defect(cur, defect_id, lock=True)
            values = {k: v for k, v in data.items() if k in FIELDS}
            cause_changed = "cause_category" in data and data["cause_category"] != d["cause_category"]
            if "cause_category" in data:
                ensure_human(self.actor, "Confirm defect cause category")
                values["cause_category"] = data["cause_category"] or "unknown"
            if values:
                sets = ", ".join(f"{k}=%s" for k in values)
                cur.execute(f"UPDATE defect SET {sets} WHERE id=%s", (*values.values(), defect_id))
            if cause_changed and not d["responsible_manual"]:
                self._infer(cur, defect_id)
            log_change(cur, "defect", defect_id, "update", self.actor, data)
            row = self._detail(cur, defect_id)
        self.bus.publish("defect.updated", {"id": str(defect_id)})
        return row

    def accept_suggestion(self, defect_id) -> dict:
        d = self.get(defect_id)
        if not d["suggested_cause"]:
            raise AppError("VALIDATION", "This defect has no agent-suggested cause category")
        return self.update(defect_id, {"cause_category": d["suggested_cause"]})

    def set_status(self, defect_id, target: str) -> dict:
        with self.db.tx() as cur:
            d = self._defect(cur, defect_id, lock=True)
            transition("defect", d["status"], target)
            resolved = "now()" if target in ("resolved", "closed") else "NULL"
            if target == "closed" and d["resolved_at"]:
                resolved = "resolved_at"
            cur.execute(
                f"UPDATE defect SET status=%s, resolved_at={resolved} WHERE id=%s",
                (target, defect_id),
            )
            log_change(cur, "defect", defect_id, "status", self.actor, {"status": target})
            row = self._detail(cur, defect_id)
        self.bus.publish(f"defect.{target}", {"id": str(defect_id)})
        return row

    def set_requirements(self, defect_id, requirement_ids: list) -> dict:
        """Edited by a person: rows become inferred=false; inferred attribution is recomputed."""
        with self.db.tx() as cur:
            d = self._defect(cur, defect_id, lock=True)
            ids = self._check_requirements(cur, requirement_ids, d["sut_id"])
            cur.execute("DELETE FROM defect_requirement WHERE defect_id=%s", (defect_id,))
            for rid in ids:
                cur.execute(
                    "INSERT INTO defect_requirement(defect_id, requirement_id, inferred) VALUES (%s,%s,false)",
                    (defect_id, rid),
                )
            if not d["responsible_manual"]:
                self._infer(cur, defect_id)
            log_change(cur, "defect", defect_id, "requirements", self.actor, {"ids": ids})
            row = self._detail(cur, defect_id)
        self.bus.publish("defect.updated", {"id": str(defect_id)})
        return row

    def set_responsible(self, defect_id, entries: list[dict]) -> dict:
        """Manual attribution (inferred=false); automatic re-inference no longer touches it."""
        ensure_human(self.actor, "Change defect attribution")
        with self.db.tx() as cur:
            self._defect(cur, defect_id, lock=True)
            pairs = list(dict.fromkeys((str(e["person_id"]), e["role"]) for e in entries))
            if pairs:
                cur.execute(
                    "SELECT id::text AS id FROM person WHERE id = ANY(%s::uuid[])",
                    ([p for p, _ in pairs],),
                )
                found = {r["id"] for r in cur.fetchall()}
                missing = sorted({p for p, _ in pairs} - found)
                if missing:
                    raise AppError("NOT_FOUND", "Person not found", related=missing)
            cur.execute("DELETE FROM defect_responsible WHERE defect_id=%s", (defect_id,))
            for person_id, role in pairs:
                cur.execute(
                    "INSERT INTO defect_responsible(defect_id, person_id, role, inferred) VALUES (%s,%s,%s,false)",
                    (defect_id, person_id, role),
                )
            cur.execute("UPDATE defect SET responsible_manual=true WHERE id=%s", (defect_id,))
            log_change(cur, "defect", defect_id, "responsible", self.actor, {"entries": pairs})
            row = self._detail(cur, defect_id)
        self.bus.publish("defect.updated", {"id": str(defect_id)})
        return row

    def infer_responsible(self, defect_id) -> dict:
        """Explicit “infer from requirement”: recompute inferred rows; manual rows stay."""
        with self.db.tx() as cur:
            self._defect(cur, defect_id, lock=True)
            self._infer(cur, defect_id)
            log_change(cur, "defect", defect_id, "infer_responsible", self.actor)
            row = self._detail(cur, defect_id)
        self.bus.publish("defect.updated", {"id": str(defect_id)})
        return row

    def _infer(self, cur, defect_id) -> None:
        cur.execute("SELECT cause_category FROM defect WHERE id=%s", (defect_id,))
        role = self.rules.role_for(cur.fetchone()["cause_category"])
        cur.execute("DELETE FROM defect_responsible WHERE defect_id=%s AND inferred", (defect_id,))
        if role is None:
            return
        cur.execute(
            "INSERT INTO defect_responsible(defect_id, person_id, role, inferred)"
            " SELECT DISTINCT %s::uuid, rp.person_id, rp.role, true"
            " FROM defect_requirement dr"
            " JOIN requirement_person rp ON rp.requirement_id=dr.requirement_id"
            " JOIN person p ON p.id=rp.person_id AND p.active"
            " WHERE dr.defect_id=%s AND rp.role=%s"
            " ON CONFLICT (defect_id, person_id, role) DO NOTHING",
            (defect_id, defect_id, role),
        )
