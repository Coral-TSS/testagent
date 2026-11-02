"""M1-09: serial task runs on the background worker, cancel, SSE progress, scheduling."""

import threading
import time
from datetime import UTC, datetime, timedelta

from tests.api.world import (
    V1,
    FakeRunner,
    build_world,
    install_runner,
    make_case,
    make_task,
    run_task,
)

from testagent.core.db import InstanceLock
from testagent.services.scheduler import Scheduler


def statuses(run):
    return [(e["case_title"], e["status"]) for e in run["executions"]]


def test_serial_order(client, db):
    w = build_world(client, db)
    ids = [make_case(client, w, t) for t in ("One", "Two", "Three")]
    runner = FakeRunner()
    install_runner(client, runner)
    task = make_task(client, w, [ids[2], ids[0], ids[1]])
    run = run_task(client, task)
    assert runner.order == ["Three", "One", "Two"]
    assert run["status"] == "passed" and run["trigger"] == "manual"
    assert [e["case_title"] for e in run["executions"]] == ["Three", "One", "Two"]
    assert run["counts"] == {
        "total": 3,
        "done": 3,
        "passed": 3,
        "failed": 0,
        "error": 0,
        "blocked": 0,
        "skipped": 0,
    }
    assert all(e["task_run_id"] == run["id"] for e in run["executions"])
    task_row = client.get(f"{V1}/tasks/{task}").json()
    assert task_row["status"] == "done"


def test_error_continues(client, db):
    w = build_world(client, db)
    ids = [make_case(client, w, t) for t in ("One", "Two", "Three")]
    install_runner(client, FakeRunner({"One": "crash", "Two": "failed"}))
    run = run_task(client, make_task(client, w, ids))
    assert statuses(run) == [("One", "error"), ("Two", "failed"), ("Three", "passed")]
    assert run["status"] == "failed"
    assert "browser crashed" in run["executions"][0]["error"]


def test_nonfunctional_skipped(client, db):
    w = build_world(client, db)
    a = make_case(client, w, "Performance", type_tag="performance")
    b = make_case(client, w, "Functional")
    install_runner(client, FakeRunner())
    run = run_task(client, make_task(client, w, [a, b]))
    assert statuses(run) == [("Performance", "skipped"), ("Functional", "passed")]
    assert run["status"] == "passed"
    skipped = client.get(f"{V1}/executions/{run['executions'][0]['id']}").json()
    assert "performance" in skipped["result"] and "never counted as passed" in skipped["result"]


def test_boundary_cases_are_executed(client, db):
    """TC-004/005/013/015 were skipped because type_tag 'boundary' was treated as
    non-functional."""
    w = build_world(client, db)
    a = make_case(client, w, "Boundary", type_tag="boundary", scenario="boundary")
    b = make_case(client, w, "Exception", type_tag="exception")
    runner = FakeRunner()
    install_runner(client, runner)
    run = run_task(client, make_task(client, w, [a, b]))
    assert statuses(run) == [("Boundary", "passed"), ("Exception", "passed")]
    assert runner.order == ["Boundary", "Exception"]


def test_only_ready_cases_run(client, db):
    w = build_world(client, db)
    ready = make_case(client, w, "Ready")
    draft = make_case(client, w, "Draft", status="draft")
    runner = FakeRunner()
    install_runner(client, runner)
    task = make_task(client, w, [draft, ready])
    run = run_task(client, task)
    assert runner.order == ["Ready"]
    assert statuses(run) == [("Ready", "passed")]
    assert run["not_ready"] == [{"id": draft, "code": "TC-002", "title": "Draft", "status": "draft"}]


def test_human_case_not_blocking(client, db):
    w = build_world(client, db)
    ids = [make_case(client, w, t) for t in ("One", "Two")]
    run = run_task(client, make_task(client, w, ids, executor="human"))
    assert statuses(run) == [("One", "blocked"), ("Two", "blocked")]
    assert run["status"] == "passed" and run["counts"]["blocked"] == 2
    blocked = run["executions"][0]
    assert blocked["blocked_reason"] == "awaiting_human"
    done = client.post(
        f"{V1}/executions/{blocked['id']}/complete",
        json={"status": "failed", "failed_assertion": "Button does nothing", "result": "Manual execution"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "failed" and done.json()["executed_by"] == "local-user"
    again = client.post(f"{V1}/executions/{blocked['id']}/complete", json={"status": "passed"})
    assert again.status_code == 409


def test_run_requires_ready_task_and_environment(client, db):
    w = build_world(client, db)
    case = make_case(client, w, "One")
    draft = make_task(client, w, [case], ready=False)
    assert client.post(f"{V1}/tasks/{draft}/run").status_code == 409
    no_env = client.post(
        f"{V1}/versions/{w['version']}/tasks", json={"name": "No environment", "case_ids": [case]}
    ).json()["id"]
    client.post(f"{V1}/tasks/{no_env}/status", json={"status": "ready"})
    resp = client.post(f"{V1}/tasks/{no_env}/run")
    assert resp.status_code == 422 and resp.json()["field_errors"][0]["field"] == "environment_id"


def test_cancel_stops_new_cases(client, db):
    w = build_world(client, db)
    ids = [make_case(client, w, t) for t in ("One", "Two", "Three")]
    state = {}

    def cancel_after_first(case):
        if case["title"] == "One":
            assert client.post(f"{V1}/runs/{state['run']}/cancel").status_code == 200

    runner = FakeRunner(on_case=cancel_after_first)
    install_runner(client, runner)
    task = make_task(client, w, ids)
    state["run"] = client.post(f"{V1}/tasks/{task}/run").json()["id"]
    assert client.get(f"{V1}/runs/{state['run']}").json()["status"] == "queued"
    client.app.state.worker.run_once()
    run = client.get(f"{V1}/runs/{state['run']}").json()
    assert runner.order == ["One"]
    assert run["status"] == "cancelled" and statuses(run) == [("One", "passed")]
    assert client.get(f"{V1}/tasks/{task}").json()["status"] == "cancelled"
    # a queued run is cancelled at once and never picked up
    queued = client.post(f"{V1}/tasks/{task}/run").json()["id"]
    assert client.post(f"{V1}/runs/{queued}/cancel").json()["status"] == "cancelled"
    assert client.app.state.worker.run_once() is False
    assert runner.order == ["One"]


def test_no_second_active_run(client, db):
    w = build_world(client, db)
    task = make_task(client, w, [make_case(client, w, "One")])
    assert client.post(f"{V1}/tasks/{task}/run").status_code == 201
    second = client.post(f"{V1}/tasks/{task}/run")
    assert second.status_code == 409 and second.json()["code"] == "RUN_ACTIVE"


def test_sse_emits_case_progress(client, db):
    w = build_world(client, db)
    ids = [make_case(client, w, t) for t in ("One", "Two")]
    install_runner(client, FakeRunner({"Two": "failed"}))
    task = make_task(client, w, ids)
    run_id = client.post(f"{V1}/tasks/{task}/run").json()["id"]
    channel = client.app.state.runs_channel(run_id)

    def work():
        deadline = time.time() + 10
        while time.time() < deadline:  # start only once the SSE endpoint is listening
            with db.tx() as cur:
                cur.execute("SELECT 1 FROM pg_stat_activity WHERE query LIKE %s", (f"LISTEN%{channel}%",))
                if cur.fetchone():
                    break
            time.sleep(0.05)
        client.app.state.worker.run_once()

    worker = threading.Thread(target=work)
    worker.start()
    resp = client.get(f"{V1}/runs/{run_id}/events")
    worker.join()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = [
        (block.split("\n")[0].removeprefix("event: "), block)
        for block in resp.text.strip().split("\n\n")
        if block.startswith("event:")
    ]
    names = [e for e, _ in events]
    assert names[0] == "snapshot" and names[-1] == "end"
    assert names.count("case") == 2
    case_events = [b for e, b in events if e == "case"]
    assert '"status": "failed"' in case_events[1] and '"index": 2' in case_events[1]
    # reconnect after the end: snapshot (full state) + end immediately
    again = client.get(f"{V1}/runs/{run_id}/events").text
    assert again.count("event: snapshot") == 1 and "event: end" in again


def test_first_run_moves_version_to_testing(client, db):
    w = build_world(client, db)
    install_runner(client, FakeRunner())
    task = make_task(client, w, [make_case(client, w, "One")])
    assert client.get(f"{V1}/versions/{w['version']}").json()["status"] == "requirements_frozen"
    run_task(client, task)
    assert client.get(f"{V1}/versions/{w['version']}").json()["status"] == "testing"
    run_task(client, task)  # later runs leave it alone
    assert client.get(f"{V1}/versions/{w['version']}").json()["status"] == "testing"
    runs = client.get(f"{V1}/tasks/{task}/runs").json()
    assert len(runs) == 2 and runs[0]["counts"]["passed"] == 1
    recent = client.get(f"{V1}/runs", params={"version_id": w["version"]}).json()
    assert [r["id"] for r in recent] == [r["id"] for r in runs]
    assert recent[0]["task_name"] == "Task" and recent[0]["sut_code"] == "SHOP"


# ------------------------------------------------------------------ scheduler (T-09.4)
class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class HeldLock:
    held = True


def scheduler_for(client, clock, lock=None):
    return Scheduler(client.app.state.db, client.app.state.runs_factory, lock or HeldLock(), clock)


def cron_task(client, w, now, expr="*/10 * * * *"):
    task = make_task(client, w, [make_case(client, w, "One")])
    client.patch(f"{V1}/tasks/{task}", json={"schedule": {"type": "cron", "expr": expr}})
    with w["db"].tx() as cur:  # pin next_run_at relative to the injected clock
        cur.execute("UPDATE test_task SET next_run_at=%s WHERE id=%s", (now, task))
    return task


T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def test_cron_enqueues_on_due(client, db):
    w = build_world(client, db)
    clock = Clock(T0 - timedelta(minutes=1))
    task = cron_task(client, w, T0)
    sched = scheduler_for(client, clock)
    assert sched.tick() == []  # not due yet
    clock.now = T0 + timedelta(seconds=5)
    started = sched.tick()
    assert len(started) == 1
    run = client.get(f"{V1}/runs/{started[0]}").json()
    assert run["trigger"] == "schedule" and run["status"] == "queued"
    nxt = client.get(f"{V1}/tasks/{task}").json()["next_run_at"]
    assert datetime.fromisoformat(nxt) == T0 + timedelta(minutes=10)


def test_no_reentry_while_running(client, db):
    w = build_world(client, db)
    clock = Clock(T0)
    task = cron_task(client, w, T0)
    sched = scheduler_for(client, clock)
    assert len(sched.tick()) == 1  # queued, not yet executed
    clock.now = T0 + timedelta(minutes=10)
    assert sched.tick() == []  # previous run still active → skipped
    assert len(client.get(f"{V1}/tasks/{task}/runs").json()) == 1
    nxt = client.get(f"{V1}/tasks/{task}").json()["next_run_at"]
    assert datetime.fromisoformat(nxt) == T0 + timedelta(minutes=20)


def test_missed_ticks_not_backfilled(client, db):
    w = build_world(client, db)
    clock = Clock(T0 + timedelta(hours=3, minutes=1))  # platform was off for 3 hours
    task = cron_task(client, w, T0)
    started = scheduler_for(client, clock).tick()
    assert len(started) == 1  # one run, not eighteen
    nxt = client.get(f"{V1}/tasks/{task}").json()["next_run_at"]
    assert datetime.fromisoformat(nxt) == T0 + timedelta(hours=3, minutes=10)


def test_scheduler_follows_local_timezone(client, db):
    w = build_world(client, db)
    task = make_task(client, w, [make_case(client, w, "One")])
    client.patch(f"{V1}/tasks/{task}", json={"schedule": {"type": "cron", "expr": "0 9 * * *"}})
    due = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)  # 09:00 Asia/Shanghai
    with w["db"].tx() as cur:
        cur.execute("UPDATE test_task SET next_run_at=%s WHERE id=%s", (due, task))
    assert len(scheduler_for(client, Clock(due + timedelta(seconds=3))).tick()) == 1
    nxt = datetime.fromisoformat(client.get(f"{V1}/tasks/{task}").json()["next_run_at"])
    assert nxt == due + timedelta(days=1)


def test_once_schedule_fires_once(client, db):
    w = build_world(client, db)
    task = make_task(client, w, [make_case(client, w, "One")])
    at = datetime.now(UTC) + timedelta(hours=1)
    client.patch(f"{V1}/tasks/{task}", json={"schedule": {"type": "once", "at": at.isoformat()}})
    sched = scheduler_for(client, Clock(at + timedelta(seconds=1)))
    assert len(sched.tick()) == 1
    assert client.get(f"{V1}/tasks/{task}").json()["next_run_at"] is None
    assert sched.tick() == []


def test_scheduler_requires_instance_lock(client, db):
    w = build_world(client, db)
    cron_task(client, w, T0)
    holder = InstanceLock(db, name="scheduler-test")
    other = InstanceLock(db, name="scheduler-test")
    assert holder.acquire()
    try:
        assert not other.acquire()
        assert scheduler_for(client, Clock(T0), lock=other).tick() == []
        assert len(scheduler_for(client, Clock(T0), lock=holder).tick()) == 1
    finally:
        holder.release()


def test_background_worker_thread_runs_jobs(client, db):
    w = build_world(client, db)
    install_runner(client, FakeRunner())
    task = make_task(client, w, [make_case(client, w, "One")])
    worker = client.app.state.worker
    worker.start(poll_s=0.2)
    try:
        run_id = client.post(f"{V1}/tasks/{task}/run").json()["id"]
        deadline = time.time() + 10
        while client.get(f"{V1}/runs/{run_id}").json()["status"] != "passed":
            assert time.time() < deadline, "worker did not pick up the run"
            time.sleep(0.1)
    finally:
        worker.stop()


def test_restart_marks_running_run_interrupted(client, db):
    from testagent.core.jobs import mark_interrupted

    w = build_world(client, db)
    task = make_task(client, w, [make_case(client, w, "One")])
    run_id = client.post(f"{V1}/tasks/{task}/run").json()["id"]
    counts = mark_interrupted(db)
    assert counts["task_run"] == 1 and counts["test_task"] == 1
    assert client.get(f"{V1}/runs/{run_id}").json()["status"] == "error"
    assert client.get(f"{V1}/tasks/{task}").json()["status"] == "ready"
    assert client.post(f"{V1}/tasks/{task}/run").status_code == 201
