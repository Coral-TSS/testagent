"""Executors (M1-08): selection matrix, agent_browser, pytest, manual and single-case debug.

A debug execution has task_run_id = NULL (architecture §5.4); task runs reuse `execute_case`."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from testagent.agent.runtime import AgentRuntime, Entry
from testagent.core.actor import current_actor
from testagent.core.artifacts import ArtifactStore
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.integrations.browser import BROWSER_TOOLS, BrowserSession
from testagent.integrations.git_repo import TestRepo
from testagent.integrations.pytest_runner import run_pytest
from testagent.services import environments as envs
from testagent.services.changelog import log_change
from testagent.services.failure_classify import classify
from testagent.services.guards import ensure_human
from testagent.services.state import transition

FUNCTIONAL = "functional"
Executor = Literal["agent_browser", "agent_api", "pytest", "manual"]
API_TYPES = ("api",)
# Types this platform does not execute in M1 (spec §2.2). Everything else — functional, api,
# boundary, exception, regression, smoke, validation, idempotency … — is functional testing
# and runs. ("boundary" used to be skipped as if it were non-functional.)
NON_FUNCTIONAL_TYPES = frozenset(
    {
        "performance",
        "load",
        "stress",
        "security",
        "reliability",
        "usability",
        "compatibility",
        "accessibility",
    }
)


def is_api_case(case: dict) -> bool:
    """API-type case: type tag `api`, or its steps call endpoints as "METHOD /path" (5d)."""
    from testagent.agent.tools import API_REF

    if case.get("type_tag") in API_TYPES:
        return True
    steps = case.get("steps") or []
    hits = sum(1 for st in steps if API_REF.search(st.get("action") or "") or API_REF.search(st.get("data") or ""))
    return bool(steps) and hits * 2 >= len(steps)


def select_executor(
    mode: str, code_path: str | None, type_tag: str, task_executor: str, api: bool = False
) -> tuple[Executor, str | None]:
    """(executor, forced status). Spec §5.1: automated+code → pytest; manual+agent →
    agent_browser (agent_api for API-type cases); manual+human → blocked(awaiting_human);
    non-functional types (performance, security …) → skipped."""
    automated = mode == "automated" and bool(code_path)
    if type_tag in NON_FUNCTIONAL_TYPES:
        return ("pytest" if automated else "manual"), "skipped"
    if automated:
        return "pytest", None
    if task_executor == "agent":
        return ("agent_api" if api or type_tag in API_TYPES else "agent_browser"), None
    if task_executor == "human":
        return "manual", "blocked"
    # automation task but the case has no script yet: not executed, never counted as an error (#18)
    return "manual", "no_script"


# ---------------------------------------------------------------- execute_case_browser entry
class BrowserRunOut(BaseModel):
    claimed_status: Literal["passed", "failed"] = Field(
        description="your opinion only; the platform decides from browser_assert receipts"
    )
    summary: str = Field(min_length=1, max_length=4000)


def browser_entry() -> Entry:
    return Entry(
        name="execute_case_browser",
        output_schema=BrowserRunOut,
        tools=BROWSER_TOOLS,
        instructions=(
            "Execute the manual test case in the browser step by step with the browser_* tools, "
            "using the given test data. Verify EVERY expected result with browser_assert; only "
            "assertion receipts count, your own claim does not. Do not try to work around "
            "failures. Finish with submit_result."
        ),
    )


class ApiRunOut(BaseModel):
    claimed_status: Literal["passed", "failed"] = Field(
        description="your opinion only; the platform decides from api_assert receipts"
    )
    summary: str = Field(min_length=1, max_length=4000)


def api_entry() -> Entry:
    from testagent.integrations.http_api import API_TOOLS

    return Entry(
        name="execute_case_api",
        output_schema=ApiRunOut,
        tools=API_TOOLS,
        instructions=(
            "Execute the API test case step by step with api_request, using the given test data. "
            "Request bodies MUST follow the registered schema (get_api_schema); never invent "
            "fields. Use values from earlier responses (e.g. created ids) in later paths. Verify "
            "EVERY expected result with api_assert (status code and the relevant response "
            "fields); only assertion receipts count. Do not work around failures. Finish with "
            "submit_result."
        ),
    )


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


class ExecutionService:
    def __init__(
        self,
        db,
        bus: EventBus,
        *,
        runtime: AgentRuntime | None = None,
        artifacts: ArtifactStore | None = None,
        repos_root: Path | None = None,
        headless: bool = True,
        pytest_timeout_s: float = 300,
        actor: str | None = None,
        runners: dict | None = None,
    ):
        self.db = db
        self.bus = bus
        self.runtime = runtime
        self.artifacts = artifacts
        self.repos_root = repos_root
        self.headless = headless
        self.pytest_timeout_s = pytest_timeout_s
        self.actor = actor or current_actor()
        # EP-03: executor overrides, `runner(case, env, execution_id) -> fields`; tests use fakes
        self.runners = runners or {}

    # ------------------------------------------------------------ lookups
    @staticmethod
    def _case(cur, case_id) -> dict:
        cur.execute(
            "SELECT c.*, s.code AS sut_code FROM test_case c JOIN sut s ON s.id=c.sut_id WHERE c.id=%s",
            (case_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Test case not found")
        return row

    @staticmethod
    def _environment(cur, env_id, sut_id) -> dict:
        if env_id is None:
            raise AppError("VALIDATION", "Choose an execution environment", field_errors=[{"field": "environment_id"}])
        cur.execute("SELECT * FROM environment WHERE id=%s AND sut_id=%s", (env_id, sut_id))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "The execution environment does not exist or belongs to another SUT")
        return row

    def repo_for(self, sut_code: str, sut_id) -> TestRepo:
        if self.repos_root is None:
            raise AppError("CONFIG_MISSING", "Test repo directory is not configured")
        return TestRepo(self.repos_root, sut_code, str(sut_id))

    def get(self, execution_id) -> dict:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT e.*, c.code AS case_code, c.title AS case_title, c.sut_id,"
                " env.name AS environment_name, env.base_url FROM case_execution e"
                " JOIN test_case c ON c.id=e.case_id"
                " LEFT JOIN environment env ON env.id=e.environment_id WHERE e.id=%s",
                (execution_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Execution not found")
        return row

    def list_for_case(self, case_id) -> list[dict]:
        with self.db.tx() as cur:
            self._case(cur, case_id)
            cur.execute(
                "SELECT e.id, e.task_run_id, e.executor, e.status, e.failed_assertion, e.error,"
                " e.duration_ms, e.executed_by, e.created_at, e.ended_at,"
                " e.failure_kind, e.suspected_cause, e.summary,"
                " env.name AS environment_name"
                " FROM case_execution e LEFT JOIN environment env ON env.id=e.environment_id"
                " WHERE e.case_id=%s ORDER BY e.created_at DESC LIMIT 100",
                (case_id,),
            )
            return cur.fetchall()

    # ------------------------------------------------------------ bookkeeping
    def _create(self, cur, case: dict, executor: str, env_id, task_run_id=None) -> dict:
        cur.execute(
            "INSERT INTO case_execution(task_run_id, case_id, executor, environment_id, test_data,"
            " executed_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                task_run_id,
                case["id"],
                executor,
                env_id,
                Jsonb(case["test_data"], dumps=_dumps) if case["test_data"] is not None else None,
                self.actor,
            ),
        )
        return cur.fetchone()

    def _set_status(self, execution_id, target: str, **fields) -> None:
        with self.db.tx() as cur:
            cur.execute("SELECT status FROM case_execution WHERE id=%s FOR UPDATE", (execution_id,))
            transition("case_execution", cur.fetchone()["status"], target)
            sets = ["status=%s"]
            values: list = [target]
            for key, value in fields.items():
                sets.append(f"{key}=%s")
                jsonb = ("steps_recorded", "artifacts", "report", "summary")
                values.append(Jsonb(value, dumps=_dumps) if key in jsonb and value is not None else value)
            if target == "running":
                sets.append("started_at=now()")
            elif target != "blocked":
                sets.append("ended_at=now()")
            cur.execute(
                f"UPDATE case_execution SET {', '.join(sets)} WHERE id=%s",
                (*values, execution_id),
            )

    # ------------------------------------------------------------ entry points
    def debug(self, case_id, environment_id, executor: str = "auto") -> dict:
        """Single-case debug: same executors, no task_run, no report (§5.4)."""
        with self.db.tx() as cur:
            case = self._case(cur, case_id)
            if case["status"] == "deprecated":
                raise AppError("CONFLICT", "The case is deprecated")
            env = self._environment(cur, environment_id, case["sut_id"])
        if executor == "auto":
            automated = case["mode"] == "automated" and case["code_path"]
            if automated:
                executor = "pytest"
            else:
                executor = "agent_api" if is_api_case(case) else "agent_browser"
        if executor == "pytest" and not case["code_path"]:
            raise AppError("VALIDATION", "The case has no automation code yet (code_path)")
        envs.require_reachable(env)  # ENV_UNREACHABLE (503): the system under test is not running
        if executor in ("agent_browser", "agent_api") and self.runtime is not None:
            self.runtime.models.create()  # MODEL_UNAVAILABLE (503) before anything is recorded
        return self.execute_case(case, env, executor)

    def execute_case(self, case: dict, env: dict, executor: str, *, task_run_id=None) -> dict:
        with self.db.tx() as cur:
            row = self._create(cur, case, executor, env["id"], task_run_id)
        self._set_status(row["id"], "running")
        try:
            if executor in self.runners:
                fields = dict(self.runners[executor](case, env, row["id"]))
            elif executor == "agent_browser":
                fields = self._agent_browser(row["id"], case, env)
            elif executor == "agent_api":
                fields = self._agent_api(case, env)
            elif executor == "pytest":
                fields = self._pytest(case, env)
            else:
                raise AppError("VALIDATION", f"Executor {executor} cannot run automatically")
        except AppError as exc:
            fields = {"status": "error", "error": f"{exc.code}: {exc.message}"}
        except Exception as exc:  # executor crash must still close the record (C04)
            fields = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:2000]}
        status = fields.pop("status")
        unchanged = fields.pop("_script_unchanged", None)
        fields.update(
            classify(
                status,
                error=fields.get("error"),
                failed_assertion=fields.get("failed_assertion"),
                report=fields.get("report"),
                executor=executor,
                code_commit="bound" if unchanged else None,
                bound_commit="bound",
                requirements=self.requirements_of(case["id"]),
            )
        )
        self._set_status(row["id"], status, **fields)
        self.bus.publish("case_execution.finished", {"id": str(row["id"]), "status": status})
        return self.get(row["id"])

    def record_self_check(self, case_id, failure: dict, *, code_commit=None) -> dict:
        """A failed execution from an AI-automation self-check a person confirmed as a system
        issue (batch 2, #9). No task run: it shows in the case history and the version report."""
        ensure_human(self.actor, "Record a self-check failure")
        with self.db.tx() as cur:
            case = self._case(cur, case_id)
            row = self._create(cur, case, "pytest", None)
        raw = failure.get("raw") or failure.get("headline") or "Self-check failed"
        summary = {k: v for k, v in failure.items() if k != "raw"} or None
        self._set_status(row["id"], "running")
        self._set_status(
            row["id"],
            "failed",
            failed_assertion=raw[:4000],
            result="Recorded from the AI automation self-check (confirmed by a person)",
            code_commit=code_commit,
            failure_kind=failure.get("kind") or "assertion",
            suspected_cause="sut",
            summary={**summary, "cause": "sut"} if summary else None,
        )
        self.bus.publish("case_execution.finished", {"id": str(row["id"]), "status": "failed"})
        return self.get(row["id"])

    def _manual_class(self, case_id, data: dict) -> dict:
        """A person recorded the result: a failure is what they saw the system do."""
        if data["status"] not in ("failed", "error"):
            return {}
        return classify(
            data["status"],
            failed_assertion=data.get("failed_assertion"),
            error=data.get("failed_assertion") if data["status"] == "error" else None,
            executor="manual",
            requirements=self.requirements_of(case_id),
            reason=data.get("failed_assertion"),
        )

    def requirements_of(self, case_id) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT r.id, r.code, r.title, r.raw_text FROM case_requirement_link l"
                " JOIN requirement r ON r.id=l.requirement_id WHERE l.case_id=%s ORDER BY r.code",
                (case_id,),
            )
            return cur.fetchall()

    def record_forced(
        self, case: dict, env_id, executor: str, status: str, *, task_run_id=None, reason=None, kind=None
    ) -> dict:
        """A task-run case that is not executed: skipped (non-functional or no script),
        blocked (awaiting human) or error."""
        with self.db.tx() as cur:
            row = self._create(cur, case, executor, env_id, task_run_id)
        fields: dict = {}
        if status != "blocked":
            fields.update(
                classify(
                    status,
                    error=reason if status == "error" else None,
                    forced=kind,
                    reason=reason,
                    requirements=self.requirements_of(case["id"]),
                )
            )
        if status == "blocked":
            fields["blocked_reason"] = reason or "awaiting_human"
        elif status == "error":
            fields["error"] = reason
        else:
            fields["result"] = reason
        self._set_status(row["id"], status, **fields)
        self.bus.publish("case_execution.finished", {"id": str(row["id"]), "status": status})
        return self.get(row["id"])

    def complete_blocked(self, execution_id, data: dict) -> dict:
        """A human finishes an execution that a task run left blocked (awaiting_human, C11)."""
        ensure_human(self.actor, "Record manual execution result")
        files = self._attachments(data)
        with self.db.tx() as cur:
            cur.execute("SELECT status FROM case_execution WHERE id=%s FOR UPDATE", (execution_id,))
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", "Execution not found")
            if row["status"] != "blocked":
                raise AppError("CONFLICT", "Only executions waiting for a person (blocked) can take a manual result")
            cur.execute("UPDATE case_execution SET executed_by=%s WHERE id=%s", (self.actor, execution_id))
            log_change(
                cur,
                "case_execution",
                execution_id,
                "manual",
                self.actor,
                {"status": data["status"]},
            )
        fields = {
            "result": data.get("result"),
            "failed_assertion": data.get("failed_assertion"),
            "artifacts": files,
            "duration_ms": data.get("duration_ms"),
        }
        if data.get("actual_data") is not None:
            fields["test_data"] = Jsonb(data["actual_data"], dumps=_dumps)
        with self.db.tx() as cur:
            cur.execute("SELECT case_id FROM case_execution WHERE id=%s", (execution_id,))
            case_id = cur.fetchone()["case_id"]
        fields.update(self._manual_class(case_id, data))
        self._set_status(execution_id, data["status"], **fields)
        self.bus.publish("case_execution.finished", {"id": str(execution_id), "status": data["status"]})
        return self.get(execution_id)

    def _attachments(self, data: dict) -> list[dict]:
        files = []
        for item in data.get("attachments") or []:
            if self.artifacts is None:
                raise AppError("CONFIG_MISSING", "Artifact store is not configured")
            try:
                raw = base64.b64decode(item["content_base64"], validate=True)
            except ValueError as exc:
                raise AppError("VALIDATION", f"Attachment {item['name']} is not valid base64") from exc
            files.append({"kind": "attachment", "name": item["name"], "sha256": self.artifacts.put(raw)})
        return files

    def _agent_browser(self, execution_id, case: dict, env: dict) -> dict:
        if self.runtime is None or self.artifacts is None:
            raise AppError("CONFIG_MISSING", "Agent executor is not configured")
        self.runtime.models.create()  # MODEL_UNAVAILABLE before a browser is started
        session = BrowserSession(env["base_url"], self.artifacts, headless=self.headless).start()
        try:
            run = self.runtime.run(
                "execute_case_browser",
                {
                    "case": {
                        k: case[k]
                        for k in (
                            "code",
                            "title",
                            "preconditions",
                            "steps",
                            "test_data",
                            "expected",
                        )
                    },
                    "base_url": env["base_url"],
                },
                sut_id=case["sut_id"],
                resources={"browser": session},
            )
        finally:
            files = session.close()
        shots = [
            {"kind": "screenshot", "name": f"step-{s['seq']}.png", "sha256": s["screenshot_sha"]}
            for s in session.steps
            if s.get("screenshot_sha")
        ]
        out = {
            "agent_run_id": run["id"],
            "steps_recorded": session.steps,
            "artifacts": files + shots,
            "duration_ms": sum(s.get("ms", 0) for s in session.steps),
        }
        claim = (run.get("result") or {}).get("summary")
        if run["status"] in ("error", "cancelled"):
            return {**out, "status": "error", "error": f"{run['error_code']}: {run['error'] or ''}"}
        verdict = session.verdict()  # receipts only; the agent's claimed_status is ignored
        return {
            **out,
            "status": verdict.status,
            "failed_assertion": verdict.failed_assertion,
            "error": verdict.error,
            "result": claim,
        }

    def _agent_api(self, case: dict, env: dict) -> dict:
        from testagent.integrations.http_api import HttpApiSession

        if self.runtime is None:
            raise AppError("CONFIG_MISSING", "Agent executor is not configured")
        self.runtime.models.create()
        session = HttpApiSession(env["base_url"])
        keys = ("code", "title", "preconditions", "steps", "test_data", "expected")
        run = self.runtime.run(
            "execute_case_api",
            {"case": {k: case[k] for k in keys}, "base_url": env["base_url"]},
            sut_id=case["sut_id"],
            resources={"http": session},
        )
        out = {
            "agent_run_id": run["id"],
            "steps_recorded": session.steps,
            "duration_ms": sum(s.get("ms", 0) for s in session.steps),
        }
        claim = (run.get("result") or {}).get("summary")
        if run["status"] in ("error", "cancelled"):
            return {**out, "status": "error", "error": f"{run['error_code']}: {run['error'] or ''}"}
        verdict = session.verdict()
        return {
            **out,
            "status": verdict.status,
            "failed_assertion": verdict.failed_assertion,
            "error": verdict.error,
            "result": claim,
        }

    def _pytest(self, case: dict, env: dict) -> dict:
        repo = self.repo_for(case["sut_code"], case["sut_id"])
        repo.ensure()
        with repo.execution_snapshot(case.get("code_commit")) as snapshot:
            rel = snapshot.resolve_test_path(case["code_path"])
            if not (snapshot.path / rel).is_file():
                raise AppError("NOT_FOUND", f"does not exist in the bound test version: {rel}")
            execution_commit = snapshot.commit
            res = run_pytest(
                snapshot.path,
                rel,
                base_url=env["base_url"].rstrip("/") + "/",
                test_data=case["test_data"],
                timeout_s=self.pytest_timeout_s,
                artifacts=self.artifacts,
            )
        status = res["status"] if res["status"] in ("passed", "failed", "skipped") else "error"
        report = res.get("report")
        failure = next((t["failure"] for t in (report or {}).get("tests", []) if t.get("failure")), None)
        failed_assertion = res.get("failed_assertion")
        if failed_assertion and failure and failure.get("explain"):
            failed_assertion = f"{failure['explain']}\n\n{failed_assertion}"
        error = res.get("error") if status == "error" else None
        if error and failure and failure.get("explain") and failure["type"] != "AssertionError":
            error = f"{failure['explain']}\n\n{error}"
        unchanged = bool(case.get("code_commit") and execution_commit == case["code_commit"])
        return {
            "status": status,
            "report": report,
            "failed_assertion": failed_assertion,
            "error": error,
            "result": res.get("output", "")[-4000:],
            "artifacts": res.get("artifacts", []),
            "duration_ms": res.get("duration_ms"),
            "code_commit": execution_commit,
            "_script_unchanged": unchanged,
        }

    # ------------------------------------------------------------ manual (US-14)
    def record_manual(self, case_id, data: dict, *, task_run_id=None) -> dict:
        ensure_human(self.actor, "Record manual execution result")
        files = self._attachments(data)
        with self.db.tx() as cur:
            case = self._case(cur, case_id)
            env_id = data.get("environment_id")
            if env_id is not None:
                self._environment(cur, env_id, case["sut_id"])
            row = self._create(cur, case, "manual", env_id, task_run_id)
            actual = data.get("actual_data")
            cur.execute(
                "UPDATE case_execution SET status='running', started_at=now() WHERE id=%s",
                (row["id"],),
            )
            log_change(cur, "case_execution", row["id"], "manual", self.actor, {"status": data["status"]})
        fields = {
            "result": data.get("result"),
            "failed_assertion": data.get("failed_assertion"),
            "artifacts": files,
            "duration_ms": data.get("duration_ms"),
            "blocked_reason": data.get("blocked_reason"),
        }
        if actual is not None:  # actual data entered by the tester replaces the planned data
            fields["test_data"] = Jsonb(actual, dumps=_dumps)
        fields.update(self._manual_class(case_id, data))
        self._set_status(row["id"], data["status"], **fields)
        self.bus.publish("case_execution.finished", {"id": str(row["id"]), "status": data["status"]})
        return self.get(row["id"])
