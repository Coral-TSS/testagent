"""Per-SUT local git test repository (architecture §6): template, guarded writes, commits.

git is called through its CLI with argument lists (no shell). Commits use the TestAgent identity
via `-c` flags and never touch the user's git configuration."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from testagent.core.errors import AppError

TEMPLATE_VERSION = 2
AGENT_IDENTITY = ("TestAgent", "agent@local")

# template v1 conftest (kept to recognise untouched files when upgrading a repo to v2)
CONFTEST_V1 = '''"""Shared fixtures; base_url comes from pytest-base-url (--base-url)."""

import json
import os

import pytest


@pytest.fixture(scope="session")
def test_data() -> dict:
    """The case's test data, passed by TestAgent as JSON in TESTAGENT_DATA."""
    return json.loads(os.environ.get("TESTAGENT_DATA") or "{}")
'''

CONFTEST = '''"""Shared fixtures; base_url comes from pytest-base-url (--base-url).

- test_data: the case's test data (TestAgent passes it as JSON in TESTAGENT_DATA).
- step("step name"): context manager naming a test step; TestAgent shows the requests, page
  actions and assertions of each step in the run report.
- check("description", actual, expected, op="=="): a named assertion with expected vs actual in the
  report. Outside TestAgent both still work (check() is a normal assertion).
"""

import contextlib
import json
import operator
import os
import sys

import pytest

_PLUGIN = "testagent.integrations.pytest_report"
_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "in": lambda a, b: a in b,
    "not in": lambda a, b: a not in b,
    "contains": lambda a, b: b in a,
    "is": operator.is_,
    "is not": operator.is_not,
}


@pytest.fixture(scope="session")
def test_data() -> dict:
    """The case's test data, passed by TestAgent as JSON in TESTAGENT_DATA."""
    return json.loads(os.environ.get("TESTAGENT_DATA") or "{}")


@pytest.fixture
def step():
    @contextlib.contextmanager
    def _step(name: str):
        plugin = sys.modules.get(_PLUGIN)
        if plugin is None:
            yield
            return
        with plugin.step(name):
            yield

    return _step


@pytest.fixture
def check():
    def _check(name: str, actual, expected=True, op: str = "=="):
        passed = bool(_OPS[op](actual, expected))
        plugin = sys.modules.get(_PLUGIN)
        if plugin is not None:
            plugin.check(name, actual, expected, op, passed)
        if not passed:
            err = AssertionError(f"{name}: expected {op} {expected!r}, got {actual!r}")
            err._ta_recorded = True
            raise err
        return actual

    return _check
'''

TEMPLATE = {
    "pyproject.toml": """[project]
name = "testagent-tests-{code_lower}"
version = "0.1.0"
requires-python = ">=3.12"
# Executed by the TestAgent platform with its own pinned pytest / pytest-playwright / playwright.
dependencies = ["pytest>=8.3", "pytest-playwright>=0.7", "playwright>=1.50"]
""",
    "pytest.ini": """[pytest]
testpaths = tests
addopts = --import-mode=importlib
""",
    "conftest.py": CONFTEST,
    ".gitignore": "__pycache__/\n.pytest_cache/\ntest-results/\n",
    "tests/.gitkeep": "",
    "pages/.gitkeep": "",
}


def target_test_path(case_code: str, requirement_codes: list[str]) -> str:
    """tests/<first requirement code>/test_<case code>.py (no requirement: tests/_unlinked/)."""
    folder = requirement_codes[0] if requirement_codes else "_unlinked"
    return f"tests/{_safe(folder)}/test_{_safe(case_code)}.py"


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", part)


def _test_path(root: Path, rel: str) -> str:
    candidate = PurePosixPath(str(rel).replace("\\", "/"))
    resolved = (root / candidate).resolve()
    tests = (root / "tests").resolve()
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or not resolved.is_relative_to(tests)
        or resolved.suffix != ".py"
    ):
        raise AppError("VALIDATION", f"Only .py files under tests/ in the test repo can be used: {rel}")
    return resolved.relative_to(root.resolve()).as_posix()


@dataclass(frozen=True)
class ExecutionSnapshot:
    path: Path
    commit: str

    def resolve_test_path(self, rel: str) -> str:
        return _test_path(self.path, rel)


class TestRepo:
    __test__ = False  # not a pytest test class

    def __init__(self, root: Path, sut_code: str, sut_id: str | None = None):
        self.path = Path(root) / _safe(sut_code)
        self.sut_code = sut_code
        self.sut_id = sut_id

    # ------------------------------------------------------------ git
    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=60,
        )
        if check and proc.returncode != 0:
            raise AppError("CONFLICT", f"git {args[0]} Failed: {(proc.stderr or proc.stdout).strip()[:300]}")
        return proc

    def _commit(self, message: str) -> str:
        name, email = AGENT_IDENTITY
        self.git(
            "-c", f"user.name={name}", "-c", f"user.email={email}", "-c", "commit.gpgsign=false",
            "commit", "-q", "--no-verify", "-m", message,
        )  # fmt: skip
        return self.head()

    @property
    def initialized(self) -> bool:
        return (self.path / ".git").exists()

    def ensure(self) -> dict:
        if not self.initialized:
            self.path.mkdir(parents=True, exist_ok=True)
            for rel, content in TEMPLATE.items():
                target = self.path / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_text(self._render(rel, content), encoding="utf-8")
            self._write_meta()
            self.git("init", "-q")
            self.git("add", "-A")
            self._commit("testagent: initialize test repository")
        else:
            self.upgrade()
        return self.info()

    def _render(self, rel: str, content: str) -> str:
        if rel == "pyproject.toml":
            return content.format(code_lower=self.sut_code.lower())
        return content

    def _meta(self) -> dict:
        try:
            return json.loads((self.path / ".testagent.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_meta(self) -> None:
        meta = {**self._meta(), "sut_id": self.sut_id, "sut_code": self.sut_code}
        meta["template"] = TEMPLATE_VERSION
        if meta.get("sut_id") is None:
            meta["sut_id"] = self._meta().get("sut_id")
        (self.path / ".testagent.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def upgrade(self) -> list[str]:
        """Bring an older template up to date (step/check helpers in conftest.py). Only
        files still identical to the old template are replaced; hand-edited files are kept.
        Commits just those files, so unrelated uncommitted edits stay untouched."""
        meta = self._meta()
        if int(meta.get("template") or 1) >= TEMPLATE_VERSION:
            return []
        changed = []
        conftest = self.path / "conftest.py"
        current = conftest.read_text(encoding="utf-8") if conftest.exists() else None
        if current is None or current.replace("\r\n", "\n") == CONFTEST_V1:
            conftest.write_text(CONFTEST, encoding="utf-8")
            changed.append("conftest.py")
        if self.sut_id is None:
            self.sut_id = meta.get("sut_id")
        self._write_meta()
        changed.append(".testagent.json")
        self.git("add", "--", *changed)
        name, email = AGENT_IDENTITY
        self.git(
            "-c", f"user.name={name}", "-c", f"user.email={email}", "-c", "commit.gpgsign=false",
            "commit", "-q", "--no-verify", "-m",
            f"testagent: template v{TEMPLATE_VERSION} (step/check helpers)", "--", *changed,
        )  # fmt: skip
        return changed

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    @contextmanager
    def execution_snapshot(self, commit: str | None = None):
        """An independent local checkout: no network, shared working tree or hardlinked objects.

        Resolve the full commit once before cloning. Legacy unbound cases use starting HEAD;
        an unavailable binding is an error, never an implicit request to execute newer code.
        """
        if commit is not None and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise AppError("VALIDATION", "The bound test version must be a full Git commit hash")
        resolved = self.git("rev-parse", "--verify", "--end-of-options", f"{commit or 'HEAD'}^{{commit}}", check=False)
        if resolved.returncode:
            raise AppError("NOT_FOUND", "The bound test commit is unavailable; restore or explicitly rebind it")
        fixed = resolved.stdout.strip()
        temporary_root = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(prefix="ta-execution-", dir=temporary_root) as directory:
            owner = Path(directory).resolve()
            # TemporaryDirectory recursively removes only this newly allocated, checked target.
            if owner.parent != temporary_root or not owner.name.startswith("ta-execution-"):
                raise AppError("VALIDATION", "Execution snapshot directory escaped its temporary root")
            checkout = TestRepo(owner, "checkout")
            self.git(
                "clone",
                "--local",
                "--no-hardlinks",
                "--dissociate",
                "--no-checkout",
                "--",
                str(self.path.resolve()),
                str(checkout.path),
            )
            checkout.git("checkout", "--detach", "--force", fixed)
            yield ExecutionSnapshot(checkout.path, fixed)

    def dirty_files(self) -> list[str]:
        out = self.git("status", "--porcelain=v1", "-uall").stdout
        return sorted({line[3:].strip().strip('"') for line in out.splitlines() if line.strip()})

    def info(self) -> dict:
        if not self.initialized:
            return {"path": str(self.path), "initialized": False}
        return {
            "path": str(self.path),
            "initialized": True,
            "head": self.head(),
            "dirty": self.dirty_files(),
        }

    def ensure_clean(self) -> None:
        dirty = self.dirty_files()
        if dirty:
            raise AppError(
                "REPO_DIRTY",
                "The test repo has uncommitted manual changes; commit or revert them before auto-committing",
                related=dirty,
            )

    # ------------------------------------------------------------ files
    def resolve_test_path(self, rel: str) -> str:
        """Only `tests/**.py` inside the repo may be written by the platform."""
        return _test_path(self.path, rel)

    def write(self, rel: str, content: str) -> str:
        rel = self.resolve_test_path(rel)
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return rel

    def exists(self, rel: str) -> bool:
        return (self.path / self.resolve_test_path(rel)).is_file()

    def commit_files(self, files: list[str], message: str) -> str:
        """Commits exactly `files`; any other uncommitted change blocks the commit (REPO_DIRTY)."""
        files = sorted({self.resolve_test_path(f) for f in files})
        other = [f for f in self.dirty_files() if f not in files]
        if other:
            raise AppError(
                "REPO_DIRTY", "The test repo has uncommitted manual changes; refusing to auto-commit", related=other
            )
        self.git("add", "--", *files)
        if not self.git("diff", "--cached", "--name-only").stdout.strip():
            return self.head()  # identical content: nothing to commit
        return self._commit(message)
