"""`generate_cases` agent entry (T-07.2): ≥3 cases per requirement (normal/boundary/exception),
linked to requirements and model nodes. Output is written as draft cases (C01)."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from testagent.agent.runtime import AgentRuntime, Entry
from testagent.agent.tools import (
    action_summaries,
    api_summaries,
    check_request_bodies,
    link_summaries,
)
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.cases import CaseService
from testagent.services.changelog import log_change

MIN_CASES_PER_REQUIREMENT = 3
SCENARIO_TAGS = ("normal", "boundary", "exception")
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class StepOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Text
    data: str | None = None
    expected: str | None = None


class CaseDraft(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=300)]
    test_point: Text
    scenario: Literal["normal", "boundary", "exception"]
    priority: Literal["P0", "P1", "P2"] = "P1"
    type_tag: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")] = "functional"
    category: Literal["requirement", "quality", "regression"] = Field(
        default="requirement",
        description="requirement (business rules incl. input validation/error codes), "
        "quality (idempotency, concurrency, repeatability/data reset), "
        "regression (main-path smoke)",
    )
    quality_tags: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]] = Field(
        default_factory=list,
        description="for quality cases: idempotency, concurrency, repeatability, data_reset, ...",
    )
    preconditions: str | None = None
    steps: list[StepOut] = Field(min_length=1)
    test_data: dict[str, Any] | None = None
    expected: Text
    requirement_codes: list[str] = Field(min_length=1)
    node_ids: list[UUID] = Field(default_factory=list)
    attribute_ids: list[UUID] = Field(
        default_factory=list, description="entity fields the case exercises (from list_fields)"
    )

    @model_validator(mode="after")
    def _scenario_is_not_a_type(self):
        """'boundary'/'exception'/'normal' are scenarios (test design), not test types."""
        if self.type_tag in SCENARIO_TAGS:
            self.type_tag = "functional"
        return self


class CasesOut(BaseModel):
    cases: list[CaseDraft] = Field(min_length=1)


def model_id_errors(db, sut_id, node_ids, attribute_ids) -> list[str]:
    """Agent output may only reference live nodes / fields of this system."""
    errors: list[str] = []
    nodes = {str(n) for n in node_ids}
    attrs = {str(a) for a in attribute_ids}
    with db.tx() as cur:
        if nodes:
            cur.execute(
                "SELECT id::text AS id FROM model_node WHERE id = ANY(%s::uuid[]) AND sut_id=%s AND deleted_at IS NULL",
                (list(nodes), sut_id),
            )
            valid = {r["id"] for r in cur.fetchall()}
            errors += [f"node_id {n} does not exist in this system's model" for n in sorted(nodes - valid)]
        if attrs:
            cur.execute(
                "SELECT id::text AS id FROM entity_attribute WHERE id = ANY(%s::uuid[])"
                " AND sut_id=%s AND deleted_at IS NULL",
                (list(attrs), sut_id),
            )
            valid = {r["id"] for r in cur.fetchall()}
            errors += [f"attribute_id {a} does not exist" for a in sorted(attrs - valid)]
    return errors


def cases_entry(db) -> Entry:
    def validate(out: CasesOut, ctx: dict) -> list[str]:
        targets: list[str] = ctx["inputs"]["requirement_codes"]
        errors = []
        unknown = {c for d in out.cases for c in d.requirement_codes} - set(targets)
        errors += [f"requirement code {c} is not one of {targets}" for c in sorted(unknown)]
        per_req = Counter(c for d in out.cases for c in set(d.requirement_codes))
        errors += [
            f"requirement {c} needs at least {MIN_CASES_PER_REQUIREMENT} cases "
            f"(normal/boundary/exception), got {per_req.get(c, 0)}"
            for c in targets
            if per_req.get(c, 0) < MIN_CASES_PER_REQUIREMENT
        ]
        errors += model_id_errors(
            db,
            ctx["sut_id"],
            [n for d in out.cases for n in d.node_ids],
            [a for d in out.cases for a in d.attribute_ids],
        )
        errors += check_request_bodies(
            db,
            ctx["sut_id"],
            [
                (f"case {i + 1} step {j + 1}", step.action, step.data)
                for i, d in enumerate(out.cases)
                for j, step in enumerate(d.steps)
            ],
        )
        return errors

    return Entry(
        name="generate_cases",
        output_schema=CasesOut,
        tools=(
            "list_requirements",
            "get_requirement",
            "list_nodes",
            "get_node",
            "search_nodes",
            "list_apis",
            "get_api_schema",
            "list_fields",
            "list_links",
            "list_cases",
            "search_memory",
        ),
        instructions=(
            "Write functional test cases for each target requirement: at least "
            f"{MIN_CASES_PER_REQUIREMENT} per requirement covering normal, boundary and exception "
            "scenarios. Each case has a test point, concrete steps, test data, the expected "
            "result, the requirement codes it verifies, the IDs of the model nodes "
            "(actions/entities) and of the entity fields (attribute_ids) it exercises. Use IDs "
            "returned by the tools only. When a step calls an API, write it as 'METHOD /path' "
            "and put the exact JSON request body in the step data: field names, types and "
            "units MUST follow the API schema (input `apis` / get_api_schema), never invent "
            "fields. Input `actions` gives each action's purpose, inputs and outputs (types, "
            "formats, enum values, Entity.field): derive boundary and invalid inputs from them and "
            "state the expected outputs. Put the key values (e.g. the amount) into test_data "
            "using the API field names. Each action lists its preconditions (e.g. PurchaseOrder.state == "
            "pending) and effects (e.g. PurchaseOrder.state → approved | rejected, create link Payment pays "
            "PurchaseOrder): cover the precondition being met and violated (expected refusal) and assert "
            "every effect (field values, created objects, links). Input `links` gives the "
            "relations between entities with both readings, cardinality, required flag and "
            "foreign-key field: derive boundary/exception cases from them — a required N:1 "
            "foreign key missing or pointing to a non-existent object, the '1' side of a 1:1 "
            "already taken, several objects on the 'N' side (1:N/M:N), unlinking. Avoid "
            "duplicating existing cases (list_cases). Give every case a category: requirement "
            "(the requirement's business rules, including input validation and error "
            "codes), quality (idempotency, concurrency/duplicate submission, "
            "repeatability and data reset; add quality_tags) or regression (main-path smoke). "
            "Boundary/exception are scenarios, never the type_tag."
        ),
        validate=validate,
    )


class CaseGenerationService:
    def __init__(self, db, bus: EventBus, runtime: AgentRuntime):
        self.db = db
        self.bus = bus
        self.runtime = runtime

    def generate(
        self,
        version_id,
        requirement_ids: list | None = None,
        *,
        automate: bool | None = None,
        environment_id=None,
        jobs=None,
    ) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM version WHERE id=%s", (version_id,))
            version = cur.fetchone()
            if version is None:
                raise AppError("NOT_FOUND", "Version not found")
            if version["status"] == "closed":
                raise AppError("CONFLICT", "The version is closed")
            cur.execute(
                "SELECT id::text AS id, code, title FROM requirement WHERE version_id=%s"
                " AND (%s::uuid[] IS NULL OR id = ANY(%s::uuid[])) ORDER BY code",
                (
                    version_id,
                    [str(r) for r in requirement_ids] if requirement_ids else None,
                    [str(r) for r in requirement_ids] if requirement_ids else None,
                ),
            )
            reqs = cur.fetchall()
        if requirement_ids and len(reqs) != len(set(map(str, requirement_ids))):
            raise AppError("NOT_FOUND", "Some requirements do not exist or do not belong to this version")
        if not reqs:
            raise AppError("VALIDATION", "This version has no requirements yet")
        run = self.runtime.run(
            "generate_cases",
            {
                "version_id": str(version_id),
                "sut_id": str(version["sut_id"]),
                "requirement_codes": [r["code"] for r in reqs],
                "requirements": [{"id": r["id"], "code": r["code"], "title": r["title"]} for r in reqs],
                "apis": api_summaries(self.db, version["sut_id"]),
                "actions": action_summaries(self.db, version["sut_id"]),
                "links": link_summaries(self.db, version["sut_id"]),
            },
            sut_id=version["sut_id"],
        )
        summary = {
            "agent_run_id": str(run["id"]),
            "status": run["status"],
            "error_code": run["error_code"],
        }
        if run["status"] != "succeeded":
            return summary
        out = CasesOut.model_validate(run["result"])
        by_code = {r["code"]: r["id"] for r in reqs}
        cases = CaseService(self.db, self.bus, actor=f"agent:{run['id']}")
        created = []
        with self.db.tx() as cur:
            for draft in out.cases:
                data = draft.model_dump(mode="json", exclude={"requirement_codes"})
                data["requirement_ids"] = [by_code[c] for c in draft.requirement_codes]
                data["origin_version_id"] = version_id
                row = cases.create(version["sut_id"], data, cur=cur, agent_run_id=run["id"])
                created.append({"id": str(row["id"]), "code": row["code"], "title": row["title"]})
            report = cases.save_coverage(version_id, cur=cur, agent_run_id=run["id"])
            log_change(
                cur,
                "version",
                version_id,
                "generate_cases",
                f"agent:{run['id']}",
                {"cases": len(created)},
            )
        self.bus.publish("cases.generated", {"version_id": str(version_id), "count": len(created)})
        if automate is None:
            automate = self.runtime.models.config.load().auto_automate
        automation = {"queued": 0, "job_ids": []}
        if automate and jobs is not None:
            automation = enqueue_automation(jobs, [c["id"] for c in created], version_id, environment_id)
        return {
            **summary,
            "cases": created,
            "coverage": report["content"],
            "automation": automation,
        }


def enqueue_automation(jobs, case_ids: list, version_id, environment_id=None) -> dict:
    """One background `automate_case` job per case (C09); progress via the jobs table."""
    from testagent.services.automation import AUTOMATE_JOB

    job_ids = [
        jobs.enqueue(
            AUTOMATE_JOB,
            {
                "case_id": str(cid),
                "version_id": str(version_id),
                "environment_id": str(environment_id) if environment_id else None,
            },
        )
        for cid in case_ids
    ]
    return {"queued": len(job_ids), "job_ids": job_ids}
