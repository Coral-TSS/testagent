"""M1-06 test strategy (revisions, AI generation) and task set."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.conftest import TEST_USER

from testagent.agent.fake import FakeChatModel, call
from testagent.core.config import DEFAULT_TIMEZONE
from testagent.core.errors import AppError
from testagent.services.strategy import StrategyService
from testagent.services.tasks import next_run

V1 = "/api/v1"


@pytest.fixture
def frozen(client, db):
    sut = client.post(f"{V1}/suts", json={"code": "SHOP", "name": "Shop"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1"}).json()["id"]
    owner = client.post(f"{V1}/persons", json={"name": "Pat Product"}).json()["id"]
    reqs = {}
    for title in ("Create purchase order", "Approve purchase order"):
        req = client.post(f"{V1}/versions/{version}/requirements", json={"title": title}).json()
        client.put(f"{V1}/requirements/{req['id']}/people", json=[{"person_id": owner, "role": "owner"}])
        client.put(f"{V1}/requirements/{req['id']}/structure", json={"action": [{"text": title}]})
        assert client.post(f"{V1}/requirements/{req['id']}/confirm").status_code == 200
        reqs[req["code"]] = req["id"]
    frozen = client.post(f"{V1}/versions/{version}/freeze").json()
    env = client.post(
        f"{V1}/suts/{sut}/environments", json={"name": "test", "base_url": "http://localhost:8766"}
    ).json()["id"]
    return {
        "sut": sut,
        "version": version,
        "reqs": reqs,
        "env": env,
        "snapshot": frozen["model_snapshot_id"],
    }


def make_cases(db, sut, n, status="ready"):
    ids = []
    with db.tx() as cur:
        for i in range(n):
            cur.execute(
                "INSERT INTO test_case(sut_id, code, title, status) VALUES (%s,%s,%s,%s) RETURNING id::text AS id",
                (sut, f"TC-{len(ids) + 1:03d}-{status}", f"Case{i}", status),
            )
            ids.append(cur.fetchone()["id"])
    return ids


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


# ------------------------------------------------------------------ strategy
def test_strategy_requires_frozen_version(client):
    sut = client.post(f"{V1}/suts", json={"code": "S", "name": "s"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v"}).json()["id"]
    resp = client.put(f"{V1}/versions/{version}/strategy", json={"scope": "x"})
    assert resp.status_code == 409
    assert client.get(f"{V1}/versions/{version}/strategy").status_code == 404


def test_strategy_edit_after_confirm_returns_draft(client, frozen):
    url = f"{V1}/versions/{frozen['version']}/strategy"
    first = client.put(
        url, json={"scope": "Procurement flow", "test_types": ["functional"], "intensity": "standard"}
    ).json()
    assert first["status"] == "draft" and first["revision"] == 1
    assert first["snapshot_id"] == frozen["snapshot"]  # BR-02
    confirmed = client.post(f"{V1}/strategy/{first['id']}/confirm").json()
    assert confirmed["status"] == "confirmed" and confirmed["confirmed_by"] == TEST_USER
    assert client.post(f"{V1}/strategy/{first['id']}/confirm").status_code == 409
    edited = client.put(url, json={"scope": "Purchase+payment", "test_types": ["functional"]}).json()
    assert edited["status"] == "draft" and edited["revision"] == 2
    assert edited["confirmed_at"] is None


def test_generate_strategy_creates_tasks(client, frozen, db):
    use_model(
        client,
        call("list_requirements", {"version_id": frozen["version"]}),
        call(
            "submit_result",
            {
                "scope": "Purchase order creation and approval",
                "test_types": ["functional", "performance"],
                "intensity": "standard",
                "tasks": [
                    {"name": "Purchase order creation", "requirement_codes": ["REQ-001"]},
                    {
                        "name": "Approval flow",
                        "requirement_codes": ["REQ-002"],
                        "executor": "human",
                    },
                ],
            },
        ),
    )
    out = client.post(f"{V1}/versions/{frozen['version']}/strategy/generate").json()
    assert out["status"] == "succeeded"
    strategy = out["strategy"]
    assert strategy["source"] == "agent" and strategy["agent_run_id"] == out["agent_run_id"]
    assert strategy["status"] == "draft"  # AI only drafts
    tasks = {t["name"]: t for t in strategy["tasks"]}
    # tasks are rule tasks — one per requirement, plus quality and regression/smoke
    assert set(tasks) == {
        "Requirement validation: REQ-001 Create purchase order",
        "Requirement validation: REQ-002 Approve purchase order",
        "General quality: idempotency, concurrency, repeatability",
        "Regression/smoke: P0 and smoke cases",
    }
    assert tasks["Requirement validation: REQ-001 Create purchase order"]["requirement_ids"] == [
        frozen["reqs"]["REQ-001"]
    ]
    assert tasks["Requirement validation: REQ-002 Approve purchase order"]["executor"] == "human"
    with db.tx() as cur:
        cur.execute("SELECT DISTINCT source, agent_run_id::text AS r FROM test_task")
        assert cur.fetchall() == [{"source": "agent", "r": out["agent_run_id"]}]
    # regenerating keeps the rule tasks instead of piling up
    use_model(
        client,
        call(
            "submit_result",
            {
                "scope": "s",
                "test_types": ["functional"],
                "intensity": "light",
                "tasks": [{"name": "Merged task", "requirement_codes": ["REQ-001", "REQ-002"]}],
            },
        ),
    )
    again = client.post(f"{V1}/versions/{frozen['version']}/strategy/generate").json()
    assert {t["name"] for t in again["strategy"]["tasks"]} == set(tasks)
    assert again["created_tasks"] == []
    assert again["strategy"]["revision"] == 2


def test_nonfunctional_types_are_tags_only(client, frozen):
    use_model(
        client,
        call(
            "submit_result",
            {
                "scope": "s",
                "test_types": ["functional", "performance", "security"],
                "intensity": "thorough",
                "tasks": [
                    {"name": "Functional", "requirement_codes": ["REQ-001"]},
                    {"name": "Load test", "type_tag": "performance"},
                    {"name": "Pen test", "type_tag": "security"},
                ],
            },
        ),
    )
    out = client.post(f"{V1}/versions/{frozen['version']}/strategy/generate").json()
    assert out["strategy"]["test_types"] == ["functional", "performance", "security"]
    assert {t["kind"] for t in out["strategy"]["tasks"]} == {"requirement", "quality", "regression"}
    assert not any("Load test" in t["name"] or "Pen test" in t["name"] for t in out["strategy"]["tasks"])
    assert out["tag_only_types"] == ["performance", "security"]


def test_generate_rejects_unknown_requirement_codes(client, frozen):
    bad = {
        "scope": "s",
        "test_types": ["functional"],
        "intensity": "light",
        "tasks": [{"name": "x", "requirement_codes": ["REQ-404"]}],
    }
    fake = use_model(client, *[call("submit_result", bad)] * 3)
    out = client.post(f"{V1}/versions/{frozen['version']}/strategy/generate").json()
    assert out["status"] == "failed" and out["error_code"] == "VALIDATION"
    assert "REQ-404" in fake.seen[1][-1].content
    assert client.get(f"{V1}/versions/{frozen['version']}/strategy").status_code == 404


def test_agent_cannot_confirm_strategy(client, frozen, db):
    sid = client.put(f"{V1}/versions/{frozen['version']}/strategy", json={"scope": "x"}).json()["id"]
    with pytest.raises(AppError, match="can only be done by a person"):
        StrategyService(db, client.app.state.bus, actor="agent:1").confirm(sid)


# ------------------------------------------------------------------ tasks
def test_task_case_order(client, frozen, db):
    a, b, c = make_cases(db, frozen["sut"], 3)
    url = f"{V1}/versions/{frozen['version']}/tasks"
    empty = client.post(url, json={"name": "Empty task"}).json()  # tasks may precede cases (AC-10)
    assert empty["cases"] == [] and empty["status"] == "draft"
    ordered = client.put(f"{V1}/tasks/{empty['id']}/cases", json={"case_ids": [c, a, b]}).json()
    assert [(x["seq"], x["id"]) for x in ordered["cases"]] == [(1, c), (2, a), (3, b)]
    reordered = client.put(f"{V1}/tasks/{empty['id']}/cases", json={"case_ids": [b, c]}).json()
    assert [x["id"] for x in reordered["cases"]] == [b, c]
    direct = client.post(url, json={"name": "Pick cases directly", "case_ids": [a, b]}).json()
    assert [x["id"] for x in direct["cases"]] == [a, b]
    assert client.put(f"{V1}/tasks/{empty['id']}/cases", json={"case_ids": [a, a]}).status_code == 422
    (dead,) = make_cases(db, frozen["sut"], 1, status="deprecated")
    assert client.put(f"{V1}/tasks/{empty['id']}/cases", json={"case_ids": [dead]}).status_code == 422
    listed = {t["name"]: t["case_count"] for t in client.get(url).json()}
    assert listed == {"Empty task": 2, "Pick cases directly": 2}


def test_invalid_cron_rejected(client, frozen):
    url = f"{V1}/versions/{frozen['version']}/tasks"
    bad = client.post(url, json={"name": "t", "schedule": {"type": "cron", "expr": "61 * * * *"}})
    assert bad.status_code == 422 and bad.json()["field_errors"][0]["field"] == "schedule.expr"
    six = client.post(url, json={"name": "t", "schedule": {"type": "cron", "expr": "0 0 * * * *"}})
    assert six.status_code == 422
    naive = client.post(url, json={"name": "t", "schedule": {"type": "once", "at": "2030-01-01T08:00"}})
    assert naive.status_code == 422
    ok = client.post(url, json={"name": "t", "schedule": {"type": "cron", "expr": "0 2 * * *"}}).json()
    assert ok["schedule"] == {"type": "cron", "expr": "0 2 * * *", "tz": "Asia/Shanghai"}
    assert ok["next_run_at"]
    once = client.post(url, json={"name": "o", "schedule": {"type": "once", "at": "2030-01-01T08:00:00+08:00"}}).json()
    fired = datetime.fromisoformat(once["next_run_at"])
    assert fired == datetime(2030, 1, 1, 0, 0, tzinfo=UTC)
    cleared = client.patch(f"{V1}/tasks/{ok['id']}", json={"schedule": None}).json()
    assert cleared["schedule"] is None and cleared["next_run_at"] is None


def test_next_run_cron_and_past_once():
    now = datetime(2026, 1, 1, 1, 30, tzinfo=UTC)
    assert next_run({"type": "cron", "expr": "0 2 * * *", "tz": "UTC"}, now) == datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    assert next_run({"type": "once", "at": "2025-01-01T00:00:00+00:00"}, now) is None


def test_cron_uses_schedule_timezone():
    # 08:30 in Shanghai (00:30 UTC): "0 9 * * *" fires at 09:00 Shanghai = 01:00 UTC today
    now = datetime(2026, 10, 31, 0, 30, tzinfo=UTC)
    sh = next_run({"type": "cron", "expr": "0 9 * * *", "tz": "Asia/Shanghai"}, now)
    assert sh == datetime(2026, 10, 31, 1, 0, tzinfo=UTC)
    assert sh.utcoffset() == timedelta(0)
    # same expression in UTC fires at 09:00 UTC
    assert next_run({"type": "cron", "expr": "0 9 * * *", "tz": "UTC"}, now) == datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
    # missing tz falls back to the built-in default (UTC) unless a zone is configured
    assert DEFAULT_TIMEZONE == "UTC"
    assert next_run({"type": "cron", "expr": "0 9 * * *"}, now) == datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
    assert next_run({"type": "cron", "expr": "0 9 * * *"}, now, default_tz="Asia/Shanghai") == sh
    # day boundaries are local: "0 0 * * *" is Shanghai midnight = 16:00 UTC
    assert next_run({"type": "cron", "expr": "0 0 * * *", "tz": "Asia/Shanghai"}, now) == (
        datetime(2026, 10, 31, 16, 0, tzinfo=UTC)
    )


def test_cron_dst_timezone():
    # America/New_York: 2026-11-01 DST ends; 09:00 local is 14:00 UTC after, 13:00 UTC before
    before = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    first = next_run({"type": "cron", "expr": "0 9 * * *", "tz": "America/New_York"}, before)
    assert first == datetime(2026, 10, 31, 13, 0, tzinfo=UTC)
    second = next_run({"type": "cron", "expr": "0 9 * * *", "tz": "America/New_York"}, first)
    assert second == datetime(2026, 11, 1, 14, 0, tzinfo=UTC)


def test_schedule_timezone_stored_and_validated(client, frozen):
    url = f"{V1}/versions/{frozen['version']}/tasks"
    utc = client.post(url, json={"name": "u", "schedule": {"type": "cron", "expr": "0 9 * * *", "tz": "UTC"}}).json()
    assert utc["schedule"]["tz"] == "UTC"
    nxt = datetime.fromisoformat(utc["next_run_at"])
    assert (nxt.astimezone(UTC).hour, nxt.minute) == (9, 0)
    local = client.post(url, json={"name": "l", "schedule": {"type": "cron", "expr": "0 9 * * *"}}).json()
    nxt = datetime.fromisoformat(local["next_run_at"]).astimezone(UTC)
    assert (nxt.hour, nxt.minute) == (1, 0)  # 09:00 Asia/Shanghai
    once = client.post(url, json={"name": "o", "schedule": {"type": "once", "at": "2030-01-01T08:00:00+08:00"}}).json()
    assert once["schedule"]["tz"] == "Asia/Shanghai"
    bad = client.post(url, json={"name": "b", "schedule": {"type": "cron", "expr": "0 9 * * *", "tz": "Mars/X"}})
    assert bad.status_code == 422 and bad.json()["field_errors"][0]["field"] == "schedule.tz"


def test_settings_general_exposes_timezone(client):
    assert client.get(f"{V1}/settings/general").json() == {"timezone": "Asia/Shanghai"}


def test_task_environment_must_match_sut(client, frozen):
    other = client.post(f"{V1}/suts", json={"code": "O", "name": "o"}).json()["id"]
    foreign = client.post(f"{V1}/suts/{other}/environments", json={"name": "e", "base_url": "http://x"}).json()["id"]
    url = f"{V1}/versions/{frozen['version']}/tasks"
    assert client.post(url, json={"name": "t", "environment_id": foreign}).status_code == 422
    task = client.post(url, json={"name": "t", "environment_id": frozen["env"]}).json()
    assert task["environment_id"] == frozen["env"]


def test_task_status_and_delete(client, frozen, db):
    url = f"{V1}/versions/{frozen['version']}/tasks"
    task = client.post(url, json={"name": "t"}).json()
    no_cases = client.post(f"{V1}/tasks/{task['id']}/status", json={"status": "ready"})
    assert no_cases.status_code == 422
    (case,) = make_cases(db, frozen["sut"], 1)
    client.put(f"{V1}/tasks/{task['id']}/cases", json={"case_ids": [case]})
    assert client.post(f"{V1}/tasks/{task['id']}/status", json={"status": "ready"}).json()["status"] == "ready"
    with db.tx() as cur:
        cur.execute("INSERT INTO task_run(task_id) VALUES (%s)", (task["id"],))
    assert client.delete(f"{V1}/tasks/{task['id']}").status_code == 409
    archived = client.post(f"{V1}/tasks/{task['id']}/status", json={"status": "archived"}).json()
    assert archived["status"] == "archived"
    assert client.patch(f"{V1}/tasks/{task['id']}", json={"name": "x"}).status_code == 409
    fresh = client.post(url, json={"name": "fresh"}).json()
    assert client.delete(f"{V1}/tasks/{fresh['id']}").status_code == 204
