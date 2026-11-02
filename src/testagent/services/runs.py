"""Task runs (M1-09): serial execution on the Worker, cancel, progress over NOTIFY → SSE.

Rules (architecture §5.1, BR-06, C04, C11): only ready cases run, in seq order; an error does not
stop the run; non-functional cases are skipped; human cases are recorded blocked(awaiting_human)
without blocking later cases."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from psycopg.types.json import Jsonb

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services import environments as envs
from testagent.services.changelog import log_change
from testagent.services.executions import ExecutionService, is_api_case, select_executor
from testagent.services.state import transition

log = logging.getLogger("testagent.runs")
JOB_KIND = "task_run"
STARTABLE = {"ready", "done", "cancelled"}
TERMINAL = {"passed", "failed", "error", "cancelled"}
FORCED_REASON = {
    "skipped": (
        "Non-functional cases (performance, security, …) are not executed in this version "
        "and are marked skipped (never counted as passed)"
    ),
    "blocked": "awaiting_human",
    "error": "A case in the automated task has no automation code yet (code_path)",
}
COUNT_KEYS = ("passed", "failed", "error", "blocked", "skipped")


def run_channel(db, run_id) -> str:
    """NOTIFY channel for one run; namespaced by schema so parallel test schemas never mix."""
    hexid = str(run_id).replace("-", "")
    return f"ta_run_{hexid}" + (f"_{db.schema}" if db.schema else "")


def _counts(executions: list[dict], total: int | None) -> dict:
    counts = {k: 0 for k in COUNT_KEYS}
    for e in executions:
        if e["status"] in counts:
            counts[e["status"]] += 1
    done = sum(counts.values())
    return {"total": total if total is not None else done, "done": done, **counts}


class RunService:
    def __init__(
        self,
        db,
        bus: EventBus,
        *,
        executions: Callable[[], ExecutionService] | None = None,
        actor: str = "local-user",
    ):
        self.db = db
        self.bus = bus
        self.executions = executions
        self.actor = actor

    # ------------------------------------------------------------ helpers
    def _notify(self, cur, run_id, payload: dict) -> None:
        cur.execute(
            "SELECT pg_notify(%s, %s)",
            (run_channel(self.db, run_id), json.dumps(payload, ensure_ascii=False, default=str)),
        )

    def notify(self, run_id, payload: dict) -> None:
        with self.db.tx() as cur:
            self._notify(cur, run_id, payload)

    @staticmethod
    def _run(cur, run_id, lock=False) -> dict:
        cur.execute(
            "SELECT r.*, t.name AS task_name, t.version_id, v.sut_id FROM task_run r"
            " JOIN test_task t ON t.id=r.task_id JOIN version v ON v.id=t.version_id"
            " WHERE r.id=%s" + (" FOR UPDATE OF r" if lock else ""),
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Run not found")
        return row

    @staticmethod
    def _set_task_status(cur, task_id, target: str) -> None:
        cur.execute("SELECT status FROM test_task WHERE id=%s FOR UPDATE", (task_id,))
        current = cur.fetchone()["status"]
        if current == target:
            return
        if current in ("done", "cancelled") and target == "running":
            transition("task", current, "ready")
            current = "ready"
        transition("task", current, target)
        cur.execute("UPDATE test_task SET status=%s WHERE id=%s", (target, task_id))

    # ------------------------------------------------------------ start / cancel
    def start(self, task_id, trigger: str = "manual", *, cur=None) -> dict:
        if cur is None:
            with self.db.tx() as c:
                run = self.start(task_id, trigger, cur=c)
            self.bus.publish("task_run.queued", {"id": str(run["id"]), "task_id": str(task_id)})
            return self.get(run["id"])
        cur.execute("SELECT * FROM test_task WHERE id=%s FOR UPDATE", (task_id,))
        task = cur.fetchone()
        if task is None:
            raise AppError("NOT_FOUND", "Task not found")
        cur.execute(
            "SELECT id FROM task_run WHERE task_id=%s AND status IN ('queued','running')",
            (task_id,),
        )
        active = cur.fetchone()
        if active:
            raise AppError("RUN_ACTIVE", "This task already has a queued or running run", related=[str(active["id"])])
        if task["status"] not in STARTABLE:
            raise AppError("CONFLICT", f"The task is currently {task['status']}; set it ready first")
        if task["executor"] != "human" and task["environment_id"] is None:
            raise AppError(
                "VALIDATION", "The task has no execution environment", field_errors=[{"field": "environment_id"}]
            )
        if task["executor"] != "human" and trigger == "manual":
            cur.execute("SELECT * FROM environment WHERE id=%s", (task["environment_id"],))
            env = cur.fetchone()
            if env is not None:
                envs.require_reachable(env)  # fail fast; scheduled runs check in execute()
        cur.execute(
            "INSERT INTO task_run(task_id, trigger, environment_id, executor, requested_by)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (task_id, trigger, task["environment_id"], task["executor"], self.actor),
        )
        run = cur.fetchone()
        cur.execute(
            "INSERT INTO jobs(kind, payload) VALUES (%s, %s) RETURNING id",
            (JOB_KIND, Jsonb({"run_id": str(run["id"])})),
        )
        job_id = cur.fetchone()["id"]
        cur.execute("UPDATE task_run SET job_id=%s WHERE id=%s", (job_id, run["id"]))
        suffix = f"_{self.db.schema}" if self.db.schema else ""
        cur.execute("SELECT pg_notify(%s, %s)", (f"testagent_jobs{suffix}", str(job_id)))
        self._set_task_status(cur, task_id, "running")
        log_change(cur, "task_run", run["id"], "start", self.actor, {"trigger": trigger})
        return run

    def cancel(self, run_id) -> dict:
        with self.db.tx() as cur:
            run = self._run(cur, run_id, lock=True)
            if run["status"] == "queued":
                cur.execute(
                    "UPDATE task_run SET status='cancelled', cancel_requested=true, ended_at=now() WHERE id=%s",
                    (run_id,),
                )
                cur.execute(
                    "UPDATE jobs SET status='cancelled', ended_at=now() WHERE id=%s AND status='queued'",
                    (run["job_id"],),
                )
                self._set_task_status(cur, run["task_id"], "cancelled")
                self._notify(cur, run_id, {"type": "run", "status": "cancelled"})
            elif run["status"] == "running":
                cur.execute("UPDATE task_run SET cancel_requested=true WHERE id=%s", (run_id,))
                self._notify(cur, run_id, {"type": "cancel_requested"})
            else:
                raise AppError("CONFLICT", "The run has already finished")
            log_change(cur, "task_run", run_id, "cancel", self.actor)
        if run["status"] == "queued":
            self.bus.publish("task_run.cancelled", {"id": str(run_id)})
        return self.get(run_id)

    # ------------------------------------------------------------ reads
    def get(self, run_id) -> dict:
        with self.db.tx() as cur:
            run = self._run(cur, run_id)
            cur.execute(
                "SELECT e.id, e.task_run_id, e.case_id, e.executor, e.status, e.failed_assertion,"
                " e.error, e.blocked_reason, e.duration_ms, e.executed_by, e.created_at,"
                " e.ended_at, c.code AS case_code, c.title AS case_title"
                " FROM case_execution e JOIN test_case c ON c.id=e.case_id"
                " WHERE e.task_run_id=%s ORDER BY e.created_at, e.id",
                (run_id,),
            )
            run["executions"] = cur.fetchall()
            cur.execute(
                "SELECT c.id::text AS id, c.code, c.title, c.status FROM task_case tc"
                " JOIN test_case c ON c.id=tc.case_id"
                " WHERE tc.task_id=%s AND c.status <> 'ready' ORDER BY tc.seq",
                (run["task_id"],),
            )
            run["not_ready"] = cur.fetchall()
            cur.execute(
                "SELECT id FROM report WHERE scope_type='task_run' AND scope_id=%s ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            )
            report = cur.fetchone()
        run["report_id"] = report["id"] if report else None
        run["counts"] = _counts(run["executions"], run["total_cases"])
        return run

    def list_recent(self, version_id=None, limit: int = 50) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT r.*, t.name AS task_name, t.version_id, v.name AS version_name,"
                " s.code AS sut_code, (SELECT jsonb_agg(e.status) FROM case_execution e"
                "  WHERE e.task_run_id=r.id) AS statuses"
                " FROM task_run r JOIN test_task t ON t.id=r.task_id"
                " JOIN version v ON v.id=t.version_id JOIN sut s ON s.id=v.sut_id"
                " WHERE (%s::uuid IS NULL OR t.version_id=%s::uuid)"
                " ORDER BY r.created_at DESC LIMIT %s",
                (version_id, version_id, limit),
            )
            rows = cur.fetchall()
        for row in rows:
            statuses = row.pop("statuses") or []
            row["counts"] = _counts([{"status": s} for s in statuses], row["total_cases"])
        return rows

    def list_for_task(self, task_id) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute("SELECT 1 FROM test_task WHERE id=%s", (task_id,))
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "Task not found")
            cur.execute(
                "SELECT r.*, (SELECT jsonb_agg(e.status) FROM case_execution e"
                "  WHERE e.task_run_id=r.id) AS statuses"
                " FROM task_run r WHERE r.task_id=%s ORDER BY r.created_at DESC LIMIT 100",
                (task_id,),
            )
            rows = cur.fetchall()
        for row in rows:
            statuses = row.pop("statuses") or []
            row["counts"] = _counts([{"status": s} for s in statuses], row["total_cases"])
        return rows

    # ------------------------------------------------------------ worker side
    def execute(self, payload: dict) -> None:
        run_id = payload["run_id"]
        with self.db.tx() as cur:
            run = self._run(cur, run_id, lock=True)
            if run["status"] != "queued":
                return  # cancelled while queued
            cur.execute(
                "SELECT c.*, s.code AS sut_code FROM task_case tc"
                " JOIN test_case c ON c.id=tc.case_id JOIN sut s ON s.id=c.sut_id"
                " WHERE tc.task_id=%s AND c.status='ready' ORDER BY tc.seq",
                (run["task_id"],),
            )
            cases = cur.fetchall()
            env = None
            if run["environment_id"] is not None:
                cur.execute("SELECT * FROM environment WHERE id=%s", (run["environment_id"],))
                env = cur.fetchone()
            cur.execute(
                "UPDATE task_run SET status='running', started_at=now(), total_cases=%s WHERE id=%s",
                (len(cases), run_id),
            )
            first_run = self._enter_testing(cur, run["version_id"])
            self._notify(cur, run_id, {"type": "run", "status": "running", "total": len(cases)})
        if first_run:
            self.bus.publish("version.testing", {"id": str(run["version_id"])})
        if env is not None and run["executor"] != "human" and not envs.probe(env["base_url"])[0]:
            self._finish(run, "error", "ENV_UNREACHABLE: " + envs.unreachable_message(env))
            return
        status = "error"
        try:
            status = self._loop(run, cases, env)
        except Exception as exc:
            log.exception("task run %s crashed", run_id)
            self._finish(run, "error", f"{type(exc).__name__}: {exc}"[:2000])
            raise
        self._finish(run, status)

    def _enter_testing(self, cur, version_id) -> bool:
        """T-09.5: the first run of a frozen version moves it to testing."""
        cur.execute("SELECT status FROM version WHERE id=%s FOR UPDATE", (version_id,))
        if cur.fetchone()["status"] != "requirements_frozen":
            return False
        transition("version", "requirements_frozen", "testing")
        cur.execute("UPDATE version SET status='testing' WHERE id=%s", (version_id,))
        log_change(cur, "version", version_id, "status", "system", {"status": "testing"})
        return True

    def _cancel_requested(self, run_id) -> bool:
        with self.db.tx() as cur:
            cur.execute("SELECT cancel_requested FROM task_run WHERE id=%s", (run_id,))
            return bool(cur.fetchone()["cancel_requested"])

    def _loop(self, run: dict, cases: list[dict], env: dict | None) -> str:
        svc = self.executions()
        results: list[str] = []
        for index, case in enumerate(cases, start=1):
            if self._cancel_requested(run["id"]):
                return "cancelled"
            executor, forced = select_executor(
                case["mode"],
                case["code_path"],
                case["type_tag"],
                run["executor"],
                is_api_case(case),
            )
            env_id = env["id"] if env else None
            if forced:
                ex = svc.record_forced(
                    case,
                    env_id,
                    executor,
                    forced,
                    task_run_id=run["id"],
                    reason=FORCED_REASON[forced],
                )
            elif env is None:
                ex = svc.record_forced(
                    case,
                    None,
                    executor,
                    "error",
                    task_run_id=run["id"],
                    reason="NO_ENVIRONMENT: the task has no execution environment",
                )
            else:
                ex = svc.execute_case(case, env, executor, task_run_id=run["id"])
            results.append(ex["status"])
            log.info(
                "Run %s: case %d/%d “%s (%s)” → %s (%s)",
                str(run["id"])[:8],
                index,
                len(cases),
                case["title"],
                case["code"],
                ex["status"],
                executor,
            )
            self.notify(
                run["id"],
                {
                    "type": "case",
                    "index": index,
                    "total": len(cases),
                    "execution_id": str(ex["id"]),
                    "case_id": str(case["id"]),
                    "case_code": case["code"],
                    "status": ex["status"],
                },
            )
        return "failed" if any(s in ("failed", "error") for s in results) else "passed"

    def _finish(self, run: dict, status: str, error: str | None = None) -> None:
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE task_run SET status=%s, error=%s, ended_at=now() WHERE id=%s",
                (status, error, run["id"]),
            )
            task_target = {"cancelled": "cancelled", "error": "ready"}.get(status, "done")
            self._set_task_status(cur, run["task_id"], task_target)
            self._notify(cur, run["id"], {"type": "run", "status": status})
        self.bus.publish(
            "task_run.finished",
            {
                "id": str(run["id"]),
                "status": status,
                "task_id": str(run["task_id"]),
                "version_id": str(run["version_id"]),
            },
        )
