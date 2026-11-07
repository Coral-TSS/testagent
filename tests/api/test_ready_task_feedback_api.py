"""Demo #11: Ready responses explain actual task links after reconciliation."""

from tests.api.test_task_binding_api import req_rule, rule_task
from tests.api.world import V1, build_world, make_case

from testagent.services.task_binding import TaskBindingService


def ready(client, case_id):
    response = client.post(f"{V1}/cases/{case_id}/status", json={"status": "ready"})
    assert response.status_code == 200, response.text
    return response.json()


def test_ready_response_and_reload_include_actual_rule_and_manual_links(client, db):
    world = build_world(client, db)
    case = make_case(client, world, "Review me", status="draft")
    automatic = rule_task(client, world, req_rule(world), name="Automatic")
    manual = rule_task(client, world, None, name="Manual")
    client.put(f"{V1}/tasks/{manual['id']}/cases", json={"case_ids": [case]})
    response = ready(client, case)
    assert {t["id"] for t in response["tasks"]} == {automatic["id"], manual["id"]}
    feedback = response["task_binding"]
    assert feedback["sync_warning"] is False
    linked = {t["id"]: t for t in feedback["linked"]}
    assert linked[automatic["id"]]["source"] == "rule"
    assert "REQ-001" in linked[automatic["id"]]["reason"]
    assert linked[manual["id"]]["source"] == "manual"
    assert linked[manual["id"]]["version_name"] == "v1"
    assert client.get(f"{V1}/cases/{case}").json()["task_binding"] == feedback


def test_unlinked_tasks_explain_rules_exclusions_and_immutable_states(client, db):
    world = build_world(client, db)
    case = make_case(client, world, "Review me", status="draft")
    mismatch = rule_task(client, world, {"categories": ["quality"]}, name="Quality")
    manual = rule_task(client, world, None, name="Manual")
    excluded = rule_task(client, world, req_rule(world), name="Removed by a person")
    client.put(f"{V1}/tasks/{excluded['id']}/cases", json={"case_ids": [case]})
    client.put(f"{V1}/tasks/{excluded['id']}/cases", json={"case_ids": []})
    running = rule_task(client, world, req_rule(world), name="Running")
    archived = rule_task(client, world, req_rule(world), name="Archived")
    client.post(f"{V1}/tasks/{archived['id']}/status", json={"status": "archived"})
    version = client.post(f"{V1}/suts/{world['sut']}/versions", json={"name": "Closed version"}).json()["id"]
    closed = client.post(f"{V1}/versions/{version}/tasks", json={"name": "Closed task", "selector": {}}).json()
    with db.tx() as cur:
        cur.execute("UPDATE test_task SET status='running' WHERE id=%s", (running["id"],))
        cur.execute("UPDATE version SET status='closed' WHERE id=%s", (version,))
    feedback = ready(client, case)["task_binding"]
    assert feedback["linked"] == []
    assert feedback["sync_warning"] is False
    assert {t["id"]: t["reason"] for t in feedback["not_added"]} == {
        mismatch["id"]: "rule_mismatch",
        manual["id"]: "no_rule",
        excluded["id"]: "manually_excluded",
        running["id"]: "task_running",
        archived["id"]: "task_archived",
        closed["id"]: "version_closed",
    }
    assert client.get(f"{V1}/tasks/{excluded['id']}").json()["cases"] == []


def test_ready_without_tasks_is_not_reported_as_a_sync_failure(client, db):
    world = build_world(client, db)
    case = make_case(client, world, "No tasks", status="draft")
    feedback = ready(client, case)["task_binding"]
    assert feedback["linked"] == [] and feedback["not_added"] == []
    assert feedback["sync_warning"] is False
    assert feedback["version_id"] == world["version"]
    assert feedback["sut_id"] == world["sut"]


def test_reconciliation_failure_preserves_ready_but_warns_instead_of_claiming_joined(client, db, monkeypatch):
    world = build_world(client, db)
    case = make_case(client, world, "Review me", status="draft")
    target = rule_task(client, world, req_rule(world))

    def broken(*args, **kwargs):
        raise RuntimeError("Synthetic reconciliation failure")

    monkeypatch.setattr(TaskBindingService, "reconcile_case", broken)
    response = ready(client, case)
    assert response["status"] == "ready"
    assert response["task_binding"]["sync_warning"] is True
    assert response["task_binding"]["linked"] == []
    assert response["task_binding"]["not_added"][0]["id"] == target["id"]
    assert response["task_binding"]["not_added"][0]["reason"] == "sync_unconfirmed"
    assert client.get(f"{V1}/cases/{case}").json()["task_binding"]["sync_warning"] is True


def test_batch_ready_returns_per_case_links_for_success_and_already_ready(client, db):
    world = build_world(client, db)
    target = rule_task(client, world, req_rule(world))
    draft = make_case(client, world, "Draft", status="draft")
    existing = make_case(client, world, "Existing")
    deprecated = make_case(client, world, "Deprecated", status="deprecated")
    response = client.post(
        f"{V1}/cases/batch", json={"case_ids": [draft, existing, deprecated], "action": "ready"}
    ).json()
    assert [r["id"] for r in response["ok"]] == [draft]
    assert [r["id"] for r in response["skipped"]] == [existing]
    assert [r["id"] for r in response["failed"]] == [deprecated]
    for row in (response["ok"][0], response["skipped"][0]):
        assert row["task_binding"]["linked"][0]["id"] == target["id"]
        assert row["task_binding"]["sync_warning"] is False


def test_feedback_never_includes_another_systems_tasks(client, db):
    world = build_world(client, db)
    target = rule_task(client, world, {})
    sut = client.post(f"{V1}/suts", json={"code": "OTHER", "name": "Other"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "Other version"}).json()["id"]
    other = client.post(f"{V1}/versions/{version}/tasks", json={"name": "Other task", "selector": {}}).json()
    case = make_case(client, world, "Review me", status="draft")
    feedback = ready(client, case)["task_binding"]
    assert [t["id"] for t in feedback["linked"]] == [target["id"]]
    assert other["id"] not in {t["id"] for t in feedback["not_added"]}
