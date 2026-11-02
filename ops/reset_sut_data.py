"""Reset one SUT to "system + environments only".

Clears everything TestAgent built for the SUT: model (nodes, fields, links, edges, API bindings,
modules), API registry, suggestions, review marks, versions and model snapshots, requirements
and their links, strategies, tasks, cases (revisions, links), executions and runs, defects,
reports, coverage reports, corrections, the SUT's agent runs and the jobs that point at any of
these. Keeps the SUT row, its environments, people, agent config, prompt versions, memories
(and the agent runs they cite), severity weights, the change log and every other SUT.

The SUT's local test repo (runtime/repos/<code>) is moved to ``--repo-archive`` (never
deleted, never overwritten) and a fresh repo is initialized exactly like the platform does for
a new SUT (``TestRepo.ensure``).

Dry run by default: prints what would be removed and kept. ``--apply`` does it in one
transaction (the immutability guards on reports/snapshots are lifted only inside that
transaction). Take a full backup (pg_dump) first. The connection string comes from .env and
is never printed.

    uv run python ops/reset_sut_data.py --sut procurement
    uv run python ops/reset_sut_data.py --sut procurement --apply --repo-archive <dir>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from testagent.core.errors import AppError  # noqa: E402
from testagent.integrations.git_repo import TestRepo  # noqa: E402

# (table, SQL selecting the ids to delete; %(...)s are id lists collected before)
COLLECT: list[tuple[str, str]] = [
    ("version", "SELECT id FROM version WHERE sut_id=%(sut)s"),
    ("test_case", "SELECT id FROM test_case WHERE sut_id=%(sut)s"),
    ("test_task", "SELECT id FROM test_task WHERE version_id = ANY(%(version)s)"),
    ("task_run", "SELECT id FROM task_run WHERE task_id = ANY(%(test_task)s)"),
    (
        "case_execution",
        "SELECT id FROM case_execution WHERE case_id = ANY(%(test_case)s) OR task_run_id = ANY(%(task_run)s)",
    ),
    (
        "defect",
        "SELECT id FROM defect WHERE sut_id=%(sut)s OR case_id = ANY(%(test_case)s)"
        " OR execution_id = ANY(%(case_execution)s)",
    ),
    (
        "report",
        "SELECT id FROM report WHERE (scope_type='task_run' AND scope_id = ANY(%(task_run)s))"
        " OR (scope_type='version' AND scope_id = ANY(%(version)s))",
    ),
    ("coverage_report", "SELECT id FROM coverage_report WHERE version_id = ANY(%(version)s)"),
    ("test_strategy", "SELECT id FROM test_strategy WHERE version_id = ANY(%(version)s)"),
    ("requirement", "SELECT id FROM requirement WHERE version_id = ANY(%(version)s)"),
    ("model_suggestion", "SELECT id FROM model_suggestion WHERE sut_id=%(sut)s"),
    (
        "model_snapshot",
        "SELECT id FROM model_snapshot WHERE sut_id=%(sut)s OR version_id = ANY(%(version)s)",
    ),
    ("model_review_mark", "SELECT id FROM model_review_mark WHERE sut_id=%(sut)s"),
    ("correction", "SELECT id FROM correction WHERE sut_id=%(sut)s"),
    ("model_link", "SELECT id FROM model_link WHERE sut_id=%(sut)s"),
    ("api_endpoint", "SELECT id FROM api_endpoint WHERE sut_id=%(sut)s"),
    ("entity_attribute", "SELECT id FROM entity_attribute WHERE sut_id=%(sut)s"),
    ("model_edge", "SELECT id FROM model_edge WHERE sut_id=%(sut)s"),
    ("model_node", "SELECT id FROM model_node WHERE sut_id=%(sut)s"),
    ("module", "SELECT id FROM module WHERE sut_id=%(sut)s"),
    (
        "agent_run",
        "SELECT id FROM agent_run WHERE sut_id=%(sut)s AND id NOT IN ("
        " SELECT agent_run_id FROM agent_memory WHERE agent_run_id IS NOT NULL"
        " UNION SELECT agent_run_id FROM prompt_template WHERE agent_run_id IS NOT NULL)",
    ),
]
# delete order (children first); rows of tables with ON DELETE CASCADE children go with them
DELETE_ORDER = [
    "model_review_mark",
    "defect",
    "report",
    "case_execution",
    "task_run",
    "test_task",
    "coverage_report",
    "test_case",
    "test_strategy",
    "model_suggestion",
    "requirement",
    "model_snapshot",
    "version",
    "correction",
    "model_link",
    "api_endpoint",
    "entity_attribute",
    "model_edge",
    "model_node",
    "module",
    "agent_run",
]
GUARDS = [("report", "report_immutable"), ("model_snapshot", "model_snapshot_immutable")]
KEEP = {
    "environment": "SELECT count(*) AS n FROM environment WHERE sut_id=%(sut)s",
    "agent_memory": "SELECT count(*) AS n FROM agent_memory WHERE sut_id=%(sut)s",
    "person": "SELECT count(*) AS n FROM person",
    "agent_config": "SELECT count(*) AS n FROM agent_config",
    "prompt_template": "SELECT count(*) AS n FROM prompt_template",
    "agent_memory_all": "SELECT count(*) AS n FROM agent_memory",
    "severity_weight": "SELECT count(*) AS n FROM severity_weight",
    "change_log": "SELECT count(*) AS n FROM change_log",
}


def _collect(cur, sut_id) -> dict[str, list]:
    ids: dict[str, list] = {"sut": sut_id}
    for table, sql in COLLECT:
        cur.execute(sql, ids)
        ids[table] = [r["id"] for r in cur.fetchall()]
    every = [str(sut_id)] + [str(i) for t, _ in COLLECT for i in ids[t]]
    cur.execute(
        "SELECT id, status FROM jobs j WHERE EXISTS (SELECT 1 FROM jsonb_each_text("
        " CASE WHEN jsonb_typeof(j.payload)='object' THEN j.payload ELSE '{}'::jsonb END) kv"
        " WHERE kv.value = ANY(%s))",
        (every,),
    )
    ids["jobs"] = cur.fetchall()
    return ids


def reset_sut(db, sut_code: str, *, apply: bool = False) -> dict:
    with db.tx() as cur:
        cur.execute("SELECT id, code, name FROM sut WHERE code=%s", (sut_code,))
        sut = cur.fetchone()
        if sut is None:
            raise AppError("NOT_FOUND", f"SUT {sut_code} does not exist")
        ids = _collect(cur, sut["id"])
        cur.execute(
            "SELECT count(*) AS n FROM task_run WHERE id = ANY(%s) AND status IN ('queued','running')",
            (ids["task_run"],),
        )
        busy = cur.fetchone()["n"] + sum(1 for j in ids["jobs"] if j["status"] == "running")
        keep = {}
        for name, sql in KEEP.items():
            cur.execute(sql, {"sut": sut["id"]})
            keep[name] = cur.fetchone()["n"]
        cur.execute("SELECT code, name FROM sut WHERE id<>%s ORDER BY created_at", (sut["id"],))
        others = [f"{r['name']} ({r['code']})" for r in cur.fetchall()]
        delete = {t: len(ids[t]) for t, _ in COLLECT}
        delete["jobs"] = len(ids["jobs"])
        result = {
            "sut": {"id": str(sut["id"]), "code": sut["code"], "name": sut["name"]},
            "delete": delete,
            "keep": keep,
            "other_suts": others,
            "applied": False,
        }
        if not apply:
            return result
        if busy:
            raise AppError(
                "CONFLICT",
                "This SUT still has queued or running executions/background jobs; wait for them or cancel them first",
            )
        for table, trigger in GUARDS:
            cur.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
        cur.execute("UPDATE version SET model_snapshot_id=NULL WHERE id = ANY(%s)", (ids["version"],))
        cur.execute(
            "DELETE FROM node_api_link WHERE node_id = ANY(%s) OR api_id = ANY(%s)",
            (ids["model_node"], ids["api_endpoint"]),
        )
        for table in DELETE_ORDER:
            if ids[table]:
                cur.execute(f"DELETE FROM {table} WHERE id = ANY(%s)", (ids[table],))
        if ids["jobs"]:
            cur.execute("DELETE FROM jobs WHERE id = ANY(%s)", ([j["id"] for j in ids["jobs"]],))
        for table, trigger in GUARDS:
            cur.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
        result["applied"] = True
        return result


def reset_repo(root: Path, sut_code: str, sut_id: str, archive: Path, *, apply: bool) -> dict:
    repo = TestRepo(root, sut_code, sut_id)
    result = {
        "path": str(repo.path.resolve()),
        "exists": repo.path.exists(),
        "archive": str(Path(archive).resolve()),
    }
    if not apply:
        result["archive_exists"] = Path(archive).exists()
        return result
    if Path(archive).exists():
        raise FileExistsError(f"Archive directory already exists, not overwriting: {archive}")
    if repo.path.exists():
        Path(archive).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(repo.path), str(archive))
    info = repo.ensure()
    result["head"] = info.get("head")
    return result


def main(argv: list[str] | None = None) -> int:
    from testagent.core.config import Settings
    from testagent.core.db import Database

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sut", required=True, help="SUT code, e.g. procurement")
    parser.add_argument("--apply", action="store_true", help="Really do it (default is a dry run)")
    parser.add_argument("--repo-archive", type=Path, help="Move the old test repo here (required with --apply)")
    parser.add_argument("--keep-repo", action="store_true", help="Leave the local test repo alone")
    args = parser.parse_args(argv)
    if args.apply and not args.keep_repo and args.repo_archive is None:
        parser.error("--apply needs --repo-archive (or --keep-repo)")
    settings = Settings()
    db = Database(settings.require_database_url(), max_size=1)
    try:
        out = reset_sut(db, args.sut, apply=args.apply)
        if not args.keep_repo:
            archive = args.repo_archive or Path("(not given)")
            out["repo"] = reset_repo(
                settings.runtime_dir / "repos",
                args.sut,
                out["sut"]["id"],
                archive,
                apply=args.apply,
            )
    except AppError as exc:
        print(f"Failed: {exc.message}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not args.apply:
        print("Dry run finished, nothing changed; add --apply to do it.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
