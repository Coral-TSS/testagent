"""Environment preflight and local start.

Before a self-check, a debug run or a task run the platform checks that the environment's base
URL accepts connections. A system that is not running fails fast with a clear message instead
of burning self-check attempts or marking a script as broken. An environment may carry a
``start_command`` (e.g. the bundled procurement demo); the platform can start it on request and
the launcher starts it at startup when it is not reachable."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from testagent.core.errors import AppError

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]  # repository root (examples/ lives here)


def _address(base_url: str) -> tuple[str, int]:
    parts = urlsplit(base_url)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return host, port


def probe(base_url: str, timeout_s: float = 2.0) -> tuple[bool, str]:
    """Does the base URL accept TCP connections? (no request is sent)"""
    try:
        host, port = _address(base_url)
        with socket.create_connection((host, port), timeout=timeout_s):
            return True, "ok"
    except (OSError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def unreachable_message(env: dict) -> str:
    url = env.get("base_url") or "(no address configured)"
    if env.get("start_command"):
        hint = "Click “Start” under “SUT → Environments”, or run in a terminal: " + env["start_command"]
    else:
        hint = (
            "Retry after it starts; you can also fill in a “Start command” in the environment settings "
            "so the platform can start it for you"
        )
    return f"SUT environment {url} is unreachable; start the SUT first ({hint})"


def require_reachable(env: dict) -> None:
    """Raise ENV_UNREACHABLE (503) with a hint when the environment is down."""
    ok, detail = probe(env["base_url"])
    if not ok:
        log.info("environment %s unreachable: %s", env.get("base_url"), detail)
        raise AppError("ENV_UNREACHABLE", unreachable_message(env))


class EnvironmentProcesses:
    """Systems under test started by this platform instance (stopped when it exits)."""

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.procs: dict[str, subprocess.Popen] = {}

    def running(self, env_id) -> bool:
        proc = self.procs.get(str(env_id))
        return proc is not None and proc.poll() is None

    def start(self, env: dict, *, wait_s: float = 20.0) -> dict:
        if not env.get("start_command"):
            raise AppError(
                "VALIDATION", "This environment has no start command", field_errors=[{"field": "start_command"}]
            )
        ok, _ = probe(env["base_url"], timeout_s=1.0)
        if ok:
            return {"started": False, "reachable": True, "message": "Environment is reachable"}
        key = str(env["id"])
        if not self.running(key):
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / f"env-{key}.log"
            out = open(log_path, "ab")  # noqa: SIM115 - kept open for the child's lifetime
            kwargs: dict = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            self.procs[key] = subprocess.Popen(
                env["start_command"],
                shell=True,
                cwd=ROOT,
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                **kwargs,
            )
            log.info("started environment %s (pid %s)", env.get("name"), self.procs[key].pid)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            ok, _ = probe(env["base_url"], timeout_s=0.5)
            if ok:
                return {"started": True, "reachable": True, "message": "Started"}
            if not self.running(key):
                break
            time.sleep(0.5)
        log_file = self.log_dir / f"env-{key}.log"
        return {
            "started": self.running(key),
            "reachable": False,
            "message": f"Still unreachable after starting; check the logs {log_file}",
        }

    def stop_all(self) -> None:
        from testagent.integrations.pytest_runner import _kill_tree

        for key, proc in list(self.procs.items()):
            if proc.poll() is None:
                _kill_tree(proc)
            self.procs.pop(key, None)


def autostart(db, processes: EnvironmentProcesses) -> list[str]:
    """Launcher: start every environment with a start command that is not reachable."""
    with db.tx() as cur:
        cur.execute("SELECT * FROM environment WHERE start_command IS NOT NULL ORDER BY name")
        envs = cur.fetchall()
    started = []
    for env in envs:
        if probe(env["base_url"], timeout_s=0.5)[0]:
            continue
        try:
            res = processes.start(env, wait_s=0)
            if res["started"]:
                started.append(f"{env['name']} ({env['base_url']})")
        except Exception:  # never block the platform from starting
            log.exception("could not start environment %s", env["name"])
    return started


__all__ = [
    "EnvironmentProcesses",
    "autostart",
    "probe",
    "require_reachable",
    "unreachable_message",
]
