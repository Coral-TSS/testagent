"""`analyze_failure` agent entry (T-10.4): suggests a cause category (suggested_cause only) and,
for product issues, files a defect as the agent with cause_category left 'unknown' (C01)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from testagent.agent.runtime import AgentRuntime, Entry
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.attribution import PRODUCT_CAUSES
from testagent.services.defects import FAILED, DefectService

Cause = Literal["requirement", "design", "development", "test", "environment", "unknown"]


class DefectDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=8000)
    severity: Literal["critical", "major", "minor", "trivial"] = "major"


class FailureAnalysisOut(BaseModel):
    suggested_cause: Cause
    is_product_issue: bool = Field(
        description="true only when the system under test (requirement/design/code) is at fault"
    )
    analysis: str = Field(min_length=1, max_length=8000)
    defect: DefectDraft | None = None


def analysis_entry() -> Entry:
    return Entry(
        name="analyze_failure",
        output_schema=FailureAnalysisOut,
        tools=("get_case", "get_requirement", "list_apis", "search_memory"),
        instructions=(
            "Analyse why the test execution failed using the failed assertion, error, recorded "
            "steps and test data. Classify the most likely cause: requirement (requirement wrong "
            "or ambiguous), design, development (implementation bug), test (the test case or "
            "script is wrong), environment (environment/data/network), or unknown. Set "
            "is_product_issue only for requirement/design/development and then draft a defect "
            "(title, reproduction description, severity). Describe facts objectively; your "
            "category is only a suggestion for a person to confirm."
        ),
    )


def _brief_steps(steps: list[dict]) -> list[dict]:
    keep = ("seq", "action", "target", "value", "result", "status")
    return [{k: s.get(k) for k in keep if s.get(k) is not None} for s in steps[-30:]]


class FailureAnalysisService:
    def __init__(self, db, bus: EventBus, runtime: AgentRuntime):
        self.db = db
        self.bus = bus
        self.runtime = runtime

    def analyze(self, execution_id) -> dict:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT e.*, c.sut_id, c.code AS case_code, c.title AS case_title, c.steps,"
                " c.expected FROM case_execution e JOIN test_case c ON c.id=e.case_id"
                " WHERE e.id=%s",
                (execution_id,),
            )
            ex = cur.fetchone()
            if ex is None:
                raise AppError("NOT_FOUND", "Execution not found")
            if ex["status"] not in FAILED:
                raise AppError("CONFLICT", "Only failed or errored executions can be analysed")
            cur.execute(
                "SELECT r.code, r.title FROM case_requirement_link l JOIN requirement r"
                " ON r.id=l.requirement_id WHERE l.case_id=%s ORDER BY r.code",
                (ex["case_id"],),
            )
            reqs = cur.fetchall()
        self.runtime.models.create()  # MODEL_UNAVAILABLE (503) before a run is recorded
        run = self.runtime.run(
            "analyze_failure",
            {
                "execution_id": str(execution_id),
                "case": {
                    "id": str(ex["case_id"]),
                    "code": ex["case_code"],
                    "title": ex["case_title"],
                    "steps": ex["steps"],
                    "expected": ex["expected"],
                },
                "requirements": reqs,
                "status": ex["status"],
                "failed_assertion": ex["failed_assertion"],
                "error": ex["error"],
                # batch 2: the platform's own first reading (kind / suspected cause / summary)
                "platform_reading": {
                    "failure_kind": ex.get("failure_kind"),
                    "suspected_cause": ex.get("suspected_cause"),
                    "summary": ex.get("summary"),
                },
                "result": (ex["result"] or "")[-2000:],
                "test_data": ex["test_data"],
                "steps_recorded": _brief_steps(ex["steps_recorded"] or []),
            },
            sut_id=ex["sut_id"],
        )
        out = {
            "agent_run_id": str(run["id"]),
            "status": run["status"],
            "error_code": run["error_code"],
            "suggested_cause": None,
            "analysis": None,
            "defect": None,
        }
        if run["status"] != "succeeded":
            return out
        result = FailureAnalysisOut.model_validate(run["result"])
        out["suggested_cause"] = result.suggested_cause
        out["analysis"] = result.analysis
        product = result.is_product_issue and result.suggested_cause in PRODUCT_CAUSES
        if product:
            draft = result.defect or DefectDraft(
                title=f"[{ex['case_code']}] {ex['failed_assertion'] or ex['case_title']}"[:300],
                description=result.analysis,
            )
            agent = DefectService(self.db, self.bus, actor=f"agent:{run['id']}")
            defect = agent.create_from_execution(
                execution_id,
                {
                    "title": draft.title,
                    "description": draft.description,
                    "severity": draft.severity,
                    "suggested_cause": result.suggested_cause,
                    "analysis": result.analysis,
                },
                agent_run_id=run["id"],
            )
            out["defect"] = {"id": str(defect["id"]), "code": defect["code"]}
        return out
