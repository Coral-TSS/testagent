"""Test tasks: CRUD, ordered case lists, environment and schedule validation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from psycopg.types.json import Jsonb

from testagent.core.actor import current_actor
from testagent.core.config import DEFAULT_TIMEZONE
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.state import transition
from testagent.services.task_binding import (
    clean_selector,
    membership,
    require_scripts,
    rows,
    script_gaps,
    sync_task,
    write_rows,
)

EDITABLE = {"draft", "ready", "done", "cancelled"}


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AppError("VALIDATION", f"Unknown time zone: {name}", field_errors=[{"field": "schedule.tz"}]) from exc


def normalize_schedule(schedule: dict | None, default_tz: str = DEFAULT_TIMEZONE) -> dict | None:
    """Every stored schedule carries the IANA timezone it is evaluated in (default: config)."""
    if not schedule:
        return None
    out = {**schedule, "tz": schedule.get("tz") or default_tz}
    zone(out["tz"])
    return out


def next_run(schedule: dict | None, now: datetime | None = None, default_tz: str = DEFAULT_TIMEZONE) -> datetime | None:
    """Validate a schedule and compute its next fire time (UTC).
    once: {at with offset}; cron: {expr, tz}, fields are wall-clock time in tz."""
    if not schedule:
        return None
    now = now or datetime.now(UTC)
    tz = zone(schedule.get("tz") or default_tz)
    kind = schedule.get("type")
    if kind == "once":
        try:
            at = datetime.fromisoformat(str(schedule.get("at")))
        except ValueError as exc:
            raise AppError(
                "VALIDATION", "Invalid schedule time format", field_errors=[{"field": "schedule.at"}]
            ) from exc
        if at.tzinfo is None:
            raise AppError(
                "VALIDATION", "The schedule time must include a time zone", field_errors=[{"field": "schedule.at"}]
            )
        return at if at > now else None
    if kind == "cron":
        expr = str(schedule.get("expr") or "")
        if len(expr.split()) != 5 or not croniter.is_valid(expr):
            raise AppError(
                "VALIDATION",
                "Invalid cron expression (5 fields needed: minute hour day month weekday)",
                field_errors=[{"field": "schedule.expr", "msg": expr}],
            )
        local = croniter(expr, now.astimezone(tz)).get_next(datetime)
        return local.astimezone(UTC)
    raise AppError("VALIDATION", "schedule.type must be once or cron")


class TaskService:
    def __init__(self, db, bus: EventBus, actor: str | None = None, default_tz: str = DEFAULT_TIMEZONE):
        self.default_tz = default_tz
        self.db = db
        self.bus = bus
        self.actor = actor or current_actor()

    @staticmethod
    def _version(cur, version_id) -> dict:
        cur.execute("SELECT * FROM version WHERE id=%s", (version_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Version not found")
        return row

    @staticmethod
    def _task(cur, task_id, lock=False) -> dict:
        cur.execute(
            "SELECT t.*, v.sut_id FROM test_task t JOIN version v ON v.id=t.version_id"
            " WHERE t.id=%s" + (" FOR UPDATE OF t" if lock else ""),
            (task_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Task not found")
        return row

    @staticmethod
    def _check_env(cur, environment_id, sut_id) -> None:
        if environment_id is None:
            return
        cur.execute("SELECT sut_id FROM environment WHERE id=%s", (environment_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Environment not found")
        if str(row["sut_id"]) != str(sut_id):
            raise AppError("VALIDATION", "The environment does not belong to this SUT")

    def _set_cases(self, cur, task: dict, case_ids: list) -> None:
        """A person sets the case list: kept rows keep their origin, new rows are manual, and
        removed rows are remembered so rules never put them back (manual wins)."""
        ordered = [str(c) for c in case_ids]
        if len(set(ordered)) != len(ordered):
            raise AppError("VALIDATION", "Duplicate case")
        if ordered:
            cur.execute(
                "SELECT id::text AS id, sut_id, status FROM test_case WHERE id = ANY(%s::uuid[])",
                (ordered,),
            )
            found = {r["id"]: r for r in cur.fetchall()}
            missing = [c for c in ordered if c not in found]
            if missing:
                raise AppError("NOT_FOUND", "Test case not found", related=missing)
            if any(str(r["sut_id"]) != str(task["sut_id"]) for r in found.values()):
                raise AppError("VALIDATION", "The case does not belong to this SUT")
            deprecated = [c for c in ordered if found[c]["status"] == "deprecated"]
            if deprecated:
                raise AppError("VALIDATION", "Deprecated cases cannot be added to a task", related=deprecated)
        before = {r["case_id"]: r for r in rows(cur, task["id"])}
        new_rows = [before.get(c) or {"case_id": c, "source": "manual", "reason": "Added manually"} for c in ordered]
        write_rows(cur, task["id"], new_rows)
        for case_id in set(before) - set(ordered):
            cur.execute(
                "INSERT INTO task_case_exclusion(task_id, case_id, removed_by) VALUES (%s,%s,%s)"
                " ON CONFLICT DO NOTHING",
                (task["id"], case_id, self.actor),
            )
        if ordered:
            cur.execute(
                "DELETE FROM task_case_exclusion WHERE task_id=%s AND case_id = ANY(%s::uuid[])",
                (task["id"], ordered),
            )

    def _detail(self, cur, task_id) -> dict:
        task = self._task(cur, task_id)
        cur.execute(
            "SELECT tc.seq, c.id, c.code, c.title, c.status, c.mode, c.type_tag, c.priority,"
            " c.category, tc.source, tc.reason, tc.added_at FROM task_case tc"
            " JOIN test_case c ON c.id=tc.case_id WHERE tc.task_id=%s ORDER BY tc.seq",
            (task_id,),
        )
        task["cases"] = cur.fetchall()
        task.update(membership(cur, task_id))
        task["script_gaps"] = script_gaps(cur, task_id)
        cur.execute("SELECT name FROM version WHERE id=%s", (task["version_id"],))
        version = cur.fetchone()
        task["version_name"] = version["name"] if version else None
        return task

    def create(self, version_id, data: dict[str, Any], *, cur=None, agent_run_id=None) -> dict:
        if cur is None:
            with self.db.tx() as c:
                row = self.create(version_id, data, cur=c, agent_run_id=agent_run_id)
            self.bus.publish("test_task.created", {"id": str(row["id"])})
            return row
        version = self._version(cur, version_id)
        if version["status"] == "closed":
            raise AppError("CONFLICT", "The version is closed")
        self._check_env(cur, data.get("environment_id"), version["sut_id"])
        schedule = normalize_schedule(data.get("schedule"), self.default_tz)
        selector = clean_selector(cur, data.get("selector"), version["sut_id"])
        cur.execute(
            "INSERT INTO test_task(version_id, strategy_id, name, kind, executor, environment_id,"
            " schedule, next_run_at, description, requirement_ids, source, agent_run_id, selector)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                version_id,
                data.get("strategy_id"),
                data["name"],
                data.get("kind", "requirement"),
                data.get("executor", "agent"),
                data.get("environment_id"),
                Jsonb(schedule) if schedule else None,
                next_run(schedule),
                data.get("description"),
                Jsonb([str(r) for r in data.get("requirement_ids") or []]),
                "agent" if agent_run_id else "human",
                agent_run_id,
                Jsonb(selector) if selector is not None else None,
            ),
        )
        task_id = cur.fetchone()["id"]
        task = self._task(cur, task_id)
        if data.get("case_ids"):
            self._set_cases(cur, task, data["case_ids"])
        sync_task(cur, task, self.actor)
        log_change(cur, "test_task", task_id, "create", self.actor, data)
        return self._detail(cur, task_id)

    def list(self, version_id) -> list[dict]:
        with self.db.tx() as cur:
            self._version(cur, version_id)
            cur.execute(
                "SELECT t.*, (SELECT count(*) FROM task_case tc WHERE tc.task_id=t.id)"
                " AS case_count FROM test_task t WHERE version_id=%s ORDER BY created_at, name",
                (version_id,),
            )
            rows = cur.fetchall()
            for row in rows:
                row["script_gap_count"] = len(script_gaps(cur, row["id"])) if row["executor"] == "automation" else 0
            return rows

    def get(self, task_id) -> dict:
        with self.db.tx() as cur:
            return self._detail(cur, task_id)

    def update(self, task_id, data: dict[str, Any]) -> dict:
        with self.db.tx() as cur:
            task = self._task(cur, task_id, lock=True)
            if task["status"] not in EDITABLE:
                raise AppError("CONFLICT", "The task is running or archived and cannot be modified")
            allowed = ("name", "kind", "executor", "environment_id", "description", "schedule")
            values = {k: v for k, v in data.items() if k in allowed}
            if "environment_id" in values:
                self._check_env(cur, values["environment_id"], task["sut_id"])
            if "schedule" in values:
                values["schedule"] = normalize_schedule(values["schedule"], self.default_tz)
                values["next_run_at"] = next_run(values["schedule"])
                values["schedule"] = Jsonb(values["schedule"]) if values["schedule"] else None
            if values:
                sets = ", ".join(f"{k}=%s" for k in values)
                cur.execute(f"UPDATE test_task SET {sets} WHERE id=%s", (*values.values(), task_id))
            if "case_ids" in data:
                self._set_cases(cur, task, data["case_ids"])
            log_change(cur, "test_task", task_id, "update", self.actor, data)
            row = self._detail(cur, task_id)
        self.bus.publish("test_task.updated", {"id": str(task_id)})
        return row

    def set_cases(self, task_id, case_ids: list) -> dict:
        return self.update(task_id, {"case_ids": case_ids})

    def set_status(self, task_id, target: str, *, allow_missing_scripts: bool = False) -> dict:
        if target not in ("draft", "ready", "archived"):
            raise AppError("VALIDATION", "Only draft / ready / archived can be set manually")
        with self.db.tx() as cur:
            task = self._task(cur, task_id, lock=True)
            transition("task", task["status"], target)
            if target == "ready":
                cur.execute("SELECT count(*) AS n FROM task_case WHERE task_id=%s", (task_id,))
                if cur.fetchone()["n"] == 0:
                    raise AppError("VALIDATION", "The task has no cases and cannot be set ready")
                if not allow_missing_scripts:
                    require_scripts(cur, task_id)
            cur.execute("UPDATE test_task SET status=%s WHERE id=%s", (target, task_id))
            log_change(cur, "test_task", task_id, "status", self.actor, {"status": target})
            row = self._detail(cur, task_id)
        self.bus.publish(f"test_task.{target}", {"id": str(task_id)})
        return row

    def delete(self, task_id) -> None:
        with self.db.tx() as cur:
            task = self._task(cur, task_id, lock=True)
            if task["status"] == "running":
                raise AppError("CONFLICT", "The task is running and cannot be deleted")
            cur.execute("SELECT 1 FROM task_run WHERE task_id=%s LIMIT 1", (task_id,))
            if cur.fetchone():
                raise AppError("CONFLICT", "The task has executions; archive it instead of deleting")
            cur.execute("DELETE FROM test_task WHERE id=%s", (task_id,))
            log_change(cur, "test_task", task_id, "delete", self.actor)
        self.bus.publish("test_task.deleted", {"id": str(task_id)})
