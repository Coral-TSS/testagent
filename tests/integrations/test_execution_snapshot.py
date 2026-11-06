"""Execution provenance: real Git repositories and pytest subprocesses, no model or DB."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.executions import ExecutionService


@pytest.fixture
def world(tmp_path):
    service = ExecutionService(None, EventBus(), repos_root=tmp_path / "repos", pytest_timeout_s=30)
    repo = service.repo_for("SNAPSHOT", "snapshot-sut")
    repo.ensure()
    return service, repo


def run(service, rel, commit, data=None):
    return service._pytest(
        {
            "sut_code": "SNAPSHOT",
            "sut_id": "snapshot-sut",
            "code_path": rel,
            "code_commit": commit,
            "test_data": data or {},
        },
        {"base_url": "http://127.0.0.1:9"},
    )


def test_uncommitted_pass_cannot_replace_a_bound_failure(world):
    service, repo = world
    rel = repo.write("tests/R/test_bound.py", "def test_bound():\n    assert False\n")
    bound = repo.commit_files([rel], "bind failing test")
    repo.write(rel, "def test_bound():\n    assert True\n")
    result = run(service, rel, bound)
    assert result["status"] == "failed"
    assert result["code_commit"] == bound
    assert result["_script_unchanged"] is True
    assert repo.head() == bound
    assert (repo.path / rel).read_text().endswith("assert True\n")
    assert rel in repo.dirty_files()


def test_bound_execution_uses_the_bound_conftest_and_helpers(world):
    service, repo = world
    (repo.path / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef answer():\n    return 7\n", encoding="utf-8"
    )
    rel = repo.write("tests/R/test_helper.py", "def test_helper(answer):\n    assert answer == 7\n")
    repo.git("add", "conftest.py", rel)
    bound = repo._commit("bind fixture and test")
    (repo.path / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef answer():\n    return 99\n", encoding="utf-8"
    )
    result = run(service, rel, bound)
    assert result["status"] == "passed"
    assert result["code_commit"] == bound
    assert "99" in (repo.path / "conftest.py").read_text()


def test_a_newer_committed_script_does_not_change_the_bound_run(world):
    service, repo = world
    rel = repo.write("tests/R/test_old.py", "def test_old():\n    assert False\n")
    bound = repo.commit_files([rel], "bound failure")
    repo.write(rel, "def test_old():\n    assert True\n")
    current = repo.commit_files([rel], "new unbound version")
    result = run(service, rel, bound)
    assert result["status"] == "failed"
    assert result["code_commit"] == bound
    assert repo.head() == current


def test_deleting_working_file_does_not_delete_its_bound_version(world):
    service, repo = world
    rel = repo.write("tests/R/test_deleted.py", "def test_deleted():\n    assert True\n")
    bound = repo.commit_files([rel], "bound test")
    (repo.path / rel).unlink()
    result = run(service, rel, bound)
    assert result["status"] == "passed"
    assert result["code_commit"] == bound
    assert not (repo.path / rel).exists()


def test_unavailable_bound_commit_does_not_fall_back_to_head(world):
    service, repo = world
    rel = repo.write("tests/R/test_unavailable.py", "def test_unavailable():\n    assert True\n")
    repo.commit_files([rel], "current test")
    with pytest.raises(AppError) as error:
        run(service, rel, "1" * 40)
    assert error.value.code == "NOT_FOUND"


def test_legacy_unbound_execution_pins_starting_head(world):
    service, repo = world
    rel = repo.write("tests/R/test_legacy.py", "def test_legacy():\n    assert False\n")
    initial = repo.commit_files([rel], "legacy committed version")
    repo.write(rel, "def test_legacy():\n    assert True\n")
    result = run(service, rel, None)
    assert result["status"] == "failed"
    assert result["code_commit"] == initial
    assert result["_script_unchanged"] is False


def test_head_change_while_running_cannot_change_recorded_commit(world, tmp_path):
    service, repo = world
    start, proceed = tmp_path / "started", tmp_path / "proceed"
    rel = repo.write(
        "tests/R/test_concurrent.py",
        """import time
from pathlib import Path
def test_concurrent(test_data):
    Path(test_data['start']).write_text('started')
    deadline = time.monotonic() + 15
    while not Path(test_data['proceed']).exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert Path(test_data['proceed']).exists()
""",
    )
    initial = repo.commit_files([rel], "start concurrent test")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run, service, rel, initial, {"start": str(start), "proceed": str(proceed)})
        try:
            deadline = time.monotonic() + 15
            while not start.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert start.exists(), "pytest did not reach the synchronization point"
            other = repo.write("tests/R/test_new.py", "def test_new():\n    assert True\n")
            new_head = repo.commit_files([other], "another commit during execution")
        finally:
            proceed.write_text("continue")
        result = future.result(timeout=30)
    assert result["status"] == "passed"
    assert result["code_commit"] == initial
    assert repo.head() == new_head


@pytest.mark.parametrize("raise_inside", [False, True])
def test_snapshot_cleanup_preserves_original_repository(world, raise_inside):
    _, repo = world
    original = repo.head()
    error = RuntimeError("test interrupted")
    propagated = None
    try:
        with repo.execution_snapshot(original) as snapshot:
            snapshot_path = snapshot.path
            assert snapshot_path.resolve() != repo.path.resolve()
            assert (snapshot_path / "conftest.py").is_file()
            assert snapshot.commit == original
            if raise_inside:
                raise error
    except RuntimeError as caught:
        propagated = caught
    assert propagated is (error if raise_inside else None)
    assert not snapshot_path.exists()
    assert repo.head() == original
    assert repo.dirty_files() == []
