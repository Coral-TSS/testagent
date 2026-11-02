"""Tasks only reference cases. Cases carry a category (requirement / quality / regression); tasks
pick cases by rules (selector) plus manual add/remove (manual wins); a case that becomes
executable joins every matching task automatically with a recorded reason; requirement gaps
are listed; strategy generation builds rule tasks from existing cases."""

from __future__ import annotations

import pytest
from tests.api.world import FakeRunner, build_world, install_runner, make_case, run_task

from testagent.agent.fake import FakeChatModel, call
from testagent.core.errors import AppError
from testagent.services.task_binding import TaskBindingService

V1 = "/api/v1"
MISSING = "00000000-0000-0000-0000-000000000001"


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


@pytest.fixture
def world(client, db):
    return build_world(client, db)


def rule_task(client, world, selector, *, name="Rule task", kind="requirement"):
    resp = client.post(
        f"{V1}/versions/{world['version']}/tasks",
        json={"name": name, "kind": kind, "environment_id": world["env"], "selector": selector},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def task(client, task_id):
    return client.get(f"{V1}/tasks/{task_id}").json()


def codes(detail):
    return [c["title"] for c in detail["cases"]]


def req_rule(world, code="REQ-001"):
    return {"requirement_ids": [world["reqs"][code]], "categories": ["requirement"]}


# ------------------------------------------------------------------ case category
def test_case_category_defaults_and_is_editable(client, world):
    cid = make_case(client, world, "Default category", status="draft")
    case = client.get(f"{V1}/cases/{cid}").json()
    assert case["category"] == "requirement" and case["quality_tags"] == []
    patched = client.patch(f"{V1}/cases/{cid}", json={"category": "quality", "quality_tags": ["idempotency"]}).json()
    assert patched["category"] == "quality" and patched["quality_tags"] == ["idempotency"]
    bad = client.patch(f"{V1}/cases/{cid}", json={"category": "performance"})
    assert bad.status_code == 422
    listed = client.get(f"{V1}/suts/{world['sut']}/cases").json()
    assert listed[0]["category"] == "quality"


# ------------------------------------------------------------------ selector
def test_rule_task_references_existing_ready_cases(client, world):
    make_case(client, world, "A requirement")
    make_case(client, world, "B idempotency", category="quality", quality_tags=["idempotency"])
    make_case(client, world, "C requirement2", req_codes=("REQ-002",))
    make_case(client, world, "D draft", status="draft")
    created = rule_task(client, world, req_rule(world))
    assert codes(created) == ["A requirement"]
    (row,) = created["cases"]
    assert row["source"] == "rule"
    assert "REQ-001" in row["reason"] and "Requirement validation" in row["reason"]
    assert created["selector"]["categories"] == ["requirement"]
    preview = client.post(
        f"{V1}/tasks/{created['id']}/selector/preview",
        json={"selector": {"categories": ["quality"]}},
    ).json()
    assert [c["title"] for c in preview["cases"]] == ["B idempotency"]
    changed = client.put(f"{V1}/tasks/{created['id']}/selector", json={"selector": {"categories": ["quality"]}}).json()
    assert codes(changed) == ["B idempotency"]  # rule rows follow the rule


def test_ready_case_joins_matching_tasks_single_and_batch(client, world, db):
    req_task = rule_task(client, world, req_rule(world), name="Requirement validation")
    quality = rule_task(client, world, {"categories": ["quality"]}, name="General quality", kind="quality")
    archived = rule_task(client, world, req_rule(world), name="Archived")
    client.post(f"{V1}/tasks/{archived['id']}/status", json={"status": "archived"})
    one = make_case(client, world, "Single", status="draft")
    client.post(f"{V1}/cases/{one}/status", json={"status": "ready"})
    joined = task(client, req_task["id"])
    assert codes(joined) == ["Single"]
    assert "became ready" in joined["cases"][0]["reason"]
    drafts = [
        make_case(client, world, "Batch1", status="draft"),
        make_case(client, world, "Batch idempotency", status="draft", category="quality"),
    ]
    out = client.post(f"{V1}/cases/batch", json={"case_ids": drafts, "action": "ready"}).json()
    assert len(out["ok"]) == 2
    assert codes(task(client, req_task["id"])) == ["Single", "Batch1"]
    assert codes(task(client, quality["id"])) == ["Batch idempotency"]
    assert codes(task(client, archived["id"])) == []
    with db.tx() as cur:
        cur.execute(
            "SELECT actor, diff FROM change_log WHERE entity_id=%s AND action='auto_join'",
            (req_task["id"],),
        )
        logged = cur.fetchall()
    assert len(logged) == 2 and logged[0]["actor"] == "system"


def test_manual_wins_and_removals_are_respected(client, world):
    a = make_case(client, world, "A")
    t = rule_task(client, world, req_rule(world))
    b = make_case(client, world, "B")  # auto-joined
    other = make_case(client, world, "Other requirement", req_codes=("REQ-002",))
    assert codes(task(client, t["id"])) == ["A", "B"]
    # manual: drop B, add a case the rule does not match
    kept = client.put(f"{V1}/tasks/{t['id']}/cases", json={"case_ids": [a, other]}).json()
    assert [(c["title"], c["source"]) for c in kept["cases"]] == [
        ("A", "rule"),
        ("Other requirement", "manual"),
    ]
    assert [e["case_id"] for e in kept["exclusions"]] == [b]
    synced = client.post(f"{V1}/tasks/{t['id']}/sync").json()
    assert codes(synced["task"]) == ["A", "Other requirement"]  # B stays out, manual row stays in
    # B going back to draft and ready again does not re-add it
    client.post(f"{V1}/cases/{b}/status", json={"status": "draft"})
    client.post(f"{V1}/cases/{b}/status", json={"status": "ready"})
    assert codes(task(client, t["id"])) == ["A", "Other requirement"]
    restored = client.delete(f"{V1}/tasks/{t['id']}/exclusions/{b}").json()
    assert codes(restored) == ["A", "Other requirement", "B"] and restored["exclusions"] == []
    assert restored["rule_stats"] == {"rule": 2, "manual": 1, "excluded": 0}


def test_case_leaving_the_rule_leaves_rule_rows_only(client, world):
    t = rule_task(client, world, req_rule(world))
    a = make_case(client, world, "A")
    manual = make_case(client, world, "M")
    current = [c["id"] for c in task(client, t["id"])["cases"]]
    assert current == [a, manual]
    client.put(f"{V1}/tasks/{t['id']}/cases", json={"case_ids": [a, manual]})  # no-op keeps rule
    client.patch(f"{V1}/cases/{a}", json={"category": "quality"})
    assert codes(task(client, t["id"])) == ["M"]  # A no longer matches → its rule row leaves
    client.post(f"{V1}/cases/{manual}/status", json={"status": "draft"})
    assert codes(task(client, t["id"])) == []  # rule row of a draft case leaves too


def test_running_task_is_not_touched_by_auto_join(client, world, db):
    t = rule_task(client, world, req_rule(world))
    with db.tx() as cur:
        cur.execute("UPDATE test_task SET status='running' WHERE id=%s", (t["id"],))
    make_case(client, world, "Added while running")
    assert codes(task(client, t["id"])) == []
    assert client.post(f"{V1}/tasks/{t['id']}/sync").status_code == 409


def test_regression_task_takes_p0_and_smoke_cases(client, world):
    make_case(client, world, "P0 main path", priority="P0")
    make_case(client, world, "P1 normal")
    make_case(client, world, "Smoke", category="regression", priority="P2")
    reg = rule_task(client, world, {"priorities": ["P0"]}, name="Regression", kind="regression")
    assert codes(reg) == ["P0 main path", "Smoke"]


def test_selector_validation(client, world):
    bad = client.post(
        f"{V1}/versions/{world['version']}/tasks",
        json={"name": "x", "selector": {"categories": ["nope"]}},
    )
    assert bad.status_code == 422
    foreign = client.post(
        f"{V1}/versions/{world['version']}/tasks",
        json={"name": "x", "selector": {"requirement_ids": [MISSING]}},
    )
    assert foreign.status_code in (404, 422)


# ------------------------------------------------------------------ ensure tasks / strategy
def test_ensure_tasks_creates_one_task_per_kind_without_duplicates(client, world):
    make_case(client, world, "Requirement1 case", priority="P0")
    make_case(client, world, "Idempotency", category="quality", quality_tags=["idempotency"])
    out = client.post(f"{V1}/versions/{world['version']}/tasks/ensure").json()
    names = {t["name"]: t for t in out["created"]}
    assert set(names) == {
        "Requirement validation: REQ-001 Requirement1",
        "Requirement validation: REQ-002 Requirement2",
        "General quality: idempotency, concurrency, repeatability",
        "Regression/smoke: P0 and smoke cases",
    }
    tasks = {t["name"]: t for t in client.get(f"{V1}/versions/{world['version']}/tasks").json()}
    assert tasks["Requirement validation: REQ-001 Requirement1"]["case_count"] == 1
    assert tasks["Requirement validation: REQ-002 Requirement2"]["case_count"] == 0
    assert tasks["General quality: idempotency, concurrency, repeatability"]["kind"] == "quality"
    assert tasks["General quality: idempotency, concurrency, repeatability"]["case_count"] == 1
    assert tasks["Regression/smoke: P0 and smoke cases"]["case_count"] == 1
    again = client.post(f"{V1}/versions/{world['version']}/tasks/ensure").json()
    assert again["created"] == []


def test_strategy_generation_builds_rule_tasks_and_lists_gaps(client, world):
    make_case(client, world, "Requirement1 ready")
    make_case(client, world, "Requirement2 draft", req_codes=("REQ-002",), status="draft")
    use_model(
        client,
        call(
            "submit_result",
            {
                "scope": "Procurement",
                "test_types": ["functional"],
                "intensity": "standard",
                "tasks": [
                    {"name": "Any name", "requirement_codes": ["REQ-001"], "executor": "human"},
                    {"name": "Idempotency", "kind": "quality"},
                ],
            },
        ),
    )
    out = client.post(f"{V1}/versions/{world['version']}/strategy/generate").json()
    assert out["status"] == "succeeded", out
    tasks = {t["name"]: t for t in out["strategy"]["tasks"]}
    req1 = tasks["Requirement validation: REQ-001 Requirement1"]
    assert req1["kind"] == "requirement" and req1["case_count"] == 1
    assert req1["executor"] == "human"  # hint from the model
    assert req1["selector"] == {
        "requirement_ids": [world["reqs"]["REQ-001"]],
        "categories": ["requirement"],
    }
    assert {t["kind"] for t in tasks.values()} == {"requirement", "quality", "regression"}
    gaps = {g["code"]: g for g in out["strategy"]["gaps"]}
    assert set(gaps) == {"REQ-002"}
    assert gaps["REQ-002"]["draft_count"] == 1 and gaps["REQ-002"]["ready_count"] == 0
    # regenerating does not pile up tasks
    use_model(
        client,
        call("submit_result", {"scope": "s", "test_types": ["functional"], "intensity": "light"}),
    )
    again = client.post(f"{V1}/versions/{world['version']}/strategy/generate").json()
    assert sorted(t["name"] for t in again["strategy"]["tasks"]) == sorted(tasks)


def test_gap_drafts_stay_drafts_until_a_human_makes_them_ready(client, world):
    rule_task(client, world, req_rule(world, "REQ-002"), name="Requirement2")
    draft = {
        "title": "Requirement2 draft",
        "test_point": "Click",
        "scenario": "normal",
        "steps": [{"action": "Do"}],
        "expected": "OK",
        "requirement_codes": ["REQ-002"],
        "category": "requirement",
    }
    use_model(client, call("submit_result", {"cases": [draft, draft, draft]}))
    out = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["reqs"]["REQ-002"]], "automate": False},
    ).json()
    assert out["status"] == "succeeded"
    rows = [client.get(f"{V1}/cases/{c['id']}").json() for c in out["cases"]]
    assert {r["status"] for r in rows} == {"draft"}
    tasks = client.get(f"{V1}/versions/{world['version']}/tasks").json()
    assert tasks[0]["case_count"] == 0
    client.post(f"{V1}/cases/{rows[0]['id']}/status", json={"status": "ready"})
    assert client.get(f"{V1}/versions/{world['version']}/tasks").json()[0]["case_count"] == 1


# ------------------------------------------------------------------ AI category
def test_generated_cases_carry_category(client, world):
    base = {
        "test_point": "Click",
        "steps": [{"action": "Do"}],
        "expected": "OK",
        "requirement_codes": ["REQ-001"],
    }
    cases = [
        {**base, "title": "Threshold", "scenario": "boundary", "category": "requirement"},
        {**base, "title": "Invalid input", "scenario": "exception"},
        {
            **base,
            "title": "Duplicate payment idempotency",
            "scenario": "exception",
            "category": "quality",
            "quality_tags": ["idempotency"],
        },
    ]
    use_model(client, call("submit_result", {"cases": cases}))
    out = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["reqs"]["REQ-001"]], "automate": False},
    ).json()
    rows = {c["title"]: client.get(f"{V1}/cases/{c['id']}").json() for c in out["cases"]}
    assert rows["Threshold"]["category"] == "requirement"
    assert rows["Invalid input"]["category"] == "requirement"  # input validation = requirement
    assert (
        rows["Duplicate payment idempotency"]["category"],
        rows["Duplicate payment idempotency"]["quality_tags"],
    ) == (
        "quality",
        ["idempotency"],
    )


def test_category_suggestion_needs_a_human(client, world, db):
    cid = make_case(client, world, "Unsure")
    with db.tx() as cur:
        cur.execute(
            "UPDATE test_case SET category_suggestion=%s::jsonb WHERE id=%s",
            ('{"category": "quality", "quality_tags": ["repeatability"], "reason": "r"}', cid),
        )
    listed = client.get(f"{V1}/suts/{world['sut']}/cases").json()
    assert listed[0]["category_suggestion"]["category"] == "quality"
    with pytest.raises(AppError):
        TaskBindingService(db, client.app.state.bus, actor="agent:x").resolve_suggestion(cid, accept=True)
    quality = rule_task(client, world, {"categories": ["quality"]}, kind="quality")
    accepted = client.post(f"{V1}/cases/{cid}/category-suggestion", json={"accept": True}).json()
    assert accepted["category"] == "quality" and accepted["category_suggestion"] is None
    assert accepted["quality_tags"] == ["repeatability"]
    assert codes(task(client, quality["id"])) == ["Unsure"]
    with db.tx() as cur:
        cur.execute(
            'UPDATE test_case SET category_suggestion=\'{"category": "regression"}\' WHERE id=%s',
            (cid,),
        )
    dismissed = client.post(f"{V1}/cases/{cid}/category-suggestion", json={"accept": False}).json()
    assert dismissed["category"] == "quality" and dismissed["category_suggestion"] is None
    again = client.post(f"{V1}/cases/{cid}/category-suggestion", json={"accept": True})
    assert again.status_code == 409


# ------------------------------------------------------------------ reports
def test_run_report_counts_by_category(client, world):
    runner = FakeRunner({"Idempotency": "failed"})
    install_runner(client, runner)
    make_case(client, world, "Requirement")
    make_case(client, world, "Idempotency", category="quality")
    t = rule_task(client, world, {"requirement_ids": [world["reqs"]["REQ-001"]]})
    client.post(f"{V1}/tasks/{t['id']}/status", json={"status": "ready"})
    run = run_task(client, t["id"])
    reports = client.get(f"{V1}/reports", params={"scope_id": run["id"]}).json()
    report = client.get(f"{V1}/reports/{reports[0]['id']}").json()
    by = {r["category"]: r for r in report["content"]["by_category"]}
    assert by["requirement"]["label"] == "Requirement validation" and by["requirement"]["passed"] == 1
    assert by["quality"]["failed"] == 1 and by["quality"]["pass_rate"] == 0
