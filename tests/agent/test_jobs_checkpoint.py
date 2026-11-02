"""M1-04 jobs queue, restart recovery and checkpoint resume."""

import threading
import time

import pytest
from pydantic import BaseModel

from testagent.agent.checkpoint import open_checkpointer
from testagent.agent.config import AgentConfigService, ModelFactory
from testagent.agent.fake import FakeChatModel, call
from testagent.agent.runtime import AgentRuntime, Entry
from testagent.agent.tools import ToolRegistry, ToolSpec
from testagent.core.jobs import JobQueue, mark_interrupted
from testagent.core.secrets import SecretStore


class Done(BaseModel):
    note: str


def test_jobs_skip_locked_single_consumer(db):
    queue = JobQueue(db)
    ids = {queue.enqueue("demo", {"n": n}) for n in range(20)}
    claimed: list[int] = []
    lock = threading.Lock()

    def worker(name):
        while (job := queue.claim(name)) is not None:
            with lock:
                claimed.append(job["id"])
            time.sleep(0.005)
            queue.finish(job["id"])

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(ids)  # every job exactly once
    assert all(queue.get(i)["status"] == "done" for i in ids)


def test_claim_respects_run_after_and_kind(db):
    queue = JobQueue(db)
    later = queue.enqueue("demo", delay_s=60)
    other = queue.enqueue("other")
    assert queue.claim("w", kinds=["demo"]) is None
    assert queue.claim("w", kinds=["other"])["id"] == other
    assert queue.get(later)["status"] == "queued"
    queue.finish(other, error="boom")
    assert queue.get(other)["error"] == "boom"


def test_notify_wakes_worker(db):
    queue = JobQueue(db)
    listener = queue.listener()
    try:
        assert listener.wait(0.2) is False
        woke = {}

        def wait():
            started = time.monotonic()
            woke["ok"] = listener.wait(5)
            woke["s"] = time.monotonic() - started

        thread = threading.Thread(target=wait)
        thread.start()
        time.sleep(0.2)
        queue.enqueue("demo")
        thread.join()
        assert woke["ok"] is True and woke["s"] < 3
    finally:
        listener.close()


def test_restart_marks_interrupted(db):
    queue = JobQueue(db)
    running = queue.enqueue("demo")
    queue.claim("w")
    queued = queue.enqueue("demo")
    with db.tx() as cur:
        cur.execute("INSERT INTO agent_run(purpose, status) VALUES ('demo','running'), ('demo','succeeded')")
    counts = mark_interrupted(db)
    assert counts["jobs"] == 2 and counts["agent_run"] == 1
    assert queue.get(running)["error"] == "INTERRUPTED"
    assert queue.get(queued)["status"] == "error"
    with db.tx() as cur:
        cur.execute("SELECT status, error_code FROM agent_run ORDER BY status")
        rows = [(r["status"], r["error_code"]) for r in cur.fetchall()]
    assert rows == [("error", "INTERRUPTED"), ("succeeded", None)]
    assert mark_interrupted(db)["jobs"] == 0


def test_jobs_api(client, db):
    job_id = JobQueue(db).enqueue("demo", {"x": 1})
    body = client.get(f"/api/v1/jobs/{job_id}").json()
    assert body["status"] == "queued" and body["payload"] == {"x": 1}
    assert client.get("/api/v1/jobs/999999").status_code == 404


class Crash(BaseException):
    """Simulates the process dying in the middle of a tool call."""


@pytest.fixture
def checkpointer(db, test_dsn):
    saver, conn = open_checkpointer(test_dsn, db.schema)
    yield saver
    conn.close()


def test_checkpoint_resume_after_interrupt(db, tmp_path, checkpointer):
    state = {"calls": 0}

    def flaky(x: str) -> str:
        state["calls"] += 1
        if state["calls"] == 1:
            raise Crash()
        return f"tool-ok-{x}"

    class Args(BaseModel):
        x: str

    registry = ToolRegistry()
    registry.register(ToolSpec("flaky", "test", "d", Args, flaky))
    entry = Entry(name="demo", output_schema=Done, tools=("flaky",))
    config = AgentConfigService(db, SecretStore(tmp_path / "s.json"))

    first_model = FakeChatModel(script=[call("flaky", {"x": "1"})])
    runtime = AgentRuntime(db, registry, ModelFactory(config, lambda c: first_model), {"demo": entry}, checkpointer)
    run_id = runtime.start("demo", {})
    with pytest.raises(Crash):
        runtime.execute(run_id)
    assert runtime.get_run(run_id)["status"] == "running"

    # "new process": fresh runtime + model, same checkpoint store
    second_model = FakeChatModel(script=[call("submit_result", {"note": "resumed"})])
    runtime2 = AgentRuntime(db, registry, ModelFactory(config, lambda c: second_model), {"demo": entry}, checkpointer)
    run = runtime2.execute(run_id, resume=True)
    assert run["status"] == "succeeded" and run["result"] == {"note": "resumed"}
    assert len(first_model.seen) == 1 and len(second_model.seen) == 1
    history = second_model.seen[0]
    assert history[-1].content == "tool-ok-1"  # resumed at the tool step, not from scratch
    assert state["calls"] == 2
