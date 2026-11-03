"""Test strategy per version (draft/confirmed with revision) and AI generation of a task set."""

from __future__ import annotations

from typing import Annotated, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from testagent.agent.runtime import AgentRuntime, Entry
from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human
from testagent.services.state import transition
from testagent.services.task_binding import TaskBindingService, version_gaps

FUNCTIONAL = "functional"
Intensity = Literal["light", "standard", "thorough"]
Tag = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]


class TaskDraft(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    kind: Literal["requirement", "quality", "regression"] = "requirement"
    executor: Literal["agent", "automation", "human"] = "agent"
    type_tag: Tag = FUNCTIONAL
    requirement_codes: list[str] = Field(default_factory=list)
    description: str | None = None


class StrategyOut(BaseModel):
    scope: Annotated[str, Field(min_length=1)]
    test_types: list[Tag] = Field(min_length=1)
    intensity: Intensity
    notes: str | None = None
    tasks: list[TaskDraft] = Field(default_factory=list)


def strategy_entry(db) -> Entry:
    def validate(out: StrategyOut, ctx: dict) -> list[str]:
        version_id = ctx["inputs"]["version_id"]
        codes = {c for t in out.tasks for c in t.requirement_codes}
        if not codes:
            return []
        with db.tx() as cur:
            cur.execute(
                "SELECT code FROM requirement WHERE version_id=%s AND code = ANY(%s)",
                (version_id, list(codes)),
            )
            known = {r["code"] for r in cur.fetchall()}
        return [f"requirement code {c} does not exist in this version" for c in sorted(codes - known)]

    return Entry(
        name="generate_strategy",
        output_schema=StrategyOut,
        tools=(
            "list_requirements",
            "get_requirement",
            "get_requirement_people",
            "list_nodes",
            "list_apis",
            "search_memory",
        ),
        instructions=(
            "Propose a test strategy for the frozen version: scope, test type tags, intensity "
            "and notes. Only functional testing is executed in this platform; other types "
            "(performance, security, ...) may be listed as tags but get no executable tasks. "
            "Tasks are built by the platform from rules over the existing test cases: one "
            "requirement task per requirement (kind=requirement; its normal/boundary/exception and "
            "input-validation cases), one quality task (kind=quality: idempotency, concurrency, "
            "repeatability/data reset) and one regression/smoke task (kind=regression: P0 cases). Use "
            "`tasks` only to say which executor (agent/automation/human) suits a requirement "
            "(reference it by requirement code) or the quality/regression task; names and "
            "descriptions you give are ignored. Do not write test steps into the strategy."
        ),
        validate=validate,
    )


class StrategyService:
    def __init__(self, db, bus: EventBus, actor: str | None = None):
        self.db = db
        self.bus = bus
        self.actor = actor or current_actor()

    @staticmethod
    def _version(cur, version_id, lock=False) -> dict:
        cur.execute("SELECT * FROM version WHERE id=%s" + (" FOR UPDATE" if lock else ""), (version_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Version not found")
        if row["status"] == "planning":
            raise AppError("CONFLICT", "Freeze the version's requirements before creating a test strategy")
        if row["status"] == "closed":
            raise AppError("CONFLICT", "The version is closed")
        return row

    def get(self, version_id) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM test_strategy WHERE version_id=%s", (version_id,))
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", "This version has no test strategy yet")
            cur.execute(
                "SELECT t.id, t.name, t.kind, t.executor, t.status, t.requirement_ids, t.selector,"
                " (SELECT count(*) FROM task_case tc WHERE tc.task_id=t.id) AS case_count"
                " FROM test_task t WHERE t.strategy_id=%s ORDER BY t.created_at, t.name",
                (row["id"],),
            )
            row["tasks"] = cur.fetchall()
            row["gaps"] = version_gaps(cur, version_id)
            return row

    @staticmethod
    def strategy_id(db, version_id):
        with db.tx() as cur:
            cur.execute("SELECT id FROM test_strategy WHERE version_id=%s", (version_id,))
            row = cur.fetchone()
        return row["id"] if row else None

    def _upsert(self, cur, version: dict, values: dict, *, agent_run_id=None) -> dict:
        cur.execute("SELECT * FROM test_strategy WHERE version_id=%s FOR UPDATE", (version["id"],))
        current = cur.fetchone()
        fields = {
            "scope": values.get("scope"),
            "test_types": Jsonb(values.get("test_types") or []),
            "intensity": values.get("intensity"),
            "notes": values.get("notes"),
            "source": "agent" if agent_run_id else "human",
            "agent_run_id": agent_run_id,
            "snapshot_id": version["model_snapshot_id"],
        }
        if current is None:
            cols = ", ".join(fields)
            cur.execute(
                f"INSERT INTO test_strategy(version_id, {cols}) VALUES (%s, "
                + ", ".join(["%s"] * len(fields))
                + ") RETURNING *",
                (version["id"], *fields.values()),
            )
            return cur.fetchone()
        if current["status"] == "confirmed":  # any edit after confirmation reopens a draft
            transition("strategy", "confirmed", "draft")
        sets = ", ".join(f"{k}=%s" for k in fields)
        cur.execute(
            f"UPDATE test_strategy SET {sets}, status='draft', revision=revision+1,"
            " confirmed_at=NULL, confirmed_by=NULL WHERE id=%s RETURNING *",
            (*fields.values(), current["id"]),
        )
        return cur.fetchone()

    def save(self, version_id, values: dict) -> dict:
        with self.db.tx() as cur:
            version = self._version(cur, version_id, lock=True)
            row = self._upsert(cur, version, values)
            log_change(cur, "test_strategy", row["id"], "save", self.actor, values)
        self.bus.publish("strategy.saved", {"id": str(row["id"])})
        return self.get(version_id)

    def confirm(self, strategy_id) -> dict:
        ensure_human(self.actor, "Confirm test strategy")
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM test_strategy WHERE id=%s FOR UPDATE", (strategy_id,))
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", "Test strategy not found")
            transition("strategy", row["status"], "confirmed")
            cur.execute(
                "UPDATE test_strategy SET status='confirmed', confirmed_at=now(), confirmed_by=%s WHERE id=%s",
                (self.actor, strategy_id),
            )
            log_change(cur, "test_strategy", strategy_id, "confirm", self.actor)
        self.bus.publish("strategy.confirmed", {"id": str(strategy_id)})
        return self.get(row["version_id"])

    def generate(self, version_id, runtime: AgentRuntime) -> dict:
        with self.db.tx() as cur:
            version = self._version(cur, version_id)
        run = runtime.run(
            "generate_strategy",
            {"version_id": str(version_id), "version": version["name"]},
            sut_id=version["sut_id"],
        )
        summary = {
            "agent_run_id": str(run["id"]),
            "status": run["status"],
            "error_code": run["error_code"],
        }
        if run["status"] != "succeeded":
            return summary
        out = StrategyOut.model_validate(run["result"])
        actor = f"agent:{run['id']}"
        tag_only = [d.type_tag for d in out.tasks if d.type_tag != FUNCTIONAL]
        hints: dict[str, str] = {}
        for draft in out.tasks:
            if draft.type_tag != FUNCTIONAL:
                continue
            keys = draft.requirement_codes if draft.kind == "requirement" else [draft.kind]
            for key in keys:
                hints.setdefault(key, draft.executor)
        with self.db.tx() as cur:
            version = self._version(cur, version_id, lock=True)
            strategy = self._upsert(cur, version, out.model_dump(exclude={"tasks"}), agent_run_id=run["id"])
            # earlier free-text drafts nobody touched are replaced by rule tasks
            cur.execute(
                "DELETE FROM test_task t WHERE strategy_id=%s AND source='agent' AND status='draft'"
                " AND selector IS NULL"
                " AND NOT EXISTS (SELECT 1 FROM task_case tc WHERE tc.task_id=t.id)"
                " AND NOT EXISTS (SELECT 1 FROM task_run r WHERE r.task_id=t.id)",
                (strategy["id"],),
            )
            created = TaskBindingService(self.db, self.bus, actor=actor).ensure_tasks(
                version_id,
                cur=cur,
                strategy_id=strategy["id"],
                executor_hints=hints,
                agent_run_id=run["id"],
            )
            log_change(
                cur,
                "test_strategy",
                strategy["id"],
                "generate",
                actor,
                {"tasks": len(created), "tag_only": tag_only},
            )
        self.bus.publish("strategy.generated", {"id": str(strategy["id"])})
        return {
            **summary,
            "strategy": self.get(version_id),
            "created_tasks": created,
            "tag_only_types": sorted(set(tag_only)),
        }
