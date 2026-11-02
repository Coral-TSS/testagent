"""environment preflight (fail fast with a readable hint, no self-check attempts spent, no
"needs fix" for a stopped system) and starting an environment from its start command."""

from __future__ import annotations

import socket
import sys

import pytest
from tests.api.world import V1, FakeRunner, build_world, install_runner, make_case, make_task

from testagent.agent.fake import FakeChatModel
from testagent.services.environments import EnvironmentProcesses, probe

pytestmark = pytest.mark.preflight
DOWN = "http://127.0.0.1:9"  # discard port: nothing listens there


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_probe_open_and_closed_port():
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        assert probe(f"http://127.0.0.1:{srv.getsockname()[1]}/")[0] is True
    assert probe(DOWN)[0] is False


def test_automation_with_stopped_environment_spends_nothing(client, db):
    w = build_world(client, db)
    case = make_case(client, w, "Amount 0 shows an error")
    fake = FakeChatModel(script=[])
    client.app.state.agent.models.builder = lambda cfg: fake
    resp = client.post(f"{V1}/cases/{case}/automate", json={"environment_id": w["env"]})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["status"] == "env_unavailable" and out["error_code"] == "ENV_UNREACHABLE"
    assert "127.0.0.1:9" in out["reason"] and "unreachable" in out["reason"]
    assert fake.seen == []  # no agent run, no self-check attempts
    row = client.get(f"{V1}/cases/{case}").json()
    assert row["automation_status"] == "env_unavailable" and row["mode"] == "manual"
    # retryable: the batch picks the case up again
    batch = client.post(f"{V1}/versions/{w['version']}/automate", json={})
    assert batch.json()["queued"] == 1


def test_debug_and_manual_run_fail_fast(client, db):
    w = build_world(client, db)
    case = make_case(client, w, "Amount 0 shows an error")
    install_runner(client, FakeRunner())
    resp = client.post(f"{V1}/cases/{case}/debug", json={"environment_id": w["env"], "executor": "agent_browser"})
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["code"] == "ENV_UNREACHABLE" and "start the SUT first" in body["message"]
    assert client.get(f"{V1}/cases/{case}/executions").json() == []
    task = make_task(client, w, [case])
    run = client.post(f"{V1}/tasks/{task}/run")
    assert run.status_code == 503 and run.json()["code"] == "ENV_UNREACHABLE"


def test_scheduled_run_with_stopped_environment_ends_in_error(client, db):
    w = build_world(client, db)
    case = make_case(client, w, "One")
    runner = FakeRunner()
    install_runner(client, runner)
    task = make_task(client, w, [case])
    with db.tx() as cur:
        run = client.app.state.runs_factory("scheduler").start(task, "schedule", cur=cur)
    assert client.app.state.worker.run_once() is True
    detail = client.get(f"{V1}/runs/{run['id']}").json()
    assert detail["status"] == "error" and "ENV_UNREACHABLE" in detail["error"]
    assert runner.order == []


def test_start_environment_from_start_command(client, db, tmp_path):
    w = build_world(client, db)
    port = free_port()
    command = f'"{sys.executable}" -m http.server {port} --bind 127.0.0.1'
    env = client.post(
        f"{V1}/suts/{w['sut']}/environments",
        json={"name": "local", "base_url": f"http://127.0.0.1:{port}", "start_command": command},
    ).json()
    assert env["start_command"] == command
    check = client.get(f"{V1}/environments/{env['id']}/check").json()
    assert check["reachable"] is False and "“Start”" in check["message"]
    procs: EnvironmentProcesses = client.app.state.env_processes
    procs.log_dir = tmp_path
    try:
        started = client.post(f"{V1}/environments/{env['id']}/start").json()
        assert started["reachable"] is True and started["started"] is True, started
        assert client.get(f"{V1}/environments/{env['id']}/check").json()["reachable"] is True
    finally:
        procs.stop_all()
    no_cmd = client.post(f"{V1}/environments/{w['env']}/start")
    assert no_cmd.status_code == 422
