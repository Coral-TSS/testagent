"""Background Worker: claims jobs (SKIP LOCKED), dispatches by kind, wakes on NOTIFY (5 s poll)."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable

from testagent.core.jobs import JobQueue

log = logging.getLogger("testagent.worker")
Handler = Callable[[dict], None]
JOB_LABEL = {
    "task_run": "Run task",
    "automate_case": "AI automate cases",
    "complete_case": "AI complete case",
    "digest_correction": "Process corrections",
}


class Worker:
    def __init__(
        self,
        jobs: JobQueue,
        handlers: dict[str, Handler],
        name: str | None = None,
        describe: Callable[[dict], str] | None = None,
    ):
        self.jobs = jobs
        self.handlers = handlers
        self.describe = describe  # payload → "case “… (TC-001)”" for readable log lines
        self.name = name or f"worker-{os.getpid()}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> bool:
        """Claim and run one job; False when nothing is due."""
        job = self.jobs.claim(self.name, list(self.handlers))
        if job is None:
            return False
        error = None
        what = self._what(job)
        log.info("Background job #%s %s started%s", job["id"], what[0], what[1])
        started = time.monotonic()
        try:
            self.handlers[job["kind"]](job["payload"])
        except Exception as exc:  # a failing job never kills the worker
            log.exception("job %s (%s) failed%s", job["id"], job["kind"], what[1])
            error = f"{type(exc).__name__}: {exc}"[:2000]
        self.jobs.finish(job["id"], error)
        log.info(
            "Background job #%s %s %s (%.1f s)%s",
            job["id"],
            what[0],
            "failed" if error else "done",
            time.monotonic() - started,
            what[1],
        )
        return True

    def _what(self, job: dict) -> tuple[str, str]:
        label = JOB_LABEL.get(job["kind"], job["kind"])
        if self.describe is None:
            return label, ""
        try:
            text = self.describe(job.get("payload") or {})
        except Exception:  # noqa: BLE001 - naming is best effort
            text = ""
        return label, f" · {text}" if text else ""

    def _loop(self, poll_s: float) -> None:
        listener = self.jobs.listener()
        try:
            while not self._stop.is_set():
                try:
                    while not self._stop.is_set() and self.run_once():
                        pass
                except Exception:
                    log.exception("worker loop error")
                listener.wait(poll_s)
        finally:
            listener.close()

    def start(self, poll_s: float = 5.0) -> None:
        self._thread = threading.Thread(target=self._loop, args=(poll_s,), name=self.name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
