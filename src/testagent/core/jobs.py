"""Background job queue on PostgreSQL: FOR UPDATE SKIP LOCKED claims + LISTEN/NOTIFY wake-ups."""

from __future__ import annotations

from psycopg import sql
from psycopg.types.json import Jsonb

from testagent.core.db import Database
from testagent.core.errors import AppError


class JobQueue:
    def __init__(self, db: Database):
        self.db = db
        schema = getattr(db, "schema", None)
        suffix = f"_{schema}" if schema else ""
        self.channel = f"testagent_jobs{suffix}"

    def enqueue(self, kind: str, payload: dict | None = None, *, delay_s: float = 0) -> int:
        with self.db.tx() as cur:
            cur.execute(
                "INSERT INTO jobs(kind, payload, run_after)"
                " VALUES (%s, %s, now() + make_interval(secs => %s)) RETURNING id",
                (kind, Jsonb(payload or {}), delay_s),
            )
            job_id = cur.fetchone()["id"]
            cur.execute("SELECT pg_notify(%s, %s)", (self.channel, str(job_id)))  # sent on commit
        return job_id

    def claim(self, worker: str, kinds: list[str] | None = None) -> dict | None:
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE jobs SET status='running', started_at=now(), attempts=attempts+1,"
                " locked_by=%s WHERE id = ("
                "  SELECT id FROM jobs WHERE status='queued' AND run_after <= now()"
                "  AND (%s::text[] IS NULL OR kind = ANY(%s::text[]))"
                "  ORDER BY run_after, id FOR UPDATE SKIP LOCKED LIMIT 1)"
                " RETURNING *",
                (worker, kinds, kinds),
            )
            return cur.fetchone()

    def finish(self, job_id: int, error: str | None = None) -> None:
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE jobs SET status=%s, error=%s, ended_at=now() WHERE id=%s AND status='running' RETURNING id",
                ("error" if error else "done", error, job_id),
            )
            if cur.fetchone() is None:
                raise AppError("CONFLICT", "Job is not running")

    def get(self, job_id: int) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Background job not found")
        return row

    def listener(self) -> Listener:
        return Listener(self.db, self.channel)

    def cancel_queued(self, kind: str, key: str, value: str) -> int:
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE jobs SET status='cancelled', ended_at=now()"
                " WHERE status='queued' AND kind=%s AND payload->>%s = %s",
                (kind, key, value),
            )
            return cur.rowcount


class Listener:
    """Dedicated LISTEN connection; `wait` returns True when a notification arrives."""

    def __init__(self, db: Database, channel: str):
        self.conn = db.connect(autocommit=True)
        self.conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))

    def wait(self, timeout: float) -> bool:
        return self.next(timeout) is not None

    def next(self, timeout: float) -> str | None:
        """Payload of the next notification, or None after `timeout` seconds."""
        for note in self.conn.notifies(timeout=timeout, stop_after=1):
            return note.payload
        return None

    def close(self) -> None:
        self.conn.close()


INTERRUPTED = "INTERRUPTED"


def mark_interrupted(db: Database) -> dict[str, int]:
    """Startup recovery: unfinished work from a previous process is marked error, never re-run."""
    counts = {}
    with db.tx() as cur:
        cur.execute(
            "UPDATE jobs SET status='error', error=%s, ended_at=now() WHERE status IN ('queued','running')",
            (INTERRUPTED,),
        )
        counts["jobs"] = cur.rowcount
        cur.execute(
            "UPDATE task_run SET status='error', error=%s WHERE status IN ('queued','running')",
            (INTERRUPTED,),
        )
        counts["task_run"] = cur.rowcount
        cur.execute("UPDATE test_task SET status='ready' WHERE status='running'")
        counts["test_task"] = cur.rowcount
        cur.execute(
            "UPDATE case_execution SET status='error', error=%s, ended_at=now() WHERE status IN ('queued','running')",
            (INTERRUPTED,),
        )
        counts["case_execution"] = cur.rowcount
        cur.execute(
            "UPDATE agent_run SET status='error', error_code=%s, ended_at=now() WHERE status IN ('queued','running')",
            (INTERRUPTED,),
        )
        counts["agent_run"] = cur.rowcount
    return counts
