"""AI completion for a test case: the agent proposes steps, expected result, test data and links
to requirements / model nodes / fields for a (usually hand-written) case. The proposal is stored
on the case (`test_case.ai_proposal`) and shown as a diff; only a human can accept it (C01)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from testagent.agent.runtime import AgentRuntime, Entry
from testagent.agent.tools import (
    action_summaries,
    api_summaries,
    check_request_bodies,
    link_summaries,
)
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.case_gen import StepOut, model_id_errors
from testagent.services.cases import CaseService
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human

COMPLETE_JOB = "complete_case"
PROPOSAL_FIELDS = (
    "test_point",
    "preconditions",
    "steps",
    "test_data",
    "expected",
    "requirement_ids",
    "node_ids",
    "attribute_ids",
    "category",
    "quality_tags",
)
LINK_FIELDS = ("requirement_ids", "node_ids", "attribute_ids")


class CompletionOut(BaseModel):
    test_point: Annotated[str, Field(min_length=1, max_length=2000)]
    preconditions: str | None = None
    steps: list[StepOut] = Field(min_length=1)
    test_data: dict[str, Any] | None = None
    expected: Annotated[str, Field(min_length=1, max_length=2000)]
    requirement_codes: list[str] = Field(default_factory=list)
    node_ids: list[UUID] = Field(default_factory=list)
    attribute_ids: list[UUID] = Field(default_factory=list)
    category: Literal["requirement", "quality", "regression"] | None = Field(
        default=None,
        description="requirement (incl. input validation), quality "
        "(idempotency, concurrency, repeatability/data reset), regression",
    )
    quality_tags: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]] | None = None
    rationale: Annotated[str, Field(min_length=1, max_length=2000)] = Field(
        description="one or two sentences: what was added and which requirement/model element it is based on"
    )


def complete_entry(db) -> Entry:
    def validate(out: CompletionOut, ctx: dict) -> list[str]:
        codes = {r["code"] for r in ctx["inputs"].get("requirements") or []}
        errors = [
            f"requirement code {c} is not one of {sorted(codes)}" for c in out.requirement_codes if c not in codes
        ]
        errors += model_id_errors(db, ctx["sut_id"], out.node_ids, out.attribute_ids)
        errors += check_request_bodies(
            db,
            ctx["sut_id"],
            [(f"step {j + 1}", s.action, s.data) for j, s in enumerate(out.steps)],
        )
        return errors

    return Entry(
        name=COMPLETE_JOB,
        output_schema=CompletionOut,
        tools=(
            "get_case",
            "list_requirements",
            "get_requirement",
            "list_nodes",
            "get_node",
            "search_nodes",
            "list_apis",
            "get_api_schema",
            "list_fields",
            "list_links",
            "search_memory",
        ),
        instructions=(
            "Complete the given test case (input `case`, often written by hand with only a title "
            "or a few steps). Keep its intent, title, scenario and type; do not invent a "
            "different test. Fill in or improve: the test point, preconditions, concrete steps "
            "(each with expected result), test data and the overall expected result, all in "
            "the output language. Link it to the requirement(s) it verifies (requirement_codes from input "
            "`requirements`), the model nodes (actions/entities, node_ids) and entity fields "
            "(attribute_ids) it exercises — IDs from the tools only. Keep existing links unless "
            "clearly wrong. When a step calls an API write 'METHOD /path' and put the exact JSON "
            "request body in the step data following the API schema; put the key values into "
            "test_data using the API field names. Respect action preconditions/effects (input "
            "`actions`) and relations (input `links`). Propose the category "
            "(requirement incl. input validation; quality: idempotency, "
            "concurrency, repeatability "
            "/data reset, with quality_tags; regression) only when the current one "
            "(input `case.category`) looks wrong. Explain briefly in `rationale`."
        ),
        validate=validate,
    )


def _version_of(cur, case: dict):
    if case.get("origin_version_id"):
        return case["origin_version_id"]
    if case.get("requirements"):
        return case["requirements"][0]["version_id"]
    cur.execute(
        "SELECT id FROM version WHERE sut_id=%s ORDER BY created_at DESC LIMIT 1",
        (case["sut_id"],),
    )
    row = cur.fetchone()
    return row["id"] if row else None


class CaseCompletionService:
    def __init__(self, db, bus: EventBus, runtime: AgentRuntime | None, actor: str = "local-user"):
        self.db = db
        self.bus = bus
        self.runtime = runtime
        self.actor = actor

    def _cases(self, actor: str | None = None) -> CaseService:
        return CaseService(self.db, self.bus, actor=actor or self.actor)

    def complete(self, case_id) -> dict:
        case = self._cases().get(case_id)
        if case["status"] == "deprecated":
            raise AppError("CONFLICT", "The case is deprecated and cannot be completed")
        with self.db.tx() as cur:
            version_id = _version_of(cur, case)
            reqs = []
            if version_id:
                cur.execute(
                    "SELECT id::text AS id, code, title FROM requirement WHERE version_id=%s ORDER BY code",
                    (version_id,),
                )
                reqs = cur.fetchall()
        current = {
            "code": case["code"],
            "title": case["title"],
            "scenario": case.get("scenario"),
            "type_tag": case.get("type_tag"),
            "priority": case.get("priority"),
            "category": case.get("category"),
            "quality_tags": case.get("quality_tags") or [],
            "test_point": case.get("test_point"),
            "preconditions": case.get("preconditions"),
            "steps": case.get("steps") or [],
            "test_data": case.get("test_data"),
            "expected": case.get("expected"),
            "requirement_codes": [r["code"] for r in case["requirements"]],
            "node_ids": [str(n["id"]) for n in case["nodes"]],
            "attribute_ids": [str(f["id"]) for f in case.get("fields") or []],
        }
        run = self.runtime.run(
            COMPLETE_JOB,
            {
                "case_id": str(case_id),
                "sut_id": str(case["sut_id"]),
                "version_id": str(version_id) if version_id else None,
                "case": current,
                "requirements": reqs,
                "apis": api_summaries(self.db, case["sut_id"]),
                "actions": action_summaries(self.db, case["sut_id"]),
                "links": link_summaries(self.db, case["sut_id"]),
            },
            sut_id=case["sut_id"],
        )
        summary = {
            "agent_run_id": str(run["id"]),
            "status": run["status"],
            "error_code": run["error_code"],
        }
        if run["status"] != "succeeded":
            return summary
        out = CompletionOut.model_validate(run["result"])
        by_code = {r["code"]: r["id"] for r in reqs}

        def union(old: list[str], new: list[str]) -> list[str]:  # never drop a human link
            return list(dict.fromkeys([*old, *new]))

        fields = {
            "test_point": out.test_point,
            "preconditions": out.preconditions,
            "steps": [s.model_dump() for s in out.steps],
            "test_data": out.test_data,
            "expected": out.expected,
            "requirement_ids": union(
                [str(r["id"]) for r in case["requirements"]],
                [by_code[c] for c in out.requirement_codes if c in by_code],
            ),
            "node_ids": union(current["node_ids"], [str(n) for n in out.node_ids]),
            "attribute_ids": union(current["attribute_ids"], [str(a) for a in out.attribute_ids]),
        }
        if out.category is not None and out.category != case.get("category"):
            fields["category"] = out.category
        if out.quality_tags is not None and out.quality_tags != (case.get("quality_tags") or []):
            fields["quality_tags"] = out.quality_tags
        proposal = {
            "agent_run_id": str(run["id"]),
            "created_at": datetime.now(UTC).isoformat(),
            "base_revision": case["revision"],
            "rationale": out.rationale,
            "fields": fields,
            "labels": self._labels(fields),
        }
        with self.db.tx() as cur:
            cur.execute("UPDATE test_case SET ai_proposal=%s WHERE id=%s", (Jsonb(proposal), case_id))
            log_change(
                cur,
                "test_case",
                case_id,
                "ai_proposal",
                f"agent:{run['id']}",
                {"fields": sorted(fields)},
            )
        self.bus.publish("case.ai_proposal", {"id": str(case_id)})
        return {**summary, "proposal": proposal}

    def _labels(self, fields: dict) -> dict[str, str]:
        ids = [i for k in LINK_FIELDS for i in fields[k]]
        if not ids:
            return {}
        with self.db.tx() as cur:
            cur.execute(
                "SELECT id::text AS id, code || ' ' || title AS label FROM requirement"
                " WHERE id = ANY(%(ids)s::uuid[])"
                " UNION ALL SELECT id::text, name FROM model_node WHERE id = ANY(%(ids)s::uuid[])"
                " UNION ALL SELECT a.id::text, n.name || '.' || a.name FROM entity_attribute a"
                " JOIN model_node n ON n.id=a.node_id WHERE a.id = ANY(%(ids)s::uuid[])",
                {"ids": ids},
            )
            return {r["id"]: r["label"] for r in cur.fetchall()}

    def accept(self, case_id, fields: list[str] | None = None) -> dict:
        """Apply the selected proposal fields as a new revision — human only (C01)."""
        ensure_human(self.actor, "Accept AI completion")
        with self.db.tx() as cur:
            cur.execute("SELECT ai_proposal FROM test_case WHERE id=%s", (case_id,))
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Test case not found")
        proposal = row["ai_proposal"]
        if not proposal:
            raise AppError("CONFLICT", "No pending AI completion to accept")
        chosen = [f for f in (fields or PROPOSAL_FIELDS) if f in proposal["fields"]]
        unknown = set(fields or []) - set(PROPOSAL_FIELDS)
        if unknown:
            raise AppError("VALIDATION", f"Unknown field: {', '.join(sorted(unknown))}")
        data = {f: proposal["fields"][f] for f in chosen}
        self._cases().update(case_id, data)
        with self.db.tx() as cur:
            cur.execute("UPDATE test_case SET ai_proposal=NULL WHERE id=%s", (case_id,))
            log_change(cur, "test_case", case_id, "ai_proposal_accept", self.actor, {"fields": chosen})
        return self._cases().get(case_id)

    def reject(self, case_id) -> dict:
        with self.db.tx() as cur:
            cur.execute("UPDATE test_case SET ai_proposal=NULL WHERE id=%s RETURNING id", (case_id,))
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "Test case not found")
            log_change(cur, "test_case", case_id, "ai_proposal_reject", self.actor, {})
        return self._cases().get(case_id)


def enqueue_completion(jobs, case_ids: list) -> dict:
    job_ids = [jobs.enqueue(COMPLETE_JOB, {"case_id": str(c)}) for c in case_ids]
    return {"queued": len(job_ids), "job_ids": job_ids}
