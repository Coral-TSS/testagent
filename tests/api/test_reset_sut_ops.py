"""ops script: reset one SUT to "system + environments only" so the user can walk through
TestAgent from scratch. Dry run changes nothing; apply clears the SUT's model, APIs,
versions, requirements, cases, runs, defects, reports, review marks, suggestions, corrections,
agent runs and jobs; keeps the SUT, its environments, people, config, prompts and memories,
and other SUTs; archives the test repo and initializes a fresh one."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb
from tests.api.test_model_review_api import setup_model
from tests.api.world import (
    V1,
    FakeRunner,
    build_world,
    install_runner,
    make_case,
    make_task,
    run_task,
)

from testagent.core.errors import AppError
from testagent.integrations.git_repo import TestRepo

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "reset_sut_data.py"


def load_script():
    spec = importlib.util.spec_from_file_location("reset_sut_data", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def one(db, sql, args=()):
    with db.tx() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def count(db, table, where="TRUE", args=()):
    return one(db, f"SELECT count(*) AS n FROM {table} WHERE {where}", args)["n"]


def populate(client, db):
    w = build_world(client, db)
    sut = w["sut"]
    model = setup_model(client, w)
    client.post(f"{V1}/suts/{sut}/modules", json={"name": "Procurement"})
    client.post(f"{V1}/suts/{sut}/apis", json={"method": "POST", "path": "/orders"})
    case = make_case(client, w, "Amount approval")
    task = make_task(client, w, [case])
    install_runner(client, FakeRunner({"Amount approval": "failed"}))
    run = run_task(client, task)
    execution = run["executions"][0]["id"]
    assert client.post(f"{V1}/executions/{execution}/defect", json={}).status_code == 201
    assert client.post(f"{V1}/versions/{w['version']}/report").status_code == 201
    corr = client.post(
        f"{V1}/corrections",
        json={"target_type": "case", "target_id": case, "content": "Amount in cents"},
    )
    assert corr.status_code == 201, corr.text
    client.put(
        f"{V1}/suts/{sut}/model-review/marks",
        json={"target_type": "entity", "target_id": model["order"], "reviewed": True},
    )
    with db.tx() as cur:
        cur.execute("INSERT INTO agent_run(purpose, sut_id) VALUES ('structure', %s) RETURNING id", (sut,))
        run_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO model_suggestion(sut_id, agent_run_id, payload) VALUES (%s, %s, %s)",
            (sut, run_id, Jsonb({"name": "Approver"})),
        )
        cur.execute(
            "INSERT INTO agent_run(purpose, sut_id) VALUES ('digest_correction', %s) RETURNING id",
            (sut,),
        )
        kept_run = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO agent_memory(scope, sut_id, content, agent_run_id)"
            " VALUES ('sut', %s, 'The amount field is in cents', %s)",
            (sut, kept_run),
        )
        cur.execute(
            "INSERT INTO jobs(kind, payload) VALUES ('automate_case', %s)",
            (Jsonb({"case_id": case}),),
        )
        cur.execute("INSERT INTO jobs(kind, payload) VALUES ('other', %s)", (Jsonb({"x": "1"}),))
    other = client.post(f"{V1}/suts", json={"code": "OTHER", "name": "Other system"}).json()["id"]
    client.post(f"{V1}/suts/{other}/nodes", json={"kind": "entity", "name": "Customer"})
    client.post(f"{V1}/suts/{other}/versions", json={"name": "v9"})
    return {**w, "case": case, "kept_run": kept_run, "other": other}


SUT_TABLES = [
    ("model_node", "sut_id=%s"),
    ("model_link", "sut_id=%s"),
    ("entity_attribute", "sut_id=%s"),
    ("api_endpoint", "sut_id=%s"),
    ("module", "sut_id=%s"),
    ("version", "sut_id=%s"),
    ("test_case", "sut_id=%s"),
    ("defect", "sut_id=%s"),
    ("model_suggestion", "sut_id=%s"),
    ("model_review_mark", "sut_id=%s"),
    ("model_snapshot", "sut_id=%s"),
    ("correction", "sut_id=%s"),
]


def test_dry_run_changes_nothing_and_apply_resets_only_that_sut(client, db, tmp_path):
    w = populate(client, db)
    sut = w["sut"]
    mod = load_script()
    before = {t: count(db, t, where, (sut,)) for t, where in SUT_TABLES}
    assert all(before[t] for t in ("model_node", "version", "test_case", "defect", "correction"))
    reports = count(db, "report")
    plan = mod.reset_sut(db, "SHOP", apply=False)
    assert plan["sut"]["code"] == "SHOP" and plan["applied"] is False
    assert plan["delete"]["test_case"] == before["test_case"]
    assert plan["delete"]["report"] == reports and plan["delete"]["jobs"] >= 1
    assert {t: count(db, t, where, (sut,)) for t, where in SUT_TABLES} == before

    done = mod.reset_sut(db, "SHOP", apply=True)
    assert done["applied"] is True and done["delete"] == plan["delete"]
    for t, where in SUT_TABLES:
        assert count(db, t, where, (sut,)) == 0, t
    assert count(db, "report") == 0
    assert count(db, "agent_run", "sut_id=%s AND id<>%s", (sut, w["kept_run"])) == 0
    assert count(db, "jobs") == 1  # the unrelated job stays
    # kept: the SUT, its environments, people, memories (and the run they point to), other SUTs
    assert count(db, "sut", "id=%s", (sut,)) == 1
    assert count(db, "environment", "sut_id=%s", (sut,)) == 1
    assert count(db, "person") == 4
    assert count(db, "agent_memory", "sut_id=%s", (sut,)) == 1
    assert count(db, "agent_run", "id=%s", (w["kept_run"],)) == 1
    assert count(db, "model_node", "sut_id=%s", (w["other"],)) == 1
    assert count(db, "version", "sut_id=%s", (w["other"],)) == 1
    assert done["keep"]["environment"] == 1 and done["keep"]["agent_memory"] == 1
    # the immutability guards are back
    with pytest.raises(Exception, match="immutable|cannot|forbid"):
        with db.tx() as cur:
            cur.execute(
                "INSERT INTO model_snapshot(sut_id, content, digest) VALUES (%s, '{}', 'x') RETURNING id",
                (w["other"],),
            )
            snap = cur.fetchone()["id"]
            cur.execute("DELETE FROM model_snapshot WHERE id=%s", (snap,))
    # the platform works on the cleared SUT: the progress starts over
    steps = client.get(f"{V1}/suts/{sut}/progress").json()["steps"]
    assert [s["status"] for s in steps][:2] == ["done", "todo"]
    # idempotent
    again = mod.reset_sut(db, "SHOP", apply=True)
    assert not any(again["delete"].values())


def test_unknown_sut_is_refused(db):
    with pytest.raises(AppError):
        load_script().reset_sut(db, "NOPE", apply=False)


def test_repo_is_archived_and_reinitialized(tmp_path):
    mod = load_script()
    root = tmp_path / "repos"
    repo = TestRepo(root, "procurement", "s-1")
    repo.ensure()
    (repo.path / "tests" / "test_old.py").write_text("def test_x():\n    pass\n", "utf-8")
    archive = tmp_path / "archive" / "test-repo-procurement-before-reset"

    plan = mod.reset_repo(root, "procurement", "s-1", archive, apply=False)
    assert plan["exists"] is True and not archive.exists()

    done = mod.reset_repo(root, "procurement", "s-1", archive, apply=True)
    assert (archive / "tests" / "test_old.py").exists() and (archive / ".git").exists()
    assert not (repo.path / "tests" / "test_old.py").exists()
    meta = json.loads((repo.path / ".testagent.json").read_text("utf-8"))
    assert meta["sut_code"] == "procurement" and meta["sut_id"] == "s-1"
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo.path, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert len(log) == 1 and done["head"]
    with pytest.raises(FileExistsError):  # never overwrite an archive
        mod.reset_repo(root, "procurement", "s-1", archive, apply=True)
