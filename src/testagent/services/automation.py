"""`automate_case` (T-08.5): the agent writes a pytest-playwright file into the SUT test repo,
self-checks it with run_pytest (budget from the agent config, default 5), then the service commits
it as TestAgent. Only a file whose LAST self-check passed is bound to the case (mode=automated);
otherwise it is committed as a draft and the case is marked needs_fix with the reason.
Only the case's own test file may be written (no probe/helper files). Manual binding pins the
current HEAD."""

from __future__ import annotations

from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from testagent.agent.runtime import AgentRuntime, Entry
from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.integrations.git_repo import TestRepo, target_test_path
from testagent.integrations.pytest_runner import run_pytest
from testagent.services import environments as envs
from testagent.services.cases import CaseService
from testagent.services.changelog import log_change
from testagent.services.failure_classify import classify
from testagent.services.guards import ensure_human

DEFAULT_SELF_CHECKS = 5
AUTOMATE_JOB = "automate_case"


class SelfCheckVerdict(BaseModel):
    """The agent's reading of the LAST self-check (batch 2, #9); checked by the platform."""

    verdict: Literal["passed", "sut_mismatch", "script_issue", "unclear"]
    expected: str | None = Field(default=None, max_length=500)
    actual: str | None = Field(default=None, max_length=500)
    requirement_code: str | None = Field(default=None, max_length=50)
    rule: str | None = Field(default=None, max_length=500)
    explanation: str = Field(default="", max_length=1000)


class AutomateOut(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    verdict: SelfCheckVerdict | None = None


class WriteArgs(BaseModel):
    content: str = Field(description="full Python source of the test file")
    path: str | None = Field(default=None, description="defaults to the case's file; must stay under tests/")


class RunArgs(BaseModel):
    path: str | None = None


def register_automation_tools(registry) -> None:
    from testagent.agent.tools import ToolSpec, to_text

    def state(ctx: dict) -> dict:
        res = ctx.get("resources", {}).get("automation")
        if res is None:
            raise AppError("VALIDATION", "no test repository bound to this run")
        return res

    def write_test_file(ctx, content: str, path: str | None = None) -> str:
        st = state(ctx)
        rel = st["repo"].resolve_test_path(path or st["target"])
        if rel != st["target"]:
            raise AppError(
                "VALIDATION",
                f"only the case file {st['target']} may be written (no probe or helper files);"
                " put helpers inside that file",
            )
        st["repo"].write(rel, content)
        st["written"].add(rel)
        st["last_check"] = None  # the new content is not verified yet
        return to_text({"written": rel})

    def run_pytest_tool(ctx, path: str | None = None) -> str:
        st = state(ctx)
        budget = st.get("max_checks", DEFAULT_SELF_CHECKS)
        if st["checks"] >= budget:
            return f"Error: self-check limit ({budget}) reached; submit_result now."
        if not st.get("base_url"):
            return "Error: no environment selected, self-check unavailable; submit_result."
        if st["target"] not in st["written"]:
            return f"Error: write {st['target']} with write_test_file first."
        st["checks"] += 1
        res = run_pytest(
            st["repo"].path,
            st["target"],
            base_url=st["base_url"],
            test_data=st["test_data"],
            timeout_s=st["timeout_s"],
        )
        keys = ("status", "failed_assertion", "error")
        left = budget - st["checks"]
        tests = (res.get("report") or {}).get("tests") or []
        failure = next((t["failure"] for t in tests if t.get("failure")), None)
        st["last_check"] = {k: res.get(k) for k in keys}
        st["last_check"]["report"] = {"tests": [{"failure": failure}]} if failure else None
        return to_text(
            {
                **{k: res.get(k) for k in keys},
                "explain": failure.get("explain") if failure else None,
                "self_checks_left": left,
                "output": res["output"][-3000:],
            }
        )

    registry.register(
        ToolSpec(
            "write_test_file",
            "repo",
            "Write the case's pytest-playwright test file (fixtures: page, base_url, test_data,"
            " step, check)."
            " Only the case file itself may be written.",
            WriteArgs,
            write_test_file,
            writes=True,
            needs_ctx=True,
        )
    )
    registry.register(
        ToolSpec(
            "run_pytest",
            "repo",
            "Run the case file once against the environment (limited budget, see input).",
            RunArgs,
            run_pytest_tool,
            writes=False,
            needs_ctx=True,
        )
    )


def automate_entry() -> Entry:
    return Entry(
        name="automate_case",
        output_schema=AutomateOut,
        tools=(
            "write_test_file",
            "run_pytest",
            "get_case",
            "list_apis",
            "get_api_schema",
            "list_fields",
            "list_links",
        ),
        instructions=(
            "Turn the manual test case into a pytest + pytest-playwright test. Use the `page` "
            "fixture with relative URLs (base_url is set; API calls via page.request with paths "
            "WITHOUT a leading slash, e.g. page.request.post('sample/orders', data=...)), the "
            "`test_data` fixture for data. Structure the test with the repo's `step` and "
            "`check` fixtures so the run report is readable: wrap each case step in "
            "`with step('Step 1: create purchase order'):` (names following the case steps) and "
            "verify every expected result with `check('description', actual, expected)` (optional "
            "op: '==', '!=', '>', '>=', '<', '<=', 'in', 'not in', 'contains', 'is'), e.g. "
            "check('returns 201', resp.status, 201), check('state is pending approval', order['state'], "
            "'pending'). Request bodies MUST follow the API schemas in the input (`apis`) or from "
            "get_api_schema exactly: same field names, types and units, no extra fields; the "
            "response fields, the actions' inputs/outputs and effects (`actions`) tell what to "
            "assert; set up the actions' preconditions first. Do "
            "not write probing code that guesses endpoints or fields. Write the file with "
            "write_test_file, run it with run_pytest and fix it until it passes (budget in "
            "`self_check_budget`). The case is bound only if the LAST run passed; if the "
            "system itself behaves differently from the expected result, keep the assertion "
            "and explain it in the summary. Never change an assertion just to make it pass. "
            "When the LAST self-check failed on an assertion, fill `verdict`: sut_mismatch when "
            "the expected value comes from the case or a requirement and the system returns "
            "something else (give expected, actual, requirement_code and the rule); "
            "script_issue when a field name, path, step or data in the script is wrong; "
            "unclear otherwise. Finish with submit_result."
        ),
    )


class AutomationService:
    def __init__(
        self,
        db,
        bus: EventBus,
        runtime: AgentRuntime,
        repos_root,
        *,
        pytest_timeout_s: float = 300,
    ):
        self.db = db
        self.bus = bus
        self.runtime = runtime
        self.repos_root = repos_root
        self.pytest_timeout_s = pytest_timeout_s

    def _load(self, case_id) -> tuple[dict, TestRepo]:
        case = CaseService(self.db, self.bus).get(case_id)
        if case["status"] == "deprecated":
            raise AppError("CONFLICT", "The case is deprecated")
        with self.db.tx() as cur:
            cur.execute("SELECT code FROM sut WHERE id=%s", (case["sut_id"],))
            sut_code = cur.fetchone()["code"]
        return case, TestRepo(self.repos_root, sut_code, str(case["sut_id"]))

    def _environment(self, case: dict, environment_id) -> dict | None:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT * FROM environment WHERE sut_id=%s AND (%s::uuid IS NULL OR id=%s) ORDER BY created_at LIMIT 1",
                (case["sut_id"], environment_id, environment_id),
            )
            row = cur.fetchone()
        if row is None:
            if environment_id is not None:
                raise AppError("NOT_FOUND", "The execution environment does not exist or belongs to another SUT")
            return None
        return row

    def _api_context(self, sut_id) -> list[dict]:
        from testagent.agent.tools import api_summaries

        return api_summaries(self.db, sut_id)

    def _action_context(self, case: dict) -> list[dict]:
        from testagent.agent.tools import action_summaries

        ids = [str(n["id"]) for n in case.get("nodes") or []]
        return action_summaries(self.db, case["sut_id"], ids) if ids else []

    def automate(self, case_id, environment_id=None) -> dict:
        case, repo = self._load(case_id)
        env = self._environment(case, environment_id)
        base_url = env["base_url"].rstrip("/") + "/" if env else None
        if env is not None and not envs.probe(env["base_url"])[0]:
            # a stopped system is not a broken script - no agent run, no attempts spent
            return self._env_unavailable(case_id, env)
        repo.ensure()
        repo.ensure_clean()  # REPO_DIRTY before the agent spends any effort
        target = target_test_path(case["code"], [r["code"] for r in case["requirements"]])
        budget = self.runtime.models.config.load().max_self_checks or DEFAULT_SELF_CHECKS
        state = {
            "repo": repo,
            "target": target,
            "written": set(),
            "checks": 0,
            "max_checks": budget,
            "last_check": None,
            "base_url": base_url,
            "test_data": case["test_data"],
            "timeout_s": self.pytest_timeout_s,
        }
        keys = ("code", "title", "preconditions", "steps", "test_data", "expected")
        run = self.runtime.run(
            "automate_case",
            {
                "case_id": str(case_id),
                "case": {k: case[k] for k in keys},
                "target_path": target,
                "self_check_budget": budget if base_url else 0,
                "apis": self._api_context(case["sut_id"]),
                "actions": self._action_context(case),
            },
            sut_id=case["sut_id"],
            resources={"automation": state},
        )
        summary = {
            "agent_run_id": str(run["id"]),
            "status": run["status"],
            "error_code": run["error_code"],
            "self_checks": state["checks"],
            "last_check": state["last_check"],
        }
        if target not in state["written"]:
            reason = "The agent did not write a test file"
            if run["status"] != "succeeded":
                reason = f"The agent did not finish ({run['error_code']}): {run.get('error') or ''}".strip()
            self._needs_fix(case_id, None, None, reason, actor=f"agent:{run['id']}")
            if run["status"] != "succeeded":
                return {**summary, "reason": reason}
            return {**summary, "status": "failed", "error_code": "NO_TEST_FILE", "reason": reason}
        last = state["last_check"] or {}
        if run["status"] == "succeeded" and last.get("status") == "passed":
            sha = repo.commit_files([target], f"testagent: {case['code']} {case['title']}")
            bound = self._bind(case_id, target, sha, actor=f"agent:{run['id']}")
            return {**summary, "code_path": target, "code_commit": sha, "case": bound}
        # 5(b): never bind an unverified or failing script; keep it as a draft to fix
        if env is not None and not envs.probe(env["base_url"])[0]:
            # the system went down during the self-checks: keep the draft, retry later
            sha = repo.commit_files([target], f"testagent: draft (env down) {case['code']}")
            return {
                **summary,
                **self._env_unavailable(case_id, env, target, sha),
                "draft_path": target,
                "draft_commit": sha,
            }
        if not base_url:
            reason = "No execution environment configured; cannot self-check"
        elif not last:
            reason = "The last code version was not self-checked"
        else:
            reason = last.get("failed_assertion") or last.get("error") or "Self-check failed"
        if run["status"] != "succeeded":
            reason = f"The agent did not finish ({run['error_code']}); {reason}"
        verdict = None
        if run["status"] == "succeeded" and isinstance(run.get("result"), dict):
            verdict = (run["result"] or {}).get("verdict")
        failure = None
        if last:
            failure = classify(
                last.get("status") or "error",
                error=last.get("error"),
                failed_assertion=last.get("failed_assertion"),
                report=last.get("report"),
                executor="pytest",
                phase="self_check",
                verdict=verdict,
                case=case,
                requirements=case["requirements"],
            )
        sut = bool(failure and failure["suspected_cause"] == "sut")
        sha = repo.commit_files([target], f"testagent: draft ({'sut mismatch' if sut else 'needs fix'}) {case['code']}")
        detail = None
        if failure and failure["summary"]:
            detail = {**failure["summary"], "raw": reason[:4000]}
        row = self._needs_fix(
            case_id,
            target,
            sha,
            reason,
            actor=f"agent:{run['id']}",
            status="sut_mismatch" if sut else "needs_fix",
            failure=detail,
        )
        return {
            **summary,
            "status": "sut_mismatch" if sut else "needs_fix",
            "error_code": "SUT_MISMATCH" if sut else "SELF_CHECK_FAILED",
            "draft_path": target,
            "draft_commit": sha,
            "reason": reason,
            "failure": detail,
            "case": row,
        }

    def _env_unavailable(self, case_id, env: dict, path=None, sha=None) -> dict:
        """Mark env_unavailable (retryable); a bound script stays bound."""
        reason = envs.unreachable_message(env)
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE test_case SET automation_status=CASE WHEN automation_status='ok'"
                " THEN 'ok' ELSE 'env_unavailable' END, automation_note=CASE WHEN"
                " automation_status='ok' THEN automation_note ELSE %s END,"
                " automation_draft_path=coalesce(%s, automation_draft_path),"
                " automation_draft_commit=coalesce(%s, automation_draft_commit) WHERE id=%s",
                (reason, path, sha, case_id),
            )
            log_change(
                cur,
                "test_case",
                case_id,
                "automation_env_unavailable",
                "system",
                {"reason": reason},
            )
        self.bus.publish("case.automation_env_unavailable", {"id": str(case_id)})
        return {
            "status": "env_unavailable",
            "error_code": "ENV_UNREACHABLE",
            "reason": reason,
            "case": CaseService(self.db, self.bus).get(case_id),
        }

    def _needs_fix(
        self,
        case_id,
        path: str | None,
        sha: str | None,
        reason: str,
        *,
        actor: str,
        status: str = "needs_fix",
        failure: dict | None = None,
    ) -> dict:
        note = (failure or {}).get("headline") or reason
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE test_case SET automation_status=%s, automation_note=%s, automation_failure=%s,"
                " automation_draft_path=coalesce(%s, automation_draft_path),"
                " automation_draft_commit=coalesce(%s, automation_draft_commit) WHERE id=%s",
                (status, note[:4000], Jsonb(failure) if failure else None, path, sha, case_id),
            )
            log_change(
                cur,
                "test_case",
                case_id,
                f"automation_{status}",
                actor,
                {"path": path, "commit": sha, "reason": reason[:500]},
            )
        self.bus.publish(f"case.automation_{status}", {"id": str(case_id)})
        return CaseService(self.db, self.bus).get(case_id)

    # ------------------------------------------------------------ batch 2 (#9): a person decides
    def confirm_sut_issue(self, case_id, action: str = "bind_and_record", create_defect: bool = False) -> dict:
        """The self-check found the system behaving differently from the expected result and a
        person agrees. bind_and_record binds the draft (later runs keep failing until the
        system is fixed) and records a failed execution; record_only only records it."""
        actor = current_actor()
        ensure_human(actor, "Confirm a suspected system issue")
        case, repo = self._load(case_id)
        if case["automation_status"] != "sut_mismatch":
            raise AppError("CONFLICT", "The case has no suspected system issue from a self-check")
        path, sha = case["automation_draft_path"], case["automation_draft_commit"]
        failure = dict(case.get("automation_failure") or {})
        if action == "bind_and_record":
            if not path or not sha:
                raise AppError("CONFLICT", "There is no draft script to bind")
            repo.ensure()
            self._bind(case_id, path, sha, actor=actor)
        from testagent.services.executions import ExecutionService

        execution = ExecutionService(self.db, self.bus, actor=actor).record_self_check(
            case_id, failure, code_commit=sha
        )
        defect = None
        if create_defect:
            from testagent.services.defects import DefectService

            defect = DefectService(self.db, self.bus, actor=actor).create_from_execution(
                execution["id"], {"suggested_cause": "development", "severity": "major"}
            )
        if action == "record_only":
            with self.db.tx() as cur:
                log_change(
                    cur, "test_case", case_id, "sut_issue_recorded", actor, {"execution_id": str(execution["id"])}
                )
        return {
            "case": CaseService(self.db, self.bus).get(case_id),
            "execution": execution,
            "defect": defect,
        }

    def mark_script_issue(self, case_id) -> dict:
        """A person says the self-check failure is the script's fault after all."""
        actor = current_actor()
        ensure_human(actor, "Mark as a script issue")
        case = CaseService(self.db, self.bus).get(case_id)
        if case["automation_status"] != "sut_mismatch":
            raise AppError("CONFLICT", "The case has no suspected system issue from a self-check")
        failure = dict(case.get("automation_failure") or {})
        if failure:
            failure["cause"] = "script"
            failure["next_actions"] = ["regenerate", "edit_case"]
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE test_case SET automation_status='needs_fix', automation_failure=%s WHERE id=%s",
                (Jsonb(failure) if failure else None, case_id),
            )
            log_change(cur, "test_case", case_id, "automation_needs_fix", actor, {"by": "person"})
        return CaseService(self.db, self.bus).get(case_id)

    def bind_existing(self, case_id, code_path: str) -> dict:
        """A human-written automated test: bind the file and the current HEAD (§6)."""
        case, repo = self._load(case_id)
        repo.ensure()
        rel = repo.resolve_test_path(code_path)
        if not repo.exists(rel):
            raise AppError("NOT_FOUND", f"does not exist in the test repo {rel}")
        if rel in repo.dirty_files():
            raise AppError("REPO_DIRTY", f"{rel} has uncommitted changes; commit them first", related=[rel])
        return self._bind(case_id, rel, repo.head(), actor=current_actor())

    def _bind(self, case_id, code_path: str, sha: str, *, actor: str) -> dict:
        cases = CaseService(self.db, self.bus, actor=actor)
        cases.update(case_id, {"code_path": code_path, "mode": "automated"})
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE test_case SET code_commit=%s, automation_status='ok', automation_note=NULL,"
                " automation_failure=NULL, automation_draft_path=NULL, automation_draft_commit=NULL"
                " WHERE id=%s",
                (sha, case_id),
            )
            log_change(
                cur,
                "test_case",
                case_id,
                "bind_code",
                actor,
                {"code_path": code_path, "commit": sha},
            )
        self.bus.publish("case.automated", {"id": str(case_id), "commit": sha})
        return cases.get(case_id)
