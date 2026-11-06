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
from tests.conftest import TEST_USER

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
    assert run["status"] == "not_executed" and run["counts"]["blocked"] == 2
    report = client.get(f"{V1}/reports/{run['report_id']}").json()["content"]
    assert report["scope"]["status"] == "not_executed"
    assert report["summary"]["executed"] == 0
    assert report["summary"]["pass_rate"] is None
    blocked = run["executions"][0]
    assert blocked["blocked_reason"] == "awaiting_human"
    done = client.post(
        f"{V1}/executions/{blocked['id']}/complete",
        json={"status": "failed", "failed_assertion": "Button does nothing", "result": "Manual execution"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "failed" and done.json()["executed_by"] == TEST_USER
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


# ------------------------------------------------------------------ batch 2 (#18): cases without a script
def _automate(db, case_id, path="tests/R/test_x.py"):
    with db.tx() as cur:
        cur.execute("UPDATE test_case SET mode='automated', code_path=%s WHERE id=%s", (path, case_id))


def test_missing_script_is_skipped_not_error(client, db):
    w = build_world(client, db)
    scripted = make_case(client, w, "Scripted")
    _automate(db, scripted)
    bare = make_case(client, w, "No script")
    install_runner(client, FakeRunner())
    # Set ready asks first: the automated task has a case without a script
    task = make_task(client, w, [scripted, bare], executor="automation", ready=False)
    resp = client.post(f"{V1}/tasks/{task}/status", json={"status": "ready"})
    assert resp.status_code == 409 and resp.json()["code"] == "MISSING_SCRIPTS"
    code = client.get(f"{V1}/cases/{bare}").json()["code"]
    assert resp.json()["related"] == [code]
    ok = client.post(f"{V1}/tasks/{task}/status", json={"status": "ready", "allow_missing_scripts": True})
    assert ok.status_code == 200
    detail = client.get(f"{V1}/tasks/{task}").json()
    assert [g["code"] for g in detail["script_gaps"]] == [code]
    listed = client.get(f"{V1}/versions/{w['version']}/tasks").json()
    assert listed[0]["script_gap_count"] == 1
    # Run now asks too
    blocked = client.post(f"{V1}/tasks/{task}/run")
    assert blocked.status_code == 409 and blocked.json()["code"] == "MISSING_SCRIPTS"
    resp = client.post(f"{V1}/tasks/{task}/run", json={"allow_missing_scripts": True})
    assert resp.status_code == 201, resp.text
    assert client.app.state.worker.run_once() is True
    run = client.get(f"{V1}/runs/{resp.json()['id']}").json()
    assert statuses(run) == [("Scripted", "passed"), ("No script", "skipped")]
    assert run["status"] == "passed"  # a missing script is a setup gap, not a failure
    skipped = run["executions"][1]
    assert skipped["failure_kind"] == "no_script" and skipped["suspected_cause"] == "platform"
    assert "no automation script" in skipped["result"]
    assert run["no_script"] == [{"case_id": bare, "code": code, "title": "No script"}]
    report = client.get(f"{V1}/reports/{run['report_id']}").json()["content"]
    summary = report["summary"]
    assert summary["skipped"] == 1 and summary["skipped_no_script"] == 1 and summary["error"] == 0
    assert summary["executed"] == 1 and summary["pass_rate"] == 1
    assert [n["case"]["code"] for n in report["no_script"]] == [code]


def test_run_with_only_missing_scripts_is_not_executed(client, db):
    w = build_world(client, db)
    bare = make_case(client, w, "No script")
    install_runner(client, FakeRunner())
    task = make_task(client, w, [bare], executor="automation", ready=False)
    client.post(f"{V1}/tasks/{task}/status", json={"status": "ready", "allow_missing_scripts": True})
    resp = client.post(f"{V1}/tasks/{task}/run", json={"allow_missing_scripts": True})
    assert client.app.state.worker.run_once() is True
    run = client.get(f"{V1}/runs/{resp.json()['id']}").json()
    assert run["status"] == "not_executed"  # nothing ran: neither passed nor failed
    assert client.get(f"{V1}/tasks/{task}").json()["status"] == "done"
    report = client.get(f"{V1}/reports/{run['report_id']}").json()["content"]
    assert report["scope"]["status"] == "not_executed"
    assert report["summary"]["executed"] == 0 and report["summary"]["pass_rate"] is None
    assert report["summary"]["skipped_no_script"] == 1
    # the task can run again
    assert client.post(f"{V1}/tasks/{task}/run", json={"allow_missing_scripts": True}).status_code == 201


def test_scheduled_run_does_not_ask_about_missing_scripts(client, db):
    w = build_world(client, db)
    bare = make_case(client, w, "No script")
    install_runner(client, FakeRunner())
    task = make_task(client, w, [bare], executor="automation", ready=False)
    client.post(f"{V1}/tasks/{task}/status", json={"status": "ready", "allow_missing_scripts": True})
    run = client.app.state.runs_factory("scheduler").start(task, "schedule")
    assert run["status"] == "queued"


def test_agent_and_human_tasks_have_no_script_gaps(client, db):
    w = build_world(client, db)
    bare = make_case(client, w, "Manual")
    task = make_task(client, w, [bare], executor="agent")
    assert client.get(f"{V1}/tasks/{task}").json()["script_gaps"] == []


# ------------------------------------------------------------------ batch 2 (#13): run a version's tasks
def test_runnable_tasks_reasons(client, db):
    w = build_world(client, db)
    a = make_case(client, w, "A")
    draft_case = make_case(client, w, "Draft", status="draft")
    ready = make_task(client, w, [a], name="Ready")
    make_task(client, w, [a], name="Draft task", ready=False)
    make_task(client, w, [draft_case], name="Only drafts", ready=False)
    empty = client.post(f"{V1}/versions/{w['version']}/tasks", json={"name": "Empty", "executor": "agent"}).json()
    rows = {r["name"]: r for r in client.get(f"{V1}/versions/{w['version']}/runnable-tasks").json()}
    assert rows["Ready"]["runnable"] is True and rows["Ready"]["reason"] is None
    assert rows["Ready"]["ready_cases"] == 1
    assert rows["Draft task"]["reason"] == "not_ready"
    assert rows["Empty"]["reason"] == "no_cases" and rows["Empty"]["id"] == empty["id"]
    install_runner(client, FakeRunner())
    client.post(f"{V1}/tasks/{ready}/run")
    rows = {r["name"]: r for r in client.get(f"{V1}/versions/{w['version']}/runnable-tasks").json()}
    assert rows["Ready"]["reason"] == "running" and rows["Ready"]["active_run_id"]


def test_run_version_starts_every_runnable_task(client, db):
    w = build_world(client, db)
    a = make_case(client, w, "A")
    b = make_case(client, w, "B")
    t1 = make_task(client, w, [a], name="T1")
    t2 = make_task(client, w, [b], name="T2")
    draft = make_task(client, w, [b], name="Draft", ready=False)
    install_runner(client, FakeRunner())
    version = client.get(f"{V1}/versions/{w['version']}").json()
    assert version["status"] == "requirements_frozen"
    out = client.post(f"{V1}/versions/{w['version']}/run-tasks", json={}).json()
    assert sorted(s["name"] for s in out["started"]) == ["T1", "T2"]
    assert out["skipped"] == [] and out["version_testing"] is True
    assert client.get(f"{V1}/versions/{w['version']}").json()["status"] == "testing"
    while client.app.state.worker.run_once():
        pass
    for task in (t1, t2):
        assert client.get(f"{V1}/tasks/{task}").json()["status"] == "done"
    # asking for a draft task without set_ready is refused for that task only
    again = client.post(f"{V1}/versions/{w['version']}/run-tasks", json={"task_ids": [draft, t1]}).json()
    assert [s["name"] for s in again["started"]] == ["T1"]
    assert again["skipped"][0]["name"] == "Draft" and again["skipped"][0]["code"] == "CONFLICT"
    while client.app.state.worker.run_once():
        pass
    # with set_ready the draft task is set ready and started
    third = client.post(f"{V1}/versions/{w['version']}/run-tasks", json={"task_ids": [draft], "set_ready": True}).json()
    assert [s["name"] for s in third["started"]] == ["Draft"]


def test_run_version_reports_missing_scripts_per_task(client, db):
    w = build_world(client, db)
    bare = make_case(client, w, "No script")
    task = make_task(client, w, [bare], executor="automation", ready=False)
    client.post(f"{V1}/tasks/{task}/status", json={"status": "ready", "allow_missing_scripts": True})
    install_runner(client, FakeRunner())
    out = client.post(f"{V1}/versions/{w['version']}/run-tasks", json={"start_testing": False}).json()
    assert out["started"] == [] and out["skipped"][0]["code"] == "MISSING_SCRIPTS"
    assert out["version_testing"] is False
    ok = client.post(f"{V1}/versions/{w['version']}/run-tasks", json={"allow_missing_scripts": True}).json()
    assert len(ok["started"]) == 1


def test_next_step_runs_tasks(client, db):
    w = build_world(client, db)

    def runs_action():
        p = client.get(f"{V1}/suts/{w['sut']}/progress", params={"version_id": w["version"]}).json()
        return next(s for s in p["steps"] if s["key"] == "runs")["action"]

    # nothing to run yet: the button says what is missing instead of pretending to run
    assert runs_action()["label"] == "New task"
    a = make_case(client, w, "A")
    task = make_task(client, w, [a], name="T1", ready=False)
    assert runs_action()["label"] == "Set tasks ready"
    client.post(f"{V1}/tasks/{task}/status", json={"status": "ready"})
    assert runs_action() == {
        "label": "Run tasks",
        "path": f"/versions/{w['version']}?tab=strategy",
        "kind": "run_tasks",
        "version_id": w["version"],
    }
