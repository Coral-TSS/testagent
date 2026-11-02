"""M1-12 self-improvement loop (architecture §4.4, D12/C09, BR-10):
raw corrections are stored verbatim → the `digest_correction` agent turns them into memories
and/or new prompt versions that take effect immediately (no review) → active memories and
prompts are injected into later agent runs (prompts.assemble records what was injected).
Skills / MCP servers are registered only (C07): nothing is loaded or executed."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from testagent.agent.prompts import DEFAULT_SYSTEM
from testagent.agent.runtime import Entry
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human

log = logging.getLogger("testagent.learning")

DIGEST_JOB = "digest_correction"
SYSTEM_PROMPT = "system"

# target_type → (sut_id/label SQL, kind default). Every query takes the target id once.
_REPORT_SUT = (
    "COALESCE((SELECT v.sut_id FROM version v WHERE r.scope_type='version' AND v.id=r.scope_id),"
    " (SELECT v.sut_id FROM task_run tr JOIN test_task t ON t.id=tr.task_id"
    "  JOIN version v ON v.id=t.version_id WHERE r.scope_type='task_run' AND tr.id=r.scope_id))"
)
TARGETS: dict[str, tuple[str, str, str]] = {
    "case": (
        "test_case",
        "SELECT sut_id, 'Case ' || code || ' ' || title AS label FROM test_case WHERE id=%s",
        "correction",
    ),
    "strategy": (
        "test_strategy",
        "SELECT v.sut_id, 'Version ' || v.name || '  test strategy' AS label FROM test_strategy s"
        " JOIN version v ON v.id=s.version_id WHERE s.id=%s",
        "correction",
    ),
    "requirement": (
        "requirement",
        "SELECT v.sut_id, 'Requirement ' || r.code || ' ' || r.title AS label FROM requirement r"
        " JOIN version v ON v.id=r.version_id WHERE r.id=%s",
        "correction",
    ),
    "execution": (
        "case_execution",
        "SELECT c.sut_id, 'Case ' || c.code || '  execution' AS label FROM case_execution e"
        " JOIN test_case c ON c.id=e.case_id WHERE e.id=%s",
        "correction",
    ),
    "report": (
        "report",
        f"SELECT {_REPORT_SUT} AS sut_id, CASE r.scope_type WHEN 'version' THEN 'Version report'"
        " ELSE 'Task report' END AS label FROM report r WHERE r.id=%s",
        "correction",
    ),
    "agent_run": (
        "agent_run",
        "SELECT sut_id, 'Agent run ' || purpose AS label FROM agent_run WHERE id=%s",
        "correction",
    ),
    "task_run": (
        "task_run",
        "SELECT v.sut_id, 'Task ' || t.name || '  run' AS label FROM task_run tr"
        " JOIN test_task t ON t.id=tr.task_id JOIN version v ON v.id=t.version_id WHERE tr.id=%s",
        "omission",
    ),
    "version": (
        "version",
        "SELECT sut_id, 'Version ' || name AS label FROM version WHERE id=%s",
        "correction",
    ),
}
TARGET_TYPES = tuple(TARGETS)
SNAPSHOT_CHARS = 6000


# ------------------------------------------------------------------ digest entry
class MemoryDraft(BaseModel):
    scope: Literal["global", "sut"] = Field(description="sut: only for this system; global: applies everywhere")
    content: str = Field(min_length=1, max_length=1000, description="one actionable lesson")
    tags: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="agent entry names this lesson applies to; empty = all entries",
    )


class PromptPatch(BaseModel):
    name: str = Field(description="'system' or an agent entry name")
    append_text: str = Field(min_length=1, max_length=2000)


class DigestOut(BaseModel):
    memories: list[MemoryDraft] = Field(default_factory=list, max_length=10)
    prompt_patches: list[PromptPatch] = Field(default_factory=list, max_length=5)


def digest_entry() -> Entry:
    def validate(out: DigestOut, ctx: dict) -> list[str]:
        inputs = ctx["inputs"]
        entries, prompts = set(inputs["entries"]), set(inputs["prompt_names"])
        errors = []
        if not out.memories and not out.prompt_patches:
            errors.append("produce at least one memory or prompt patch")
        for m in out.memories:
            errors += [f"unknown tag {t}; use one of {sorted(entries)}" for t in m.tags if t not in entries]
            if m.scope == "sut" and not ctx.get("sut_id"):
                errors.append("scope 'sut' needs a correction that belongs to a system")
        errors += [
            f"unknown prompt name {p.name}; use one of {sorted(prompts)}"
            for p in out.prompt_patches
            if p.name not in prompts
        ]
        return errors

    return Entry(
        name="digest_correction",
        output_schema=DigestOut,
        tools=("search_memory",),
        instructions=(
            "A tester corrected the agent's work. Input: the raw correction text, what it targets"
            " (a snapshot of the object), the agent entry names and prompt names. Turn it into"
            " durable guidance: short memories (one lesson each, tagged with the entries they"
            " apply to; scope 'sut' when specific to this system) and/or prompt_patches that"
            " append a general rule to a prompt. Check search_memory to avoid duplicates. Keep"
            " the tester's intent; do not invent requirements; never judge people."
        ),
        validate=validate,
    )


def _jsonable(value) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


# ------------------------------------------------------------------ prompts
class PromptService:
    def __init__(self, db, names: list[str], actor: str = "local-user"):
        self.db = db
        self.names = [SYSTEM_PROMPT, *sorted(n for n in names if n != SYSTEM_PROMPT)]
        self.actor = actor

    def _check(self, name: str) -> None:
        if name not in self.names:
            raise AppError(
                "VALIDATION",
                f"Unknown prompt: {name}",
                field_errors=[{"field": "name", "msg": name}],
            )

    @staticmethod
    def baseline(name: str) -> str:
        return DEFAULT_SYSTEM if name == SYSTEM_PROMPT else ""

    def list(self) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT name, max(version) AS versions, max(version) FILTER (WHERE active)"
                " AS active_version, max(created_at) AS updated_at FROM prompt_template"
                " GROUP BY name"
            )
            rows = {r["name"]: r for r in cur.fetchall()}
            cur.execute("SELECT name, content FROM prompt_template WHERE active")
            active = {r["name"]: r["content"] for r in cur.fetchall()}
        out = []
        for name in self.names:
            r = rows.get(name) or {}
            out.append(
                {
                    "name": name,
                    "kind": "system" if name == SYSTEM_PROMPT else "entry",
                    "versions": r.get("versions") or 0,
                    "active_version": r.get("active_version"),
                    "updated_at": r.get("updated_at"),
                    "content": active.get(name, self.baseline(name)),
                    "is_default": name not in active,
                }
            )
        return out

    def versions(self, name: str) -> list[dict]:
        self._check(name)
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM prompt_template WHERE name=%s ORDER BY version DESC", (name,))
            return cur.fetchall()

    def _ensure_baseline(self, cur, name: str) -> None:
        cur.execute("SELECT 1 FROM prompt_template WHERE name=%s LIMIT 1", (name,))
        if cur.fetchone() is None:  # keep the built-in default as v1 so it can be rolled back to
            cur.execute(
                "INSERT INTO prompt_template(name, version, content, active, created_by, note)"
                " VALUES (%s, 1, %s, false, 'system', 'Built-in default')",
                (name, self.baseline(name)),
            )

    def _active_content(self, cur, name: str) -> str:
        cur.execute("SELECT content FROM prompt_template WHERE name=%s AND active", (name,))
        row = cur.fetchone()
        if row:
            return row["content"]
        cur.execute("SELECT content FROM prompt_template WHERE name=%s ORDER BY version LIMIT 1", (name,))
        row = cur.fetchone()
        return row["content"] if row else self.baseline(name)

    def add_version(
        self,
        cur,
        name: str,
        content: str,
        *,
        actor: str,
        note: str | None = None,
        sources: list[str] | None = None,
        agent_run_id=None,
    ) -> dict:
        self._check(name)
        self._ensure_baseline(cur, name)
        cur.execute("SELECT max(version) AS v FROM prompt_template WHERE name=%s", (name,))
        version = cur.fetchone()["v"] + 1
        cur.execute("UPDATE prompt_template SET active=false WHERE name=%s AND active", (name,))
        cur.execute(
            "INSERT INTO prompt_template(name, version, content, active, source_correction_ids,"
            " created_by, note, agent_run_id) VALUES (%s,%s,%s,true,%s,%s,%s,%s) RETURNING *",
            (name, version, content, Jsonb(sources or []), actor, note, agent_run_id),
        )
        row = cur.fetchone()
        log_change(cur, "prompt_template", row["id"], "create", actor, {"name": name, "v": version})
        return row

    def patch(self, cur, name: str, append_text: str, *, actor, sources, agent_run_id) -> dict:
        self._check(name)
        self._ensure_baseline(cur, name)
        current = self._active_content(cur, name).rstrip()
        content = f"{current}\n\n{append_text.strip()}" if current else append_text.strip()
        return self.add_version(
            cur,
            name,
            content,
            actor=actor,
            note="Generated from corrections",
            sources=sources,
            agent_run_id=agent_run_id,
        )

    def create(self, name: str, content: str, note: str | None) -> dict:
        ensure_human(self.actor, "Change prompt")
        with self.db.tx() as cur:
            return self.add_version(cur, name, content, actor=self.actor, note=note)

    def activate(self, name: str, version: int) -> dict:
        ensure_human(self.actor, "Roll back prompt")
        self._check(name)
        with self.db.tx() as cur:
            cur.execute("SELECT id FROM prompt_template WHERE name=%s AND version=%s", (name, version))
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", f"Prompt {name} has no version {version}")
            cur.execute("UPDATE prompt_template SET active=false WHERE name=%s AND active", (name,))
            cur.execute("UPDATE prompt_template SET active=true WHERE id=%s RETURNING *", (row["id"],))
            out = cur.fetchone()
            log_change(cur, "prompt_template", row["id"], "activate", self.actor, {"v": version})
            return out


# ------------------------------------------------------------------ memories
class MemoryService:
    def __init__(self, db, actor: str = "local-user"):
        self.db = db
        self.actor = actor

    def list(self, scope=None, sut_id=None, enabled=None) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT m.*, s.code AS sut_code FROM agent_memory m"
                " LEFT JOIN sut s ON s.id=m.sut_id"
                " WHERE (%(scope)s::text IS NULL OR m.scope=%(scope)s)"
                " AND (%(sut)s::uuid IS NULL OR m.sut_id=%(sut)s::uuid)"
                " AND (%(en)s::boolean IS NULL OR m.enabled=%(en)s)"
                " ORDER BY m.created_at DESC LIMIT 500",
                {"scope": scope, "sut": sut_id, "en": enabled},
            )
            return cur.fetchall()

    def set_enabled(self, memory_id, enabled: bool) -> dict:
        ensure_human(self.actor, "Disable memory")
        with self.db.tx() as cur:
            cur.execute("UPDATE agent_memory SET enabled=%s WHERE id=%s RETURNING *", (enabled, memory_id))
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", "Memory not found")
            log_change(cur, "agent_memory", memory_id, "update", self.actor, {"enabled": enabled})
            return row


# ------------------------------------------------------------------ corrections
class CorrectionService:
    """Raw corrections (US-18). Text is stored byte-for-byte; digesting happens in a job."""

    def __init__(self, db, bus: EventBus, actor: str = "local-user"):
        self.db = db
        self.bus = bus
        self.actor = actor

    @staticmethod
    def resolve(cur, target_type: str, target_id) -> dict:
        spec = TARGETS.get(target_type)
        if spec is None:
            raise AppError("VALIDATION", f"Unsupported correction target: {target_type}")
        cur.execute(spec[1], (target_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Correction target not found")
        return row

    def create(self, target_type: str, target_id, content: str, kind: str | None = None) -> dict:
        ensure_human(self.actor, "Submit correction")
        if not content.strip():
            raise AppError("VALIDATION", "Correction text cannot be empty", field_errors=[{"field": "content"}])
        with self.db.tx() as cur:
            target = self.resolve(cur, target_type, target_id)
            cur.execute(
                "INSERT INTO correction(target_type, target_id, content, author, sut_id, kind)"
                " VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    target_type,
                    target_id,
                    content,
                    self.actor,
                    target["sut_id"],
                    kind or TARGETS[target_type][2],
                ),
            )
            row = cur.fetchone()
            log_change(cur, "correction", row["id"], "create", self.actor, {"target": target_type})
        self.bus.publish(
            "correction.created",
            {"id": str(row["id"]), "target_type": target_type, "target_id": str(target_id)},
        )
        return {**row, "target_label": target["label"]}

    def get(self, correction_id) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM correction WHERE id=%s", (correction_id,))
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", "Correction not found")
            try:
                label = self.resolve(cur, row["target_type"], row["target_id"])["label"]
            except AppError:
                label = None
        return {**row, "target_label": label}

    def list(self, target_type=None, target_id=None, status=None, kind=None, sut_id=None):
        with self.db.tx() as cur:
            cur.execute(
                "SELECT c.*, s.code AS sut_code FROM correction c LEFT JOIN sut s ON s.id=c.sut_id"
                " WHERE (%(tt)s::text IS NULL OR c.target_type=%(tt)s)"
                " AND (%(ti)s::uuid IS NULL OR c.target_id=%(ti)s::uuid)"
                " AND (%(st)s::text IS NULL OR c.status=%(st)s)"
                " AND (%(k)s::text IS NULL OR c.kind=%(k)s)"
                " AND (%(s)s::uuid IS NULL OR c.sut_id=%(s)s::uuid)"
                " ORDER BY c.created_at DESC LIMIT 200",
                {"tt": target_type, "ti": target_id, "st": status, "k": kind, "s": sut_id},
            )
            rows = cur.fetchall()
            for r in rows:
                try:
                    r["target_label"] = self.resolve(cur, r["target_type"], r["target_id"])["label"]
                except AppError:
                    r["target_label"] = None
            return rows

    def reprocess(self, correction_id) -> dict:
        """C09: digest again (e.g. after a failure or once a model is configured)."""
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE correction SET status='pending' WHERE id=%s AND status <> 'processing' RETURNING id",
                (correction_id,),
            )
            if cur.fetchone() is None:
                cur.execute("SELECT 1 FROM correction WHERE id=%s", (correction_id,))
                if cur.fetchone() is None:
                    raise AppError("NOT_FOUND", "Correction not found")
                raise AppError("CONFLICT", "Being processed; try again later")
        self.bus.publish("correction.reprocess", {"id": str(correction_id)})
        return self.get(correction_id)


class DigestService:
    def __init__(self, db, bus: EventBus, runtime):
        self.db = db
        self.bus = bus
        self.runtime = runtime

    def _snapshot(self, cur, target_type: str, target_id) -> Any:
        table = TARGETS[target_type][0]
        cur.execute(f"SELECT to_jsonb(t) AS row FROM {table} t WHERE id=%s", (target_id,))  # noqa: S608
        row = cur.fetchone()
        text = json.dumps(row["row"] if row else None, ensure_ascii=False, default=str)
        return text[:SNAPSHOT_CHARS]

    def _fail(self, correction_id, error: str, agent_run_id=None) -> None:
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE correction SET status='failed', error=%s, agent_run_id=COALESCE(%s, agent_run_id) WHERE id=%s",
                (error[:2000], agent_run_id, correction_id),
            )
        self.bus.publish("correction.failed", {"id": str(correction_id)})

    def digest(self, correction_id) -> dict:
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE correction SET status='processing', attempts=attempts+1, error=NULL"
                " WHERE id=%s AND status='pending' RETURNING *",
                (correction_id,),
            )
            corr = cur.fetchone()
            if corr is None:
                return {"skipped": True}
            target = CorrectionService.resolve(cur, corr["target_type"], corr["target_id"])
            snapshot = self._snapshot(cur, corr["target_type"], corr["target_id"])
        entries = sorted(n for n in self.runtime.entries if n != "digest_correction")
        prompts = PromptService(self.db, entries)
        try:
            self.runtime.models.create()
            run = self.runtime.run(
                "digest_correction",
                {
                    "correction": {
                        "id": str(corr["id"]),
                        "kind": corr["kind"],
                        "target_type": corr["target_type"],
                        "target": target["label"],
                        "content": corr["content"],
                    },
                    "target_snapshot": snapshot,
                    "entries": entries,
                    "prompt_names": prompts.names,
                },
                sut_id=corr["sut_id"],
            )
        except AppError as exc:
            self._fail(correction_id, f"{exc.code}: {exc.message}")
            return {"status": "failed"}
        except Exception as exc:  # never lose the correction; it stays retryable
            log.exception("digest_correction crashed")
            self._fail(correction_id, f"{type(exc).__name__}: {exc}")
            return {"status": "failed"}
        if run["status"] != "succeeded":
            self._fail(correction_id, f"{run.get('error_code')}: {run.get('error')}", run["id"])
            return {"status": "failed", "agent_run_id": str(run["id"])}
        out = DigestOut.model_validate(run["result"])
        actor = f"agent:{run['id']}"
        source = [str(corr["id"])]
        with self.db.tx() as cur:
            memory_ids = []
            for m in out.memories:
                scope = m.scope if corr["sut_id"] else "global"
                cur.execute(
                    "INSERT INTO agent_memory(scope, sut_id, content, tags, source_correction_ids,"
                    " created_by, agent_run_id) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (
                        scope,
                        corr["sut_id"] if scope == "sut" else None,
                        m.content,
                        Jsonb(m.tags),
                        Jsonb(source),
                        actor,
                        run["id"],
                    ),
                )
                memory_ids.append(str(cur.fetchone()["id"]))
            versions = []
            for p in out.prompt_patches:
                row = prompts.patch(cur, p.name, p.append_text, actor=actor, sources=source, agent_run_id=run["id"])
                versions.append({"name": p.name, "version": row["version"], "id": str(row["id"])})
            outputs = {"memory_ids": memory_ids, "prompt_versions": versions}
            cur.execute(
                "UPDATE correction SET status='processed', processed_at=now(), error=NULL,"
                " agent_run_id=%s, outputs=%s WHERE id=%s",
                (run["id"], Jsonb(outputs), correction_id),
            )
        self.bus.publish("correction.processed", {"id": str(correction_id), **outputs})
        return {"status": "processed", **outputs}


# ------------------------------------------------------------------ skills / MCP (C07)
class RegistryOnlyService:
    """Skills and MCP servers are recorded and can be disabled; M1 never loads them."""

    TABLES = {
        "skill": ("name", "description", "content", "source", "enabled"),
        "mcp_server": ("name", "transport", "command", "url", "description", "enabled"),
    }

    def __init__(self, db, table: str, actor: str = "local-user"):
        self.db = db
        self.table = table
        self.fields = self.TABLES[table]
        self.actor = actor

    def list(self) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(f"SELECT * FROM {self.table} ORDER BY name")  # noqa: S608
            return cur.fetchall()

    def create(self, data: dict) -> dict:
        ensure_human(self.actor, "Register skill/MCP")
        values = {k: v for k, v in data.items() if k in self.fields and v is not None}
        cols = ", ".join(values)
        marks = ", ".join(["%s"] * len(values))
        with self.db.tx() as cur:
            cur.execute(
                f"INSERT INTO {self.table}({cols}) VALUES ({marks}) RETURNING *",  # noqa: S608
                tuple(values.values()),
            )
            row = cur.fetchone()
            log_change(cur, self.table, row["id"], "create", self.actor, _jsonable(values))
            return row

    def update(self, item_id, data: dict) -> dict:
        ensure_human(self.actor, "Change skill/MCP")
        values = {k: v for k, v in data.items() if k in self.fields}
        with self.db.tx() as cur:
            if values:
                sets = ", ".join(f"{k}=%s" for k in values)
                cur.execute(
                    f"UPDATE {self.table} SET {sets} WHERE id=%s",  # noqa: S608
                    (*values.values(), item_id),
                )
            cur.execute(f"SELECT * FROM {self.table} WHERE id=%s", (item_id,))  # noqa: S608
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", "Record not found")
            log_change(cur, self.table, item_id, "update", self.actor, _jsonable(values))
            return row
