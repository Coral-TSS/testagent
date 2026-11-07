"""Task ↔ case binding.

Tasks only *reference* cases. A task may carry a selection rule (`selector`); its case list is
the rule's matches plus cases a person added by hand. Manual always wins: a case a person took
out is remembered in `task_case_exclusion` and never put back by a rule, and a case a person put
in stays even when the rule does not match it. A case that becomes executable (or changes) is
reconciled against every live rule task of its system, and each membership records why.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human

CATEGORIES = ("requirement", "quality", "regression")
CATEGORY_LABEL = {
    "requirement": "Requirement validation",
    "quality": "General quality",
    "regression": "Regression smoke",
}
KIND_LABEL = {"requirement": "Requirement validation", "quality": "General quality", "regression": "Regression/smoke"}
QUALITY_LABEL = {
    "idempotency": "Idempotency",
    "concurrency": "Concurrency",
    "repeatability": "Repeatability",
    "data_reset": "Data reset",
    "isolation": "Data isolation",
    "contract": "API contract",
}
SCENARIO_LABEL = {"normal": "Normal", "boundary": "Boundary", "exception": "Exception"}
LIST_KEYS = (
    "requirement_ids",
    "categories",
    "type_tags",
    "scenarios",
    "priorities",
    "quality_tags",
)
ALLOWED = {
    "categories": set(CATEGORIES),
    "scenarios": set(SCENARIO_LABEL),
    "priorities": {"P0", "P1", "P2"},
}
LIVE = ("draft", "ready", "done", "cancelled")  # running / archived tasks are left alone
QUALITY_TASK = "General quality: idempotency, concurrency, repeatability"
REGRESSION_TASK = "Regression/smoke: P0 and smoke cases"


# ------------------------------------------------------------------ rules
def clean_selector(cur, selector: dict | None, sut_id) -> dict | None:
    """Validate and normalise a selector; None means 'no rule' (manual-only task)."""
    if selector is None:
        return None
    unknown = set(selector) - set(LIST_KEYS)
    if unknown:
        raise AppError("VALIDATION", f"Unknown rule field: {', '.join(sorted(unknown))}")
    out: dict[str, list[str]] = {}
    for key in LIST_KEYS:
        values = list(dict.fromkeys(str(v) for v in selector.get(key) or []))
        if not values:
            continue
        bad = [v for v in values if key in ALLOWED and v not in ALLOWED[key]]
        if bad:
            raise AppError(
                "VALIDATION",
                f"Rule {key} has an invalid value: {', '.join(bad)}",
                field_errors=[{"field": key}],
            )
        out[key] = values
    if out.get("requirement_ids"):
        cur.execute(
            "SELECT r.id::text AS id FROM requirement r JOIN version v ON v.id=r.version_id"
            " WHERE r.id = ANY(%s::uuid[]) AND v.sut_id=%s",
            (out["requirement_ids"], sut_id),
        )
        found = {r["id"] for r in cur.fetchall()}
        missing = [r for r in out["requirement_ids"] if r not in found]
        if missing:
            raise AppError(
                "NOT_FOUND", "A requirement in the rule does not exist or belongs to another SUT", related=missing
            )
    return out


def candidates(cur, sut_id, case_ids: list | None = None) -> list[dict]:
    cur.execute(
        "SELECT c.id::text AS id, c.code, c.title, c.status, c.category, c.quality_tags,"
        " c.type_tag, c.scenario, c.priority,"
        " coalesce(array_agg(r.id::text ORDER BY r.code) FILTER (WHERE r.id IS NOT NULL), '{}')"
        "   AS req_ids,"
        " coalesce(array_agg(r.code ORDER BY r.code) FILTER (WHERE r.id IS NOT NULL), '{}')"
        "   AS req_codes"
        " FROM test_case c LEFT JOIN case_requirement_link l ON l.case_id=c.id"
        " LEFT JOIN requirement r ON r.id=l.requirement_id"
        " WHERE c.sut_id=%s AND (%s::uuid[] IS NULL OR c.id = ANY(%s::uuid[]))"
        " GROUP BY c.id ORDER BY c.code",
        (sut_id, case_ids, case_ids),
    )
    return cur.fetchall()


def match(selector: dict | None, kind: str, case: dict) -> list[str] | None:
    """The reasons a ready case matches the rule, or None. Cases categorised regression always
    satisfy the category/priority part of a regression/smoke task."""
    if selector is None or case["status"] != "ready":
        return None
    smoke = kind == "regression" and case["category"] == "regression"
    parts: list[str] = []
    if selector.get("requirement_ids"):
        wanted = set(selector["requirement_ids"])
        hit = [c for i, c in zip(case["req_ids"], case["req_codes"], strict=False) if i in wanted]
        if not hit:
            return None
        parts.append("Requirement " + ", ".join(hit))
    if selector.get("categories"):
        if case["category"] not in selector["categories"] and not smoke:
            return None
        parts.append(CATEGORY_LABEL[case["category"]])
    if selector.get("type_tags"):
        if case["type_tag"] not in selector["type_tags"]:
            return None
        parts.append(f"Type {case['type_tag']}")
    if selector.get("scenarios"):
        if case["scenario"] not in selector["scenarios"]:
            return None
        parts.append(f"Scenario {SCENARIO_LABEL.get(case['scenario'], case['scenario'])}")
    if selector.get("priorities"):
        if case["priority"] not in selector["priorities"] and not smoke:
            return None
        parts.append("smoke case" if smoke and case["priority"] not in selector["priorities"] else case["priority"])
    if selector.get("quality_tags"):
        hit = [t for t in case["quality_tags"] or [] if t in selector["quality_tags"]]
        if not hit:
            return None
        parts.append("quality " + ", ".join(QUALITY_LABEL.get(t, t) for t in hit))
    return list(dict.fromkeys(parts)) or ["All ready cases"]


def rule_text(parts: list[str]) -> str:
    return "Rule match: " + " · ".join(parts)


def describe_selector(selector: dict | None, req_codes: dict[str, str] | None = None) -> str:
    if selector is None:
        return "No rule (only manually added cases)"
    req_codes = req_codes or {}
    parts = []
    if selector.get("requirement_ids"):
        parts.append("Requirement " + ", ".join(req_codes.get(r, r) for r in selector["requirement_ids"]))
    if selector.get("categories"):
        parts.append("category " + ", ".join(CATEGORY_LABEL[c] for c in selector["categories"]))
    if selector.get("priorities"):
        parts.append("Priority " + ", ".join(selector["priorities"]))
    if selector.get("scenarios"):
        parts.append("Scenario " + ", ".join(SCENARIO_LABEL[s] for s in selector["scenarios"]))
    if selector.get("type_tags"):
        parts.append("Type " + ", ".join(selector["type_tags"]))
    if selector.get("quality_tags"):
        parts.append("quality " + ", ".join(QUALITY_LABEL.get(t, t) for t in selector["quality_tags"]))
    return "; ".join(parts) or "All ready cases"


# ------------------------------------------------------------------ rows
def rows(cur, task_id) -> list[dict]:
    cur.execute(
        "SELECT case_id::text AS case_id, source, reason, added_at FROM task_case WHERE task_id=%s ORDER BY seq",
        (task_id,),
    )
    return cur.fetchall()


def write_rows(cur, task_id, new_rows: list[dict]) -> None:
    cur.execute("DELETE FROM task_case WHERE task_id=%s", (task_id,))
    for seq, row in enumerate(new_rows, start=1):
        cur.execute(
            "INSERT INTO task_case(task_id, case_id, seq, source, reason, added_at)"
            " VALUES (%s,%s,%s,%s,%s, coalesce(%s, now()))",
            (task_id, row["case_id"], seq, row["source"], row.get("reason"), row.get("added_at")),
        )


def excluded(cur, task_id) -> set[str]:
    cur.execute("SELECT case_id::text AS id FROM task_case_exclusion WHERE task_id=%s", (task_id,))
    return {r["id"] for r in cur.fetchall()}


def sync_task(cur, task: dict, actor: str, prefix: str = "") -> dict:
    """Bring rule rows in line with the selector. Manual rows and exclusions are kept."""
    selector = task.get("selector")
    if selector is None:
        return {"added": [], "removed": []}
    found = {c["id"]: c for c in candidates(cur, task["sut_id"])}
    out_of_task = excluded(cur, task["id"])
    current = rows(cur, task["id"])
    present = {r["case_id"] for r in current}
    kept, removed = [], []
    for row in current:
        case = found.get(row["case_id"])
        gone = case is None or match(selector, task["kind"], case) is None
        if row["source"] == "rule" and gone:
            removed.append(case["code"] if case else row["case_id"])
            continue
        kept.append(row)
    added = []
    for case in found.values():
        if case["id"] in present or case["id"] in out_of_task:
            continue
        parts = match(selector, task["kind"], case)
        if parts is None:
            continue
        kept.append({"case_id": case["id"], "source": "rule", "reason": prefix + rule_text(parts)})
        added.append(case["code"])
    if added or removed:
        write_rows(cur, task["id"], kept)
        diff = {"added": added, "removed": removed}
        log_change(cur, "test_task", task["id"], "sync", actor, diff)
    return {"added": added, "removed": removed}


def script_gaps(cur, task_id) -> list[dict]:
    """Ready functional cases of an automated task that have no automation script (#18).
    They would not be executed (recorded skipped, never an error)."""
    from testagent.services.executions import NON_FUNCTIONAL_TYPES

    cur.execute(
        "SELECT c.id::text AS id, c.code, c.title, c.automation_status FROM task_case tc"
        " JOIN test_task t ON t.id=tc.task_id JOIN test_case c ON c.id=tc.case_id"
        " WHERE tc.task_id=%s AND t.executor='automation' AND c.status='ready'"
        " AND NOT (c.type_tag = ANY(%s)) AND NOT (c.mode='automated' AND c.code_path IS NOT NULL)"
        " ORDER BY tc.seq",
        (task_id, sorted(NON_FUNCTIONAL_TYPES)),
    )
    return cur.fetchall()


def require_scripts(cur, task_id) -> None:
    gaps = script_gaps(cur, task_id)
    if gaps:
        codes = [g["code"] for g in gaps]
        raise AppError(
            "MISSING_SCRIPTS",
            f"{len(gaps)} case(s) in this automated task have no automation script yet: "
            + ", ".join(codes[:10])
            + ("…" if len(codes) > 10 else "")
            + ". Generate scripts, move them to an agent task, or run anyway (they will be skipped)",
            related=codes,
        )


def membership(cur, task_id) -> dict:
    cur.execute(
        "SELECT e.case_id::text AS case_id, c.code, c.title, e.removed_by, e.created_at"
        " FROM task_case_exclusion e JOIN test_case c ON c.id=e.case_id"
        " WHERE e.task_id=%s ORDER BY c.code",
        (task_id,),
    )
    exclusions = cur.fetchall()
    cur.execute(
        "SELECT count(*) FILTER (WHERE source='rule') AS rule,"
        " count(*) FILTER (WHERE source='manual') AS manual FROM task_case WHERE task_id=%s",
        (task_id,),
    )
    counts = cur.fetchone()
    return {
        "exclusions": exclusions,
        "rule_stats": {
            "rule": counts["rule"],
            "manual": counts["manual"],
            "excluded": len(exclusions),
        },
    }


# ------------------------------------------------------------------ service
class TaskBindingService:
    def __init__(self, db, bus: EventBus, actor: str | None = None):
        self.db = db
        self.bus = bus
        self.actor = actor or current_actor()

    def _tasks(self):
        from testagent.services.tasks import TaskService

        return TaskService(self.db, self.bus, actor=self.actor)

    @staticmethod
    def _editable(task: dict) -> None:
        if task["status"] not in LIVE:
            raise AppError("CONFLICT", "The task is running or archived; its cases cannot change")

    def preview(self, task_id, selector: dict | None) -> dict:
        tasks = self._tasks()
        with self.db.tx() as cur:
            task = tasks._task(cur, task_id)
            selector = clean_selector(cur, selector, task["sut_id"])
            out = excluded(cur, task_id)
            hits = []
            for case in candidates(cur, task["sut_id"]):
                parts = match(selector, task["kind"], case)
                if parts is not None:
                    hits.append(
                        {
                            "id": case["id"],
                            "code": case["code"],
                            "title": case["title"],
                            "category": case["category"],
                            "reason": rule_text(parts),
                            "excluded": case["id"] in out,
                        }
                    )
        return {"selector": selector, "cases": hits}

    def set_selector(self, task_id, selector: dict | None) -> dict:
        tasks = self._tasks()
        with self.db.tx() as cur:
            task = tasks._task(cur, task_id, lock=True)
            self._editable(task)
            selector = clean_selector(cur, selector, task["sut_id"])
            cur.execute(
                "UPDATE test_task SET selector=%s, updated_at=now() WHERE id=%s",
                (Jsonb(selector) if selector is not None else None, task_id),
            )
            log_change(cur, "test_task", task_id, "selector", self.actor, {"selector": selector})
            task["selector"] = selector
            sync_task(cur, task, self.actor)
            row = tasks._detail(cur, task_id)
        self.bus.publish("test_task.updated", {"id": str(task_id)})
        return row

    def sync(self, task_id) -> dict:
        tasks = self._tasks()
        with self.db.tx() as cur:
            task = tasks._task(cur, task_id, lock=True)
            self._editable(task)
            result = sync_task(cur, task, self.actor)
            detail = tasks._detail(cur, task_id)
        self.bus.publish("test_task.updated", {"id": str(task_id)})
        return {**result, "task": detail}

    def restore(self, task_id, case_id) -> dict:
        """Undo a manual removal: the rule may pick the case up again."""
        tasks = self._tasks()
        with self.db.tx() as cur:
            task = tasks._task(cur, task_id, lock=True)
            self._editable(task)
            cur.execute(
                "DELETE FROM task_case_exclusion WHERE task_id=%s AND case_id=%s RETURNING case_id",
                (task_id, case_id),
            )
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "This case was not manually removed")
            log_change(cur, "test_task", task_id, "restore_case", self.actor, {"case_id": case_id})
            sync_task(cur, task, self.actor)
            row = tasks._detail(cur, task_id)
        self.bus.publish("test_task.updated", {"id": str(task_id)})
        return row

    def reconcile_case(self, case_id, event: str = "case.ready") -> list[str]:
        """A case changed: join every live rule task it now matches, leave the rule tasks it no
        longer matches. Exclusions and manual rows are respected. Returns touched task ids."""
        prefix = {
            "case.ready": "Case became ready, added automatically (",
            "case.updated": "Case matches the rule after editing, added automatically (",
        }.get(event, "Added automatically (")
        touched = []
        with self.db.tx() as cur:
            (case,) = candidates_by_id(cur, case_id) or (None,)
            if case is None:
                return []
            cur.execute(
                "SELECT t.*, v.sut_id FROM test_task t JOIN version v ON v.id=t.version_id"
                " WHERE v.sut_id=%s AND v.status <> 'closed' AND t.selector IS NOT NULL"
                " AND t.status = ANY(%s) ORDER BY t.created_at FOR UPDATE OF t",
                (case["sut_id"], list(LIVE)),
            )
            for task in cur.fetchall():
                current = rows(cur, task["id"])
                row = next((r for r in current if r["case_id"] == case["id"]), None)
                parts = match(task["selector"], task["kind"], case)
                if row is None and parts is not None:
                    if case["id"] in excluded(cur, task["id"]):
                        continue
                    reason = prefix + rule_text(parts) + ")"
                    current.append({"case_id": case["id"], "source": "rule", "reason": reason})
                    write_rows(cur, task["id"], current)
                    log_change(
                        cur,
                        "test_task",
                        task["id"],
                        "auto_join",
                        self.actor,
                        {"case": case["code"], "reason": reason},
                    )
                    touched.append(str(task["id"]))
                elif row is not None and row["source"] == "rule" and parts is None:
                    write_rows(cur, task["id"], [r for r in current if r is not row])
                    log_change(
                        cur,
                        "test_task",
                        task["id"],
                        "auto_leave",
                        self.actor,
                        {"case": case["code"], "event": event},
                    )
                    touched.append(str(task["id"]))
        for task_id in touched:
            self.bus.publish("test_task.updated", {"id": task_id})
        return touched

    # -------------------------------------------------------------- version level
    def gaps(self, version_id) -> list[dict]:
        """Requirements of the version without any executable case."""
        with self.db.tx() as cur:
            return version_gaps(cur, version_id)

    def ensure_tasks(
        self,
        version_id,
        *,
        cur=None,
        strategy_id=None,
        executor_hints: dict[str, str] | None = None,
        agent_run_id=None,
    ) -> list[dict]:
        """One requirement-validation task per requirement, one quality task and one regression/smoke task — each a rule
        task filled from existing executable cases. Existing rule tasks are never duplicated."""
        if cur is None:
            with self.db.tx() as c:
                created = self.ensure_tasks(
                    version_id,
                    cur=c,
                    strategy_id=strategy_id,
                    executor_hints=executor_hints,
                    agent_run_id=agent_run_id,
                )
            for t in created:
                self.bus.publish("test_task.created", {"id": str(t["id"])})
            return created
        hints = executor_hints or {}
        tasks = self._tasks()
        cur.execute("SELECT * FROM version WHERE id=%s", (version_id,))
        version = cur.fetchone()
        if version is None:
            raise AppError("NOT_FOUND", "Version not found")
        if version["status"] == "closed":
            raise AppError("CONFLICT", "The version is closed")
        cur.execute(
            "SELECT kind, selector, requirement_ids FROM test_task WHERE version_id=%s AND status <> 'archived'",
            (version_id,),
        )
        existing = cur.fetchall()
        covered = set()
        for t in existing:
            if t["kind"] == "requirement" and t["selector"]:
                covered |= set(t["selector"].get("requirement_ids") or [])
        kinds = {t["kind"] for t in existing if t["selector"] is not None}
        cur.execute(
            "SELECT id::text AS id, code, title FROM requirement WHERE version_id=%s ORDER BY code",
            (version_id,),
        )
        plans: list[dict[str, Any]] = []
        for req in cur.fetchall():
            if req["id"] in covered:
                continue
            plans.append(
                {
                    "name": f"Requirement validation: {req['code']} {req['title']}"[:200],
                    "kind": "requirement",
                    "executor": hints.get(req["code"], "agent"),
                    "requirement_ids": [req["id"]],
                    "selector": {"requirement_ids": [req["id"]], "categories": ["requirement"]},
                    "description": f"Rule: ready requirement-validation cases of {req['code']} ",
                }
            )
        if "quality" not in kinds:
            plans.append(
                {
                    "name": QUALITY_TASK,
                    "kind": "quality",
                    "executor": hints.get("quality", "agent"),
                    "selector": {"categories": ["quality"]},
                    "description": (
                        "Rule: ready general-quality cases (idempotency, concurrency, repeatability/data reset, …)"
                    ),
                }
            )
        if "regression" not in kinds:
            plans.append(
                {
                    "name": REGRESSION_TASK,
                    "kind": "regression",
                    "executor": hints.get("regression", "agent"),
                    "selector": {"priorities": ["P0"]},
                    "description": "Rule: ready P0 cases and cases categorised as regression smoke",
                }
            )
        created = []
        for plan in plans:
            row = tasks.create(
                version_id,
                {**plan, "strategy_id": strategy_id},
                cur=cur,
                agent_run_id=agent_run_id,
            )
            brief = {k: row[k] for k in ("id", "name", "kind")}
            created.append({**brief, "cases": len(row["cases"])})
        return created

    # -------------------------------------------------------------- category suggestions
    def resolve_suggestion(self, case_id, *, accept: bool) -> dict:
        """Accept or dismiss a pending category suggestion — a person decides (C01)."""
        ensure_human(self.actor, "Confirm case category")
        from testagent.services.cases import CaseService

        cases = CaseService(self.db, self.bus, actor=self.actor)
        with self.db.tx() as cur:
            cur.execute("SELECT category_suggestion FROM test_case WHERE id=%s", (case_id,))
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Test case not found")
        suggestion = row["category_suggestion"]
        if not suggestion:
            raise AppError("CONFLICT", "No pending category suggestion")
        if accept:
            data = {"category": suggestion["category"]}
            if suggestion.get("quality_tags") is not None:
                data["quality_tags"] = suggestion["quality_tags"]
            cases.update(case_id, data)
        with self.db.tx() as cur:
            cur.execute("UPDATE test_case SET category_suggestion=NULL WHERE id=%s", (case_id,))
            log_change(
                cur,
                "test_case",
                case_id,
                "category_suggestion_accept" if accept else "category_suggestion_dismiss",
                self.actor,
                suggestion,
            )
        return cases.get(case_id)


def candidates_by_id(cur, case_id) -> list[dict]:
    cur.execute("SELECT sut_id FROM test_case WHERE id=%s", (case_id,))
    row = cur.fetchone()
    if row is None:
        return []
    found = candidates(cur, row["sut_id"], [str(case_id)])
    for c in found:
        c["sut_id"] = row["sut_id"]
    return found


def ready_task_feedback(cur, case: dict) -> dict:
    """Describe observed links without changing membership or undoing manual exclusions."""
    (candidate,) = candidates_by_id(cur, case["id"])
    cur.execute(
        "SELECT t.id, t.name, t.version_id, v.name AS version_name, v.status AS version_status,"
        " t.status, t.kind, t.selector, tc.seq, tc.source, tc.reason,"
        " (ex.case_id IS NOT NULL) AS excluded FROM test_task t"
        " JOIN version v ON v.id=t.version_id"
        " LEFT JOIN task_case tc ON tc.task_id=t.id AND tc.case_id=%s"
        " LEFT JOIN task_case_exclusion ex ON ex.task_id=t.id AND ex.case_id=%s"
        " WHERE v.sut_id=%s ORDER BY v.created_at, t.created_at, t.id",
        (case["id"], case["id"], case["sut_id"]),
    )
    linked, not_added = [], []
    for task in cur.fetchall():
        info = {k: task[k] for k in ("id", "name", "version_id", "version_name", "status")}
        if task["seq"] is not None:
            linked.append({**info, "source": task["source"], "reason": task["reason"], "seq": task["seq"]})
            continue
        if task["version_status"] == "closed":
            reason = "version_closed"
        elif task["status"] == "running":
            reason = "task_running"
        elif task["status"] == "archived":
            reason = "task_archived"
        elif task["excluded"]:
            reason = "manually_excluded"
        elif task["selector"] is None:
            reason = "no_rule"
        elif match(task["selector"], task["kind"], candidate) is None:
            reason = "rule_mismatch"
        else:
            reason = "sync_unconfirmed"
        not_added.append({**info, "reason": reason})
    return {
        "case_id": case["id"],
        "code": case["code"],
        "sut_id": case["sut_id"],
        "version_id": case.get("origin_version_id") or next((r["version_id"] for r in case["requirements"]), None),
        "linked": linked,
        "not_added": not_added,
        "sync_warning": any(t["reason"] == "sync_unconfirmed" for t in not_added),
    }


def version_gaps(cur, version_id) -> list[dict]:
    cur.execute(
        "SELECT r.id::text AS requirement_id, r.code, r.title,"
        " count(c.id) FILTER (WHERE c.status='ready') AS ready_count,"
        " count(c.id) FILTER (WHERE c.status='draft') AS draft_count"
        " FROM requirement r LEFT JOIN case_requirement_link l ON l.requirement_id=r.id"
        " LEFT JOIN test_case c ON c.id=l.case_id"
        " WHERE r.version_id=%s GROUP BY r.id ORDER BY r.code",
        (version_id,),
    )
    return [g for g in cur.fetchall() if g["ready_count"] == 0]
