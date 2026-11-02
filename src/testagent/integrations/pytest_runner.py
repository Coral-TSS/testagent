"""pytest executor (architecture §5.3): runs one test file of a SUT test repo in a subprocess,
parses JUnit XML, extracts the failed assertion and collects Playwright traces/screenshots.

the platform plugin ``testagent.integrations.pytest_report`` is loaded into the run and
writes a readable report (steps, requests, assertions with expected/actual, data keys, error
explained in plain language) that is returned as ``report``."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from testagent.core.artifacts import ArtifactStore

_KEEP_ENV_PREFIXES = ("TESTAGENT_DATA", "TESTAGENT_BASE_URL")


PLUGIN = "testagent.integrations.pytest_report"
SRC_DIR = str(Path(__file__).resolve().parents[2])  # makes the plugin importable from the repo


def _env(base_url: str, test_data, report: Path | None = None, pycache: Path | None = None):
    env = {
        k: v for k, v in os.environ.items() if not k.startswith("TESTAGENT_") or k.startswith(_KEEP_ENV_PREFIXES)
    }  # never leak platform settings (e.g. database URLs) into test code
    env["TESTAGENT_DATA"] = json.dumps(test_data or {}, ensure_ascii=False)
    env["TESTAGENT_BASE_URL"] = base_url
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    env["PYTHONIOENCODING"] = "utf-8"
    if report is not None:
        env["TESTAGENT_REPORT"] = str(report)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (SRC_DIR, env.get("PYTHONPATH")) if p)
    if pycache is not None:  # fresh assertion rewriting (pass hook) and no .pyc in the repo
        env["PYTHONPYCACHEPREFIX"] = str(pycache)
    return env


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.kill()


def parse_junit(path: Path) -> dict:
    """Aggregate one file's testcases: error > failed > passed > skipped."""
    root = ET.parse(path).getroot()
    cases = []
    for tc in root.iter("testcase"):
        name = f"{tc.get('classname', '')}::{tc.get('name', '')}".strip(":")
        failure, error, skipped = tc.find("failure"), tc.find("error"), tc.find("skipped")
        if error is not None:
            status, node = "error", error
        elif failure is not None:
            status, node = "failed", failure
        elif skipped is not None:
            status, node = "skipped", skipped
        else:
            status, node = "passed", None
        message = None
        if node is not None:
            message = (node.get("message") or "").strip() or (node.text or "").strip()[:2000]
        cases.append(
            {
                "name": name,
                "status": status,
                "message": message,
                "detail": node.text if node is not None else None,
            }
        )
    if not cases:
        return {"status": "error", "cases": [], "error": "no tests collected"}
    statuses = {c["status"] for c in cases}
    status = next(s for s in ("error", "failed", "passed", "skipped") if s in statuses)
    out = {"status": status, "cases": cases}
    failed = [c for c in cases if c["status"] == "failed"]
    if failed:
        out["failed_assertion"] = _assertion_line(failed[0])
    errored = [c for c in cases if c["status"] == "error"]
    if errored:
        out["error"] = errored[0]["message"]
    return out


def _assertion_line(case: dict) -> str:
    """Prefer pytest's 'E   assert ...' lines from the traceback; fall back to the message."""
    lines = [ln.strip()[1:].strip() for ln in (case["detail"] or "").splitlines() if ln.strip().startswith("E ")]
    text = "\n".join(lines[:6]) if lines else (case["message"] or "")
    return f"{case['name']}: {text}"[:2000]


def _read_report(path: Path, test_data) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    given = test_data if isinstance(test_data, dict) else {}
    for test in data.get("tests", []):
        keys = test.get("data_keys") or []
        test["data_used"] = {k: given[k] for k in keys if k in given}
        test["data_missing"] = [k for k in keys if k not in given]
    return data


def run_pytest(
    repo_path: Path,
    code_path: str,
    *,
    base_url: str,
    test_data=None,
    timeout_s: float = 300,
    artifacts: ArtifactStore | None = None,
    browser: bool = True,
) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ta-pytest-") as tmp:
        junit = Path(tmp) / "junit.xml"
        output = Path(tmp) / "output"
        report = Path(tmp) / "report.json"
        cmd = [
            sys.executable, "-m", "pytest", code_path,
            "--junitxml", str(junit), "-p", "no:cacheprovider", "-q", "-o", "junit_family=xunit2",
            "--base-url", base_url,
            "-p", PLUGIN, "-o", "enable_assertion_pass_hook=true",
        ]  # fmt: skip
        if browser:
            cmd += ["--tracing", "retain-on-failure", "--screenshot", "only-on-failure"]
            cmd += ["--output", str(output)]
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            cmd,
            cwd=repo_path,
            env=_env(base_url, test_data, report, Path(tmp) / "pycache"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        try:
            raw, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.communicate()
            return {
                "status": "error",
                "error": f"TIMEOUT: pytest exceeded {timeout_s:g}s and was killed",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "output": "",
                "artifacts": [],
            }
        text = raw.decode("utf-8", errors="replace")
        result = (
            parse_junit(junit)
            if junit.exists()
            else {"status": "error", "error": f"pytest exited with {proc.returncode}"}
        )
        if result["status"] == "error" and not result.get("error"):
            result["error"] = text.strip().splitlines()[-1] if text.strip() else "error"
        files = []
        if artifacts is not None and output.exists():
            for f in sorted(output.rglob("*")):
                if f.is_file() and f.suffix in (".zip", ".png", ".webm"):
                    kind = {".zip": "trace", ".png": "screenshot", ".webm": "video"}[f.suffix]
                    files.append({"kind": kind, "name": f.name, "sha256": artifacts.put(f.read_bytes())})
        result["report"] = _read_report(report, test_data)
        result.update(
            output=text[-8000:],
            artifacts=files,
            duration_ms=int((time.monotonic() - started) * 1000),
            returncode=proc.returncode,
        )
        return result
