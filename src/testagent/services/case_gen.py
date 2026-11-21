"""`generate_cases` agent entry (T-07.2): ≥3 cases per requirement (normal/boundary/exception),
linked to requirements and model nodes. Output is written as draft cases (C01)."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from testagent.agent.runtime import AgentRuntime, Entry
from testagent.agent.tools import check_request_bodies
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
    covers: list[str] = Field(
        default_factory=list,
        description="coverage target ids from the scope manifest that this case hits",
    )

    @model_validator(mode="after")
    def _scenario_is_not_a_type(self):
        """'boundary'/'exception'/'normal' are scenarios (test design), not test types."""
        if self.type_tag in SCENARIO_TAGS:
            self.type_tag = "functional"
        return self


class WaiverDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: Annotated[str, Field(min_length=1, max_length=200)]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    requirement_code: str | None = None


class CasesOut(BaseModel):
    cases: list[CaseDraft] = Field(min_length=1)
    waivers: list[WaiverDraft] = Field(default_factory=list)


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


def coverage_errors(db, ctx: dict, out: CasesOut) -> list[str]:
    """Every manifest target is hit, or a person has confirmed a waiver. Agent waivers do not pass."""
    from testagent.services.case_scope import confirmed_waivers, record_agent_waivers
    from testagent.services.scope_manifest import case_covers_target, target_label

    scopes = (ctx.get("inputs") or {}).get("scopes") or []
    if not scopes:
        return []
    version_id = (ctx.get("inputs") or {}).get("version_id")
    with db.tx() as cur:
        if out.waivers and version_id:
            record_agent_waivers(cur, version_id, scopes, out.waivers)
        waived = confirmed_waivers(cur, scopes)
    proposed = {w.target_id for w in out.waivers}
    errors = []
    for scope in scopes:
        if scope.get("blocked"):
            continue
        req = scope.get("requirement") or {}
        code = req.get("code")
        mine = [c for c in out.cases if code in c.requirement_codes]
        allowed = waived.get((str(req.get("id")), scope.get("fingerprint")), set())
        for target in scope.get("targets") or []:
            if target["id"] in allowed or any(case_covers_target(target, c) for c in mine):
                continue
            label = target_label(target)
            if target["id"] in proposed:
                errors.append(
                    f"requirement {code} coverage target {target['id']} ({target['type']}: {label}) "
                    "has an agent waiver that does not count until a person confirms it"
                )
            else:
                errors.append(
                    f"requirement {code} coverage target {target['id']} ({target['type']}: {label}) is not covered"
                )
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
        errors += coverage_errors(db, ctx, out)
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
            "scenarios. The context lists one scope manifest per requirement (ids, names and "
            "coverage targets only). Do not assume objects that are not in that manifest. "
            "Read the requirement text and its structured refs with get_requirement. Read field "
            "types, enums, preconditions, effects, link cardinality and API schemas with the "
            "tools; a tool call for an id outside the manifest returns an error. Use only ids "
            "the tools return. Each case has a test point, concrete steps, test data, the "
            "expected result, the requirement codes it verifies, the model node ids and the "
            "entity field ids (attribute_ids) it exercises. When a step calls an API, write it "
            "as 'METHOD /path' and put the exact JSON request body in the step data: field "
            "names, types and units MUST follow get_api_schema, never invent fields. Put the "
            "key values (e.g. the amount) into test_data using the API field names. For every "
            "coverage target, at least one case must hit it and list that target id in covers. "
            "A field target needs that attribute_id. An action, precondition, effect or "
            "constraint target needs the action or entity in node_ids and the target id in "
            "covers. A link target needs an endpoint entity in node_ids and the target id in "
            "covers. "
            "Cover an in-scope action's precondition being met and each precondition being "
            "violated (expected refusal), and assert every effect. For an in-scope link, cover "
            "a missing foreign key (only a required link is a validation failure; an optional "
            "link may be absent), a foreign key pointing at a missing object, and the "
            "cardinality boundary named on the target (1:1 already taken, several objects on "
            "the N side). Avoid duplicating existing cases (list_cases). Give every case a "
            "category: requirement (the requirement's business rules, including input "
            "validation and error codes), quality (idempotency, concurrency/duplicate "
            "submission, repeatability and data reset; add quality_tags) or regression "
            "(main-path smoke). Boundary/exception are scenarios, never the type_tag."
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
        from testagent.services.case_scope import CaseScopeService

        scopes = CaseScopeService(self.db).for_generate(version_id, reqs, require_confirmed=True)
        run = self.runtime.run(
            "generate_cases",
            {
                "version_id": str(version_id),
                "sut_id": str(version["sut_id"]),
                "requirement_codes": [r["code"] for r in reqs],
                "requirements": [{"id": r["id"], "code": r["code"], "title": r["title"]} for r in reqs],
                "scopes": [s["manifest"] for s in scopes],
                "scope_ids": [s["id"] for s in scopes],
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

    def generate_e2e(self, version_id) -> dict:
        from testagent.services.case_chains import ChainService

        chains = ChainService(self.db).sync(version_id)
        if not chains:
            raise AppError("VALIDATION", "没有可以从动作效果和前置条件串起来的链路。")
        with self.db.tx() as cur:
            cur.execute("SELECT sut_id FROM version WHERE id=%s", (version_id,))
            version = cur.fetchone()
        scopes = ChainService(self.db).tool_scopes(version_id, chains)
        run = self.runtime.run(
            "generate_e2e_cases",
            {
                "version_id": str(version_id),
                "sut_id": str(version["sut_id"]),
                "chains": chains,
                "scopes": scopes,
                "requirement_codes": sorted({r["code"] for c in chains for r in c["requirements"]}),
            },
            sut_id=version["sut_id"],
        )
        summary = {
            "agent_run_id": str(run["id"]),
            "status": run["status"],
            "error_code": run["error_code"],
            "chains": chains,
        }
        if run["status"] != "succeeded":
            return summary
        out = CasesOut.model_validate(run["result"])
        codes = {r["code"]: r["id"] for c in chains for r in c["requirements"]}
        cases = CaseService(self.db, self.bus, actor=f"agent:{run['id']}")
        created = []
        with self.db.tx() as cur:
            for draft in out.cases:
                data = draft.model_dump(mode="json", exclude={"requirement_codes"})
                data["requirement_ids"] = [codes[c] for c in draft.requirement_codes if c in codes]
                data["origin_version_id"] = version_id
                row = cases.create(version["sut_id"], data, cur=cur, agent_run_id=run["id"])
                chain_id = _chain_for(draft, chains)
                if chain_id:
                    cur.execute("UPDATE test_case SET chain_id=%s WHERE id=%s", (chain_id, row["id"]))
                    row["chain_id"] = chain_id
                created.append({"id": str(row["id"]), "code": row["code"], "title": row["title"], "chain_id": chain_id})
            report = cases.save_coverage(version_id, cur=cur, agent_run_id=run["id"])
        return {**summary, "cases": created, "coverage": report["content"]}


def e2e_entry(db) -> Entry:
    def validate(out: CasesOut, ctx: dict) -> list[str]:
        chains = (ctx.get("inputs") or {}).get("chains") or []
        errors = []
        known_codes = {r["code"] for chain in chains for r in chain.get("requirements") or []}
        unknown = {c for d in out.cases for c in d.requirement_codes} - known_codes
        errors += [f"requirement code {c} is not on a chain" for c in sorted(unknown)]
        for chain in chains:
            action_ids = {a["id"] for a in chain["actions"]}
            codes = {r["code"] for r in chain["requirements"]}
            label = " → ".join(a["name"] for a in chain["actions"])
            mine = [c for c in out.cases if action_ids <= {str(n) for n in c.node_ids}]
            if not mine:
                errors.append(f"chain {label} needs a case whose node_ids include every action")
                continue
            if codes and not any(codes <= set(c.requirement_codes) for c in mine):
                errors.append(f"chain {label} needs a case linked to every requirement on the path")
            needed = {f"chain:{chain['id']}"} | {t["id"] for t in chain["transitions"]}
            covered = set()
            for case in mine:
                covered |= set(case.covers or [])
            missing = sorted(needed - covered)
            errors += [f"chain {label} coverage target {t} is not covered" for t in missing]
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
        name="generate_e2e_cases",
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
            "Write cross-requirement end-to-end cases for each chain in the context. A chain is a "
            "path of actions where one action's effect satisfies the next action's precondition. "
            "This is not a single requirement's scope and must not be produced by raising that "
            "depth. For each chain write at least one case that walks every action in order, "
            "links every requirement code on the path, puts every action id in node_ids, and "
            "lists covers for the chain id and each transition id. Assert the state named on "
            "each transition. Use the tools for field and API details; ids outside the chain "
            "scope are refused."
        ),
        validate=validate,
    )


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


def _chain_for(case: CaseDraft, chains: list[dict]) -> str | None:
    nodes = {str(n) for n in case.node_ids}
    match = [c for c in chains if {a["id"] for a in c["actions"]} <= nodes]
    if not match:
        return None
    match.sort(key=lambda c: len(c["actions"]), reverse=True)
    return match[0]["id"]
