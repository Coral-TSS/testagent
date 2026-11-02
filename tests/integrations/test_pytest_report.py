"""readable pytest report: steps from comments or step(), API requests, assertions with
expected/actual, plain-language error explanation, test data keys, page actions; template upgrade."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from tests.fixtures.mini_shop import MiniShop, browser_available

from testagent.integrations.git_repo import CONFTEST, CONFTEST_V1, TestRepo
from testagent.integrations.pytest_report import assertion_event, explain_error
from testagent.integrations.pytest_runner import run_pytest


class _Api(BaseHTTPRequestHandler):
    orders: dict = {}

    def _send(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):  # noqa: N802
        size = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(size) or b"{}")
        if self.path == "/orders":
            state = "pending" if body.get("amount_minor", 0) >= 5000000 else "approved"
            self._send(201, {"id": "o-1", "state": state, "amount_minor": body["amount_minor"]})
        else:
            self._send(404, {"detail": "not found"})

    def do_GET(self):  # noqa: N802
        self._send(200, {"id": "o-1", "state": "pending"})

    def log_message(self, *args):
        pass


@pytest.fixture
def api_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


@pytest.fixture
def repo(tmp_path):
    repo = TestRepo(tmp_path / "repos", "SHOP", "sut-1")
    repo.ensure()
    return repo


COMMENT_STYLE = '''"""TC-001 Large purchase order goes to pending approval"""
import pytest


@pytest.fixture
def api(playwright, base_url):
    ctx = playwright.request.new_context(base_url=base_url)
    yield ctx
    ctx.dispose()


def test_large_order(api, test_data):
    # Setup: prepare data
    amount = test_data["amount_minor"]

    # Step 1: create purchase order
    created = api.post("orders", data={"amount_minor": amount})
    assert created.status == 201, created.text()
    order = created.json()

    # Step 2: check state
    assert order["state"] == test_data.get("expected_state")
'''


def test_comment_steps_requests_and_assertions(repo, api_url):
    rel = repo.write("tests/R/test_TC-001.py", COMMENT_STYLE)
    data = {"amount_minor": 6000000, "expected_state": "pending", "unused": 1}
    ok = run_pytest(repo.path, rel, base_url=api_url, test_data=data, browser=False)
    assert ok["status"] == "passed", ok["output"]
    test = ok["report"]["tests"][0]
    assert test["outcome"] == "passed" and test["title"] is None
    names = [s["name"] for s in test["steps"]]
    assert names == ["Setup: prepare data", "Step 1: create purchase order", "Step 2: check state"]
    create = test["steps"][1]["events"]
    request = next(e for e in create if e["type"] == "request")
    assert request["method"] == "POST" and request["status"] == 201
    assert request["url"].endswith("/orders") and '"amount_minor": 6000000' in request["request"]
    assert '"state": "pending"' in request["response"]
    status_check = next(e for e in create if e["type"] == "check")
    assert status_check["passed"] and status_check["subject"] == "created.status"
    assert status_check["expected"] == "201" and status_check["actual"] == "201"
    final = test["steps"][2]["events"][0]
    assert final["passed"] and final["actual"] == "'pending'"
    assert test["checks"] == {"total": 2, "failed": 0} and test["requests"] == 1
    assert test["data_keys"] == ["amount_minor", "expected_state"]
    assert test["data_used"] == {"amount_minor": 6000000, "expected_state": "pending"}
    assert not (repo.path / "tests" / "R" / "__pycache__").exists()  # pyc kept out of the repo

    bad = run_pytest(repo.path, rel, base_url=api_url, test_data={**data, "amount_minor": 100}, browser=False)
    assert bad["status"] == "failed"
    test = bad["report"]["tests"][0]
    assert test["outcome"] == "failed"
    failed_step = test["steps"][2]
    assert failed_step["status"] == "failed"
    check = failed_step["events"][-1]
    assert check["passed"] is False
    assert check["actual"] == "'approved'"
    assert test["failure"]["explain"].startswith("expected order['state'] equals")
    assert "got 'approved'" in test["failure"]["explain"]


STEP_STYLE = """
import pytest


@pytest.fixture
def api(playwright, base_url):
    ctx = playwright.request.new_context(base_url=base_url)
    yield ctx
    ctx.dispose()


def test_named(api, step, check):
    with step("Create a large purchase order"):
        resp = api.post("orders", data={"amount_minor": 6000000})
        check("returns 201", resp.status, 201)
    with step("Query and verify the state"):
        order = api.get("orders/o-1").json()
        check("State is approved", order["state"], "approved")
"""


def test_step_and_check_helpers(repo, api_url):
    assert (repo.path / "conftest.py").read_text(encoding="utf-8") == CONFTEST
    rel = repo.write("tests/R/test_TC-002.py", STEP_STYLE)
    out = run_pytest(repo.path, rel, base_url=api_url, browser=False)
    assert out["status"] == "failed"
    test = out["report"]["tests"][0]
    assert [s["name"] for s in test["steps"]] == ["Create a large purchase order", "Query and verify the state"]
    assert [s["status"] for s in test["steps"]] == ["passed", "failed"]
    first, second = test["steps"]
    assert [e["type"] for e in first["events"]] == ["request", "check"]
    check = second["events"][-1]
    assert check["name"] == "State is approved" and check["passed"] is False
    assert (check["expected"], check["actual"]) == ("'approved'", "'pending'")
    assert check["explain"] == "State is approved: expected equals 'approved', got 'pending'"
    assert len([e for e in second["events"] if e["type"] == "check"]) == 1  # not twice
    # outside TestAgent (no plugin) the helpers still assert
    plain = repo.write("tests/R/test_plain.py", "def test_p(check):\n    check('x', 1, 2)\n")
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", plain],
        cwd=repo.path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 1 and "expected == 2, got 1" in proc.stdout


def test_error_explanations():
    assert "Cannot connect to the SUT" in explain_error("Error", "connect ECONNREFUSED 127.0.0.1:1")
    assert "Data has no field" in explain_error("KeyError", "'state'")
    assert "timed out" in explain_error("TimeoutError", 'waiting for locator("#ok")')
    event = assertion_event("resp.status == 201", "assert 409 == 201", False)
    assert event["explain"] == "API returned status code 409, expected equals 201"


def test_template_upgrade_keeps_hand_edits(tmp_path):
    repo = TestRepo(tmp_path / "repos", "OLD", "sut-9")
    repo.path.mkdir(parents=True)
    (repo.path / "conftest.py").write_text(CONFTEST_V1, encoding="utf-8")
    (repo.path / ".testagent.json").write_text(
        '{"sut_id": "sut-9", "sut_code": "OLD", "template": 1}', encoding="utf-8"
    )
    (repo.path / "notes.txt").write_text("mine", encoding="utf-8")
    repo.git("init", "-q")
    repo.git("add", "-A")
    repo._commit("old")
    (repo.path / "notes.txt").write_text("uncommitted edit", encoding="utf-8")
    repo.ensure()
    assert (repo.path / "conftest.py").read_text(encoding="utf-8") == CONFTEST
    assert json.loads((repo.path / ".testagent.json").read_text("utf-8"))["template"] == 2
    assert repo.dirty_files() == ["notes.txt"]  # the user's edit is neither lost nor committed
    log = repo.git("log", "--format=%s").stdout.splitlines()
    assert log[0] == "testagent: template v2 (step/check helpers)"
    assert repo.upgrade() == []  # idempotent

    edited = TestRepo(tmp_path / "repos", "EDIT", "sut-8")
    edited.path.mkdir(parents=True)
    (edited.path / "conftest.py").write_text("# my own fixtures\n", encoding="utf-8")
    (edited.path / ".testagent.json").write_text('{"template": 1}', encoding="utf-8")
    edited.git("init", "-q")
    edited.git("add", "-A")
    edited._commit("old")
    assert edited.upgrade() == [".testagent.json"]
    assert (edited.path / "conftest.py").read_text(encoding="utf-8") == "# my own fixtures\n"


@pytest.mark.skipif(not browser_available(), reason="playwright chromium not installed")
def test_page_actions_and_expect(repo):
    code = """
from playwright.sync_api import expect


def test_zero_rejected(page, test_data):
    # Step 1: enter amount and submit
    page.goto("")
    page.get_by_label("Amount").fill(str(test_data["amount"]))
    page.get_by_role("button", name="Submit").click()
    # Step 2: check the message
    expect(page.get_by_role("status")).to_have_text("Amount must be greater than 0")
"""
    rel = repo.write("tests/R/test_ui.py", code)
    with MiniShop() as shop:
        out = run_pytest(repo.path, rel, base_url=shop.url + "/bug/", test_data={"amount": 0})
    test = out["report"]["tests"][0]
    assert out["status"] == "failed"
    actions = [(e["action"], e.get("value")) for e in test["steps"][0]["events"]]
    assert actions == [("Open", None), ("Fill", "0"), ("Click", None)]
    check = test["steps"][1]["events"][0]
    assert check["passed"] is False and "to_have_text" in check["name"]
    assert check["expected"] == "'Amount must be greater than 0'"
