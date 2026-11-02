"""M1-08 executors: selection, agent_browser (real Chromium + fake model), test repo automation,
pytest debug, manual results."""

import base64

import pytest
from tests.fixtures.mini_shop import MiniShop, browser_available

from testagent.agent.fake import FakeChatModel, call
from testagent.core.errors import AppError
from testagent.integrations.git_repo import TestRepo
from testagent.services.executions import ExecutionService, select_executor

V1 = "/api/v1"
needs_browser = pytest.mark.skipif(not browser_available(), reason="playwright chromium not installed")


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


@pytest.fixture
def shop():
    with MiniShop() as app:
        yield app


@pytest.fixture
def world(client):
    sut = client.post(f"{V1}/suts", json={"code": "SHOP", "name": "Shop"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1"}).json()["id"]
    req = client.post(f"{V1}/versions/{version}/requirements", json={"title": "Amount validation"}).json()
    case = client.post(
        f"{V1}/suts/{sut}/cases",
        json={
            "title": "Amount 0 shows an error",
            "steps": [{"action": "Enter amount 0 and submit", "expected": "Shows “Amount must be greater than 0”"}],
            "test_data": {"amount": 0},
            "expected": "Shows “Amount must be greater than 0”",
            "requirement_ids": [req["id"]],
        },
    ).json()
    return {"sut": sut, "version": version, "req": req, "case": case}


def env(client, world, base_url):
    return client.post(f"{V1}/suts/{world['sut']}/environments", json={"name": "test", "base_url": base_url}).json()[
        "id"
    ]


AMOUNT = {"label": "Amount"}
SUBMIT = {"role": "button", "name": "Submit"}
MSG = {"role": "status"}


def browse(*extra):
    return [
        call("browser_goto", {"url": "/"}, "c1"),
        call("browser_fill", {"target": AMOUNT, "value": "0"}, "c2"),
        call("browser_click", {"target": SUBMIT}, "c3"),
        *extra,
    ]


ASSERT = call("browser_assert", {"kind": "text", "target": MSG, "expected": "Amount must be greater than 0"}, "c4")
CLAIM_PASS = call("submit_result", {"claimed_status": "passed", "summary": "Looks all right"}, "c5")


def debug(client, world, env_id, executor="agent_browser"):
    resp = client.post(
        f"{V1}/cases/{world['case']['id']}/debug",
        json={"environment_id": env_id, "executor": executor},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ------------------------------------------------------------------ selection (T-08.1)
def test_executor_selection_matrix():
    f = "functional"
    assert select_executor("automated", "tests/R/test_a.py", f, "agent") == ("pytest", None)
    assert select_executor("automated", "tests/R/test_a.py", f, "human") == ("pytest", None)
    assert select_executor("manual", None, f, "agent") == ("agent_browser", None)
    assert select_executor("manual", None, f, "human") == ("manual", "blocked")
    assert select_executor("manual", None, f, "automation") == ("manual", "error")
    assert select_executor("automated", None, f, "agent") == ("agent_browser", None)
    assert select_executor("manual", None, "performance", "agent") == ("manual", "skipped")
    assert select_executor("automated", "t.py", "security", "agent") == ("pytest", "skipped")
    # boundary / exception are functional test design, not non-functional types
    for tag in ("boundary", "exception", "regression", "smoke", "validation", "idempotency"):
        assert select_executor("automated", "t.py", tag, "agent") == ("pytest", None), tag
        assert select_executor("manual", None, tag, "agent") == ("agent_browser", None), tag


# ------------------------------------------------------------------ agent_browser (T-08.3)
@needs_browser
def test_agent_exec_pass(client, world, shop):
    use_model(client, *browse(ASSERT, CLAIM_PASS))
    out = debug(client, world, env(client, world, shop.url))
    assert out["status"] == "passed", out
    assert out["task_run_id"] is None and out["executor"] == "agent_browser"
    steps = out["steps_recorded"]
    assert [s["action"] for s in steps] == ["goto", "fill", "click", "assert"]
    assert steps[1] == {**steps[1], "target": AMOUNT, "value": "0", "status": "ok"}
    assert all(s["screenshot_sha"] for s in steps)
    assert out["test_data"] == {"amount": 0} and out["agent_run_id"]
    kinds = {a["kind"] for a in out["artifacts"]}
    assert kinds == {"trace", "screenshot"}
    shot = client.get(f"{V1}/artifacts/{steps[0]['screenshot_sha']}")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"


@needs_browser
def test_agent_exec_detects_injected_bug(client, world, shop):
    use_model(
        client,
        *browse(ASSERT),
        call("submit_result", {"claimed_status": "failed", "summary": "Wrong message"}, "c5"),
    )
    out = debug(client, world, env(client, world, shop.url + "/bug/"))
    assert out["status"] == "failed"
    assert (
        "Amount must be greater than 0" in out["failed_assertion"]
        and "Submitted successfully" in out["failed_assertion"]
    )
    assert out["test_data"] == {"amount": 0}


@needs_browser
def test_no_assertion_is_error(client, world, shop):
    use_model(client, *browse(CLAIM_PASS))
    out = debug(client, world, env(client, world, shop.url))
    assert out["status"] == "error" and "NO_ASSERTION" in out["error"]


@needs_browser
def test_agent_claim_pass_ignored(client, world, shop):
    use_model(client, *browse(ASSERT, CLAIM_PASS))
    out = debug(client, world, env(client, world, shop.url + "/bug/"))
    assert out["status"] == "failed" and out["result"] == "Looks all right"


def test_agent_exec_requires_model(client, world):
    resp = client.post(
        f"{V1}/cases/{world['case']['id']}/debug",
        json={
            "environment_id": env(client, world, "http://127.0.0.1:9"),
            "executor": "agent_browser",
        },
    )
    assert resp.status_code == 503
    assert client.get(f"{V1}/cases/{world['case']['id']}/executions").json() == []


# ------------------------------------------------------------------ automation (T-08.4/5)
def repo_of(client) -> TestRepo:
    return TestRepo(client.app.state.repos_root, "SHOP")


TEST_CODE = "def test_amount(test_data):\n    assert test_data['amount'] == 0\n"


def test_automate_commits_and_binds_case(client, world):
    env_id = env(client, world, "http://127.0.0.1:9")
    use_model(
        client,
        call("write_test_file", {"content": TEST_CODE}, "w1"),
        call("run_pytest", {}, "p1"),
        call("submit_result", {"summary": "Generated"}, "s1"),
    )
    out = client.post(f"{V1}/cases/{world['case']['id']}/automate", json={"environment_id": env_id}).json()
    assert out["status"] == "succeeded", out
    assert out["code_path"] == "tests/REQ-001/test_TC-001.py"
    repo = repo_of(client)
    assert out["code_commit"] == repo.head()
    log = repo.git("log", "-1", "--format=%an <%ae>|%s").stdout.strip()
    assert log == "TestAgent <agent@local>|testagent: TC-001 Amount 0 shows an error"
    case = client.get(f"{V1}/cases/{world['case']['id']}").json()
    assert case["mode"] == "automated" and case["code_path"] == out["code_path"]
    assert case["code_commit"] == out["code_commit"]
    assert case["automation_status"] == "ok" and case["automation_note"] is None
    assert case["code_abs_path"].replace("\\", "/").endswith("SHOP/tests/REQ-001/test_TC-001.py")
    code = client.get(f"{V1}/cases/{world['case']['id']}/code").json()
    assert code["content"] == TEST_CODE and code["commit"] == out["code_commit"]
    # the bound code runs through the pytest executor (single-case debug)
    result = debug(client, world, env_id, executor="auto")
    assert result["executor"] == "pytest" and result["status"] == "passed", result
    assert result["code_commit"] == out["code_commit"]
    test = result["report"]["tests"][0]  # readable report
    assert test["outcome"] == "passed" and test["data_used"] == {"amount": 0}
    check = test["steps"][0]["events"][0]
    assert check["type"] == "check" and check["passed"] and check["actual"] == "0"


FAILING_CODE = "def test_amount(test_data):\n    assert test_data['amount'] == 1\n"


def test_automate_failed_self_check_marks_needs_fix(client, world):
    """5b: a script whose last self-check fails is committed as a draft but never bound."""
    env_id = env(client, world, "http://127.0.0.1:9")
    use_model(
        client,
        call("write_test_file", {"content": FAILING_CODE}, "w1"),
        call("run_pytest", {}, "p1"),
        call("submit_result", {"summary": "Generated"}, "s1"),
    )
    cid = world["case"]["id"]
    out = client.post(f"{V1}/cases/{cid}/automate", json={"environment_id": env_id}).json()
    assert out["status"] == "needs_fix" and out["error_code"] == "SELF_CHECK_FAILED", out
    case = client.get(f"{V1}/cases/{cid}").json()
    assert case["mode"] == "manual" and case["code_path"] is None
    assert case["automation_status"] == "needs_fix" and "assert" in case["automation_note"]
    assert case["automation_draft_path"] == "tests/REQ-001/test_TC-001.py"
    assert case["draft_abs_path"]
    draft = client.get(f"{V1}/cases/{cid}/code", params={"draft": True}).json()
    assert draft["content"] == FAILING_CODE
    assert client.get(f"{V1}/cases/{cid}/code").status_code == 404
    assert repo_of(client).dirty_files() == []


def test_automate_without_check_is_not_bound(client, world):
    use_model(
        client,
        call("write_test_file", {"content": TEST_CODE}, "w1"),
        call("submit_result", {"summary": "Generated"}, "s1"),
    )
    out = client.post(f"{V1}/cases/{world['case']['id']}/automate", json={}).json()
    assert out["status"] == "needs_fix", out
    case = client.get(f"{V1}/cases/{world['case']['id']}").json()
    assert case["mode"] == "manual" and case["automation_status"] == "needs_fix"


def test_automate_probe_file_rejected(client, world):
    env_id = env(client, world, "http://127.0.0.1:9")
    use_model(
        client,
        call(
            "write_test_file",
            {"content": TEST_CODE, "path": "tests/REQ-001/test_TC-001_probe.py"},
            "w0",
        ),
        call("write_test_file", {"content": TEST_CODE}, "w1"),
        call("run_pytest", {}, "p1"),
        call("submit_result", {"summary": "Generated"}, "s1"),
    )
    out = client.post(f"{V1}/cases/{world['case']['id']}/automate", json={"environment_id": env_id}).json()
    assert out["status"] == "succeeded", out
    run = client.get(f"{V1}/agent/runs/{out['agent_run_id']}").json()
    first = [s for s in run["steps"] if s["type"] == "tool"][0]
    assert first["status"] == "error"
    files = repo_of(client).git("ls-files").stdout
    assert "probe" not in files


def test_automate_write_outside_tests_rejected(client, world):
    use_model(
        client,
        call("write_test_file", {"content": "x = 1\n", "path": "../evil.py"}, "w1"),
        call("submit_result", {"summary": "done"}, "s1"),
    )
    out = client.post(f"{V1}/cases/{world['case']['id']}/automate", json={}).json()
    assert out["status"] == "failed" and out["error_code"] == "NO_TEST_FILE"
    run = client.get(f"{V1}/agent/runs/{out['agent_run_id']}").json()
    tool = [s for s in run["steps"] if s["type"] == "tool"][0]
    assert tool["status"] == "error" and "tests/" in tool["result"]
    assert not (repo_of(client).path.parent / "evil.py").exists()


def test_automate_on_dirty_repo_409(client, world):
    repo = repo_of(client)
    repo.ensure()
    (repo.path / "conftest.py").write_text("# local edit\n", encoding="utf-8")
    use_model(client)
    resp = client.post(f"{V1}/cases/{world['case']['id']}/automate", json={})
    assert resp.status_code == 409 and resp.json()["code"] == "REPO_DIRTY"
    assert resp.json()["related"] == ["conftest.py"]


def test_debug_execution_has_no_run(client, world, db):
    repo = repo_of(client)
    repo.ensure()
    rel = repo.write("tests/REQ-001/test_TC-001.py", TEST_CODE)
    repo.git("add", rel)
    repo.git("-c", "user.name=Tester", "-c", "user.email=t@local", "commit", "-q", "-m", "hand")
    bound = client.post(f"{V1}/cases/{world['case']['id']}/bind-code", json={"code_path": rel})
    assert bound.status_code == 200 and bound.json()["code_commit"] == repo.head()
    out = debug(client, world, env(client, world, "http://127.0.0.1:9"), executor="pytest")
    assert out["status"] == "passed" and out["task_run_id"] is None
    with db.tx() as cur:
        cur.execute("SELECT count(*) AS n FROM task_run")
        assert cur.fetchone()["n"] == 0
    listed = client.get(f"{V1}/cases/{world['case']['id']}/executions").json()
    assert [e["id"] for e in listed] == [out["id"]]


# ------------------------------------------------------------------ manual (T-08.7)
def test_manual_execution_recorded(client, world, db):
    photo = base64.b64encode(b"\x89PNG fake screenshot").decode()
    resp = client.post(
        f"{V1}/cases/{world['case']['id']}/executions/manual",
        json={
            "status": "failed",
            "result": "The message says “Submitted successfully”",
            "failed_assertion": "Should say the amount must be greater than 0",
            "actual_data": {"amount": 0, "browser": "Edge"},
            "attachments": [{"name": "screenshot.png", "content_base64": photo}],
        },
    )
    assert resp.status_code == 201, resp.text
    ex = resp.json()
    assert ex["executor"] == "manual" and ex["status"] == "failed"
    assert ex["executed_by"] == "local-user" and ex["task_run_id"] is None
    assert ex["test_data"] == {"amount": 0, "browser": "Edge"} and ex["ended_at"]
    sha = ex["artifacts"][0]["sha256"]
    assert client.get(f"{V1}/artifacts/{sha}").content == b"\x89PNG fake screenshot"
    agent = ExecutionService(db, client.app.state.bus, actor="agent:x")
    with pytest.raises(AppError):
        agent.record_manual(world["case"]["id"], {"status": "passed"})
