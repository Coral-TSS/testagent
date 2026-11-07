"""Demo #14: every task keeps a direct route back to its latest execution."""

from uuid import UUID

from tests.api.world import V1, FakeRunner, build_world, install_runner, make_case, make_task, run_task


def task_rows(client, version):
    response = client.get(f"{V1}/versions/{version}/tasks")
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()}


def test_latest_run_absent_and_version_scoped(client, db):
    world = build_world(client, db)
    task = make_task(client, world, [], ready=False)
    other_version = client.post(f"{V1}/suts/{world['sut']}/versions", json={"name": "v2"}).json()["id"]
    other_task = client.post(f"{V1}/versions/{other_version}/tasks", json={"name": "Other task"}).json()["id"]
    rows = task_rows(client, world["version"])
    assert set(rows) == {task}
    assert rows[task]["latest_run"] is None
    assert task_rows(client, other_version)[other_task]["latest_run"] is None


def test_latest_run_tracks_queue_progress_and_completion(client, db):
    world = build_world(client, db)
    case_ids = [make_case(client, world, title) for title in ("First", "Second")]
    task = make_task(client, world, case_ids)
    queued = client.post(f"{V1}/tasks/{task}/run").json()
    summary = task_rows(client, world["version"])[task]["latest_run"]
    assert summary["id"] == queued["id"]
    assert summary["status"] == "queued"
    assert summary["counts"] == {
        "total": 0,
        "done": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "blocked": 0,
        "skipped": 0,
    }

    progress = []

    def observe(case):
        if case["title"] == "Second":
            progress.append(task_rows(client, world["version"])[task]["latest_run"])

    install_runner(client, FakeRunner(on_case=observe))
    assert client.app.state.worker.run_once()
    assert progress[0]["status"] == "running"
    assert progress[0]["counts"]["done"] == 1
    assert progress[0]["counts"]["total"] == 2
    completed = task_rows(client, world["version"])[task]["latest_run"]
    assert completed["id"] == queued["id"]
    assert completed["status"] == "passed"
    assert completed["counts"] == {
        "total": 2,
        "done": 2,
        "passed": 2,
        "failed": 0,
        "error": 0,
        "blocked": 0,
        "skipped": 0,
    }


def test_latest_run_is_per_task_not_a_limited_recent_run_feed(client, db):
    world = build_world(client, db)
    cases = [make_case(client, world, "One")]
    old_task = make_task(client, world, cases, name="Infrequent")
    busy_task = make_task(client, world, cases, name="Frequent")
    with db.tx() as cur:
        cur.execute(
            "INSERT INTO task_run(task_id, trigger, executor, status, created_at)"
            " VALUES (%s, 'manual', 'agent', 'failed', now() - interval '1 day') RETURNING id::text AS id",
            (old_task,),
        )
        old_run = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task_run(task_id, trigger, executor, status)"
            " SELECT %s, 'schedule', 'agent', 'passed' FROM generate_series(1, 205)",
            (busy_task,),
        )
    rows = task_rows(client, world["version"])
    assert rows[old_task]["latest_run"]["id"] == old_run
    assert rows[old_task]["latest_run"]["status"] == "failed"
    assert rows[busy_task]["latest_run"]["task_id"] == busy_task


def test_latest_run_switches_to_rerun_and_breaks_timestamp_ties(client, db):
    world = build_world(client, db)
    task = make_task(client, world, [make_case(client, world, "One")])
    install_runner(client, FakeRunner())
    first = run_task(client, task)
    second = client.post(f"{V1}/tasks/{task}/run").json()
    assert task_rows(client, world["version"])[task]["latest_run"]["id"] == second["id"]
    with db.tx() as cur:
        cur.execute("UPDATE task_run SET created_at='2026-11-01T00:00:00Z' WHERE task_id=%s", (task,))
    expected = max((first["id"], second["id"]), key=UUID)
    assert task_rows(client, world["version"])[task]["latest_run"]["id"] == expected
