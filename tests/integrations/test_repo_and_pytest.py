"""T-08.4 test repository and T-08.6 pytest executor (real git and pytest subprocesses)."""

import time

import pytest
from tests.fixtures.mini_shop import MiniShop, browser_available

from testagent.core.artifacts import ArtifactStore
from testagent.core.errors import AppError
from testagent.integrations.git_repo import TestRepo, target_test_path
from testagent.integrations.pytest_runner import run_pytest


@pytest.fixture
def repo(tmp_path):
    return TestRepo(tmp_path / "repos", "SHOP", "sut-1")


def test_repo_initialized_with_template(repo):
    info = repo.ensure()
    assert info["initialized"] and info["dirty"] == [] and len(info["head"]) == 40
    for rel in ("pyproject.toml", "pytest.ini", "conftest.py", ".testagent.json", "tests/.gitkeep"):
        assert (repo.path / rel).exists(), rel
    assert '"sut_id": "sut-1"' in (repo.path / ".testagent.json").read_text(encoding="utf-8")
    log = repo.git("log", "--format=%an <%ae>|%s").stdout.strip()
    assert log == "TestAgent <agent@local>|testagent: initialize test repository"
    assert repo.ensure()["head"] == info["head"]  # idempotent


def test_write_outside_tests_rejected(repo):
    repo.ensure()
    for bad in ("conftest.py", "../evil.py", "tests/../conftest.py", "/tmp/x.py", "tests/a.txt"):
        with pytest.raises(AppError) as err:
            repo.write(bad, "x = 1\n")
        assert err.value.code == "VALIDATION", bad
    assert repo.write("tests/REQ-001/test_TC-001.py", "x = 1\n") == "tests/REQ-001/test_TC-001.py"


def test_dirty_repo_blocks_commit(repo):
    repo.ensure()
    (repo.path / "conftest.py").write_text("# hand edit\n", encoding="utf-8")
    rel = repo.write("tests/REQ-001/test_TC-001.py", "def test_ok():\n    assert True\n")
    with pytest.raises(AppError) as err:
        repo.commit_files([rel], "testagent: TC-001")
    assert err.value.code == "REPO_DIRTY" and err.value.related == ["conftest.py"]
    repo.git("checkout", "--", "conftest.py")
    sha = repo.commit_files([rel], "testagent: TC-001 x")
    assert sha == repo.head() and repo.dirty_files() == []


def test_path_uses_first_requirement_code():
    assert target_test_path("TC-007", ["REQ-002", "REQ-001"]) == "tests/REQ-002/test_TC-007.py"
    assert target_test_path("TC-008", []) == "tests/_unlinked/test_TC-008.py"


PASS_FAIL = """
def test_ok(test_data):
    assert test_data["amount"] == 0


def test_total():
    total = 1 + 1
    assert total == 3, "Total should be 3"
"""


def test_pytest_results_parsed(repo, tmp_path):
    repo.ensure()
    ok = repo.write("tests/R/test_ok.py", "def test_ok(test_data):\n    assert test_data['a'] == 1\n")
    out = run_pytest(repo.path, ok, base_url="http://127.0.0.1:9", test_data={"a": 1}, browser=False)
    assert out["status"] == "passed", out["output"]
    missing = run_pytest(repo.path, "tests/R/test_none.py", base_url="http://x", browser=False)
    assert missing["status"] == "error"


def test_failed_assertion_extracted(repo):
    repo.ensure()
    rel = repo.write("tests/R/test_mixed.py", PASS_FAIL)
    out = run_pytest(repo.path, rel, base_url="http://127.0.0.1:9", test_data={"amount": 0}, browser=False)
    assert out["status"] == "failed"
    assert "test_total" in out["failed_assertion"] and "Total should be 3" in out["failed_assertion"]


def test_timeout_kills_process(repo):
    repo.ensure()
    rel = repo.write("tests/R/test_slow.py", "import time\n\ndef test_slow():\n    time.sleep(60)\n")
    started = time.monotonic()
    out = run_pytest(repo.path, rel, base_url="http://x", timeout_s=3, browser=False)
    assert out["status"] == "error" and out["error"].startswith("TIMEOUT")
    assert time.monotonic() - started < 30


@pytest.mark.skipif(not browser_available(), reason="playwright chromium not installed")
def test_pytest_playwright_against_fixture_app(repo, tmp_path):
    repo.ensure()
    code = """
def test_zero_rejected(page, test_data):
    page.goto("")
    page.get_by_label("Amount").fill(str(test_data["amount"]))
    page.get_by_role("button", name="Submit").click()
    assert page.get_by_role("status").inner_text() == "Amount must be greater than 0"
"""
    rel = repo.write("tests/REQ-001/test_TC-001.py", code)
    store = ArtifactStore(tmp_path / "art")
    with MiniShop() as shop:
        ok = run_pytest(repo.path, rel, base_url=shop.url + "/", test_data={"amount": 0}, artifacts=store)
        bad = run_pytest(repo.path, rel, base_url=shop.url + "/bug/", test_data={"amount": 0}, artifacts=store)
    assert ok["status"] == "passed", ok["output"]
    assert bad["status"] == "failed" and "Submitted successfully" in bad["failed_assertion"]
    assert {a["kind"] for a in bad["artifacts"]} >= {"trace", "screenshot"}
