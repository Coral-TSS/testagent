"""Scheduler (architecture §5.5): only in the process holding the instance lock; no re-entry;
missed periods are not back-filled (C08). The clock is injectable for tests."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from testagent.core.errors import AppError
from testagent.services.tasks import next_run

log = logging.getLogger("testagent.scheduler")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Scheduler:
    def __init__(self, db, runs: Callable, lock, clock: Callable[[], datetime] = utcnow):
        self.db = db
        self.runs = runs  # () -> RunService acting as the scheduler
        self.lock = lock
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> list[str]:
        """Enqueue every due task once; returns the started run ids."""
        if self.lock is None or not self.lock.held:
            return []
        now = self.clock()
        started: list[str] = []
        service = self.runs()
        with self.db.tx() as cur:
            cur.execute(
                "SELECT id, schedule FROM test_task WHERE next_run_at IS NOT NULL"
                " AND next_run_at <= %s AND status <> 'archived'"
                " ORDER BY next_run_at FOR UPDATE SKIP LOCKED",
                (now,),
            )
            due = cur.fetchall()
            for task in due:
                try:
                    following = next_run(task["schedule"], now)  # from now: no back-fill
                except AppError:
                    following = None
                cur.execute("UPDATE test_task SET next_run_at=%s WHERE id=%s", (following, task["id"]))
                cur.execute("SAVEPOINT sched")
                try:
                    run = service.start(task["id"], "schedule", cur=cur)
                except AppError as err:  # RUN_ACTIVE (no re-entry), not ready, no environment
                    cur.execute("ROLLBACK TO SAVEPOINT sched")
                    log.info("scheduled run of task %s skipped: %s", task["id"], err.message)
                    continue
                cur.execute("RELEASE SAVEPOINT sched")
                started.append(str(run["id"]))
        return started

    def _loop(self, interval_s: float) -> None:
        while not self._stop.wait(interval_s):
            try:
                self.tick()
            except Exception:
                log.exception("scheduler tick failed")

    def start(self, interval_s: float = 30.0) -> None:
        self._thread = threading.Thread(target=self._loop, args=(interval_s,), name="scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
