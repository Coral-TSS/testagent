"""Defect statistics (architecture §6.2, BR-08). Rejected defects never count; scores are
Σ severity weight; density = defects ÷ executed cases (passed/failed/error, de-duplicated by case).

The same aggregation serves the live stats API (version/time filters) and reports (explicit
defect and execution scopes), so a report always matches what the stats page showed then."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Literal

from testagent.core.errors import AppError
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human

SEVERITIES = ("critical", "major", "minor", "trivial")
EXECUTED = ("passed", "failed", "error")
# spec SeverityWeight (v1.1); also seeded by migration 0001. Editable at runtime.
DEFAULT_WEIGHTS = {"critical": 10.0, "major": 3.0, "minor": 1.0, "trivial": 0.1}
PersonSort = Literal["attributed_score", "attributed_count", "related_count"]


def load_weights(cur) -> dict[str, float]:
    cur.execute("SELECT severity, weight FROM severity_weight")
    return {r["severity"]: float(r["weight"]) for r in cur.fetchall()}


def scoped_defects(
    cur,
    *,
    version_id=None,
    sut_id=None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    execution_ids: list | None = None,
) -> list[dict]:
    """Non-rejected defects with their requirement ids and (person, role) attributions."""
    cur.execute(
        "SELECT d.id::text AS id, d.code, d.title, d.severity, d.status, d.cause_category,"
        " d.execution_id::text AS execution_id,"
        " COALESCE((SELECT jsonb_agg(x.requirement_id::text) FROM defect_requirement x"
        "   WHERE x.defect_id=d.id), '[]'::jsonb) AS requirement_ids,"
        " COALESCE((SELECT jsonb_agg(jsonb_build_array(x.person_id::text, x.role))"
        "   FROM defect_responsible x WHERE x.defect_id=d.id), '[]'::jsonb) AS responsible"
        " FROM defect d WHERE d.status <> 'rejected'"
        " AND (%(v)s::uuid IS NULL OR d.version_id=%(v)s::uuid)"
        " AND (%(s)s::uuid IS NULL OR d.sut_id=%(s)s::uuid)"
        " AND (%(f)s::timestamptz IS NULL OR d.created_at >= %(f)s::timestamptz)"
        " AND (%(t)s::timestamptz IS NULL OR d.created_at < %(t)s::timestamptz)"
        " AND (%(e)s::uuid[] IS NULL OR d.execution_id = ANY(%(e)s::uuid[]))"
        " ORDER BY d.created_at, d.code",
        {
            "v": version_id,
            "s": sut_id,
            "f": date_from,
            "t": date_to,
            "e": [str(e) for e in execution_ids] if execution_ids is not None else None,
        },
    )
    return cur.fetchall()


def requirement_rows(cur, requirement_ids) -> list[dict]:
    ids = sorted({str(r) for r in requirement_ids})
    if not ids:
        return []
    cur.execute(
        "SELECT r.id::text AS id, r.code, r.title, r.version_id::text AS version_id,"
        " COALESCE((SELECT jsonb_agg(jsonb_build_array(p.name, rp.role) ORDER BY p.name)"
        "   FROM requirement_person rp JOIN person p ON p.id=rp.person_id"
        "   WHERE rp.requirement_id=r.id), '[]'::jsonb) AS people"
        " FROM requirement r WHERE r.id = ANY(%s::uuid[]) ORDER BY r.code",
        (ids,),
    )
    return cur.fetchall()


def executed_by_requirement(cur, executions: list[dict]) -> dict[str, set[str]]:
    """executions: [{case_id, status}] → {requirement_id: {case ids executed}}."""
    case_ids = sorted({str(e["case_id"]) for e in executions if e["status"] in EXECUTED})
    if not case_ids:
        return {}
    cur.execute(
        "SELECT requirement_id::text AS rid, case_id::text AS cid FROM case_requirement_link"
        " WHERE case_id = ANY(%s::uuid[])",
        (case_ids,),
    )
    out: dict[str, set[str]] = defaultdict(set)
    for row in cur.fetchall():
        out[row["rid"]].add(row["cid"])
    return out


def aggregate_requirements(reqs, defects, executed, weights) -> list[dict]:
    rows = []
    for r in reqs:
        mine = [d for d in defects if r["id"] in d["requirement_ids"]]
        sev: dict[str, int] = {}
        for d in mine:
            sev[d["severity"]] = sev.get(d["severity"], 0) + 1
        n_exec = len(executed.get(r["id"], ()))
        people = r["people"]
        rows.append(
            {
                "requirement_id": r["id"],
                "version_id": r["version_id"],
                "code": r["code"],
                "title": r["title"],
                "owner": [n for n, role in people if role == "owner"],
                "developers": [n for n, role in people if role == "developer"],
                "testers": [n for n, role in people if role == "tester"],
                "defect_count": len(mine),
                "weighted_score": float(sum(weights[d["severity"]] for d in mine)),
                "executed_cases": n_exec,
                "density": (len(mine) / n_exec) if n_exec else None,
                "by_severity": {k: sev[k] for k in SEVERITIES if k in sev},
            }
        )
    return rows


def aggregate_people(cur, defects, weights, sort: str = "attributed_score") -> list[dict]:
    req_ids = sorted({r for d in defects for r in d["requirement_ids"]})
    reqs = {r["id"]: r for r in requirement_rows(cur, req_ids)}
    cur.execute(
        "SELECT rp.requirement_id::text AS rid, rp.person_id::text AS pid"
        " FROM requirement_person rp WHERE rp.requirement_id = ANY(%s::uuid[])",
        (req_ids,),
    )
    req_people: dict[str, set[str]] = defaultdict(set)
    for row in cur.fetchall():
        req_people[row["rid"]].add(row["pid"])
    stats: dict[str, dict] = {}

    def entry(pid: str) -> dict:
        return stats.setdefault(
            pid,
            {
                "person_id": pid,
                "attributed": set(),
                "attributed_by_role": {},
                "related": set(),
                "req_counts": defaultdict(int),
            },
        )

    for d in defects:
        weight = weights[d["severity"]]
        for pid, role in d["responsible"]:
            e = entry(pid)
            if d["id"] not in e["attributed"]:
                e["attributed"].add(d["id"])
                for rid in d["requirement_ids"]:
                    e["req_counts"][rid] += 1
            slot = e["attributed_by_role"].setdefault(role, {"count": 0, "score": 0.0})
            slot["count"] += 1
            slot["score"] += weight
        for pid in {p for rid in d["requirement_ids"] for p in req_people.get(rid, ())}:
            entry(pid)["related"].add(d["id"])
    if not stats:
        return []
    cur.execute(
        "SELECT id::text AS id, name, active FROM person WHERE id = ANY(%s::uuid[])",
        (list(stats),),
    )
    persons = {r["id"]: r for r in cur.fetchall()}
    by_id = {d["id"]: d for d in defects}
    rows = []
    for pid, e in stats.items():
        reqs_sorted = sorted(e["req_counts"].items(), key=lambda kv: (-kv[1], reqs[kv[0]]["code"]))
        rows.append(
            {
                "person_id": pid,
                "name": persons[pid]["name"],
                "active": persons[pid]["active"],
                "attributed_count": len(e["attributed"]),
                "attributed_score": float(sum(weights[by_id[i]["severity"]] for i in e["attributed"])),
                "attributed_by_role": {
                    role: {"count": v["count"], "score": float(v["score"])}
                    for role, v in sorted(e["attributed_by_role"].items())
                },
                "related_count": len(e["related"]),
                "requirements": [
                    {"code": reqs[rid]["code"], "title": reqs[rid]["title"], "count": n} for rid, n in reqs_sorted
                ],
            }
        )
    rows.sort(key=lambda r: (-r[sort], -r["attributed_score"], -r["related_count"], r["name"]))
    return rows


class StatsService:
    def __init__(self, db, actor: str = "local-user"):
        self.db = db
        self.actor = actor

    def weights(self) -> dict[str, float]:
        with self.db.tx() as cur:
            return load_weights(cur)

    def set_weights(self, weights: dict[str, float]) -> dict[str, float]:
        ensure_human(self.actor, "Change severity weights")
        if set(weights) != set(SEVERITIES):
            raise AppError("VALIDATION", "All four weights critical/major/minor/trivial are required")
        with self.db.tx() as cur:
            for severity, weight in weights.items():
                cur.execute("UPDATE severity_weight SET weight=%s WHERE severity=%s", (weight, severity))
            log_change(cur, "severity_weight", "all", "update", self.actor, weights)
            return load_weights(cur)

    def requirements(self, *, version_id=None, sut_id=None, date_from=None, date_to=None):
        with self.db.tx() as cur:
            weights = load_weights(cur)
            defects = scoped_defects(cur, version_id=version_id, sut_id=sut_id, date_from=date_from, date_to=date_to)
            if version_id is not None:
                cur.execute("SELECT id::text AS id FROM requirement WHERE version_id=%s", (version_id,))
                req_ids = [r["id"] for r in cur.fetchall()]
            else:
                req_ids = sorted({r for d in defects for r in d["requirement_ids"]})
            reqs = requirement_rows(cur, req_ids)
            cur.execute(
                "SELECT e.case_id, e.status FROM case_execution e"
                " JOIN case_requirement_link l ON l.case_id=e.case_id"
                " WHERE l.requirement_id = ANY(%s::uuid[])"
                " AND (%s::timestamptz IS NULL OR e.created_at >= %s::timestamptz)"
                " AND (%s::timestamptz IS NULL OR e.created_at < %s::timestamptz)",
                ([r["id"] for r in reqs], date_from, date_from, date_to, date_to),
            )
            executed = executed_by_requirement(cur, cur.fetchall())
            return aggregate_requirements(reqs, defects, executed, weights)

    def people(
        self,
        *,
        version_id=None,
        sut_id=None,
        date_from=None,
        date_to=None,
        sort: str = "attributed_score",
    ):
        with self.db.tx() as cur:
            weights = load_weights(cur)
            defects = scoped_defects(cur, version_id=version_id, sut_id=sut_id, date_from=date_from, date_to=date_to)
            return aggregate_people(cur, defects, weights, sort)
