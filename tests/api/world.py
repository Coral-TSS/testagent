"""Shared test world for M1-09..M1-11: a frozen version with people, requirements and cases."""

from __future__ import annotations

V1 = "/api/v1"


def build_world(client, db, *, n_reqs: int = 2) -> dict:
    sut = client.post(f"{V1}/suts", json={"code": "SHOP", "name": "Shop"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1"}).json()["id"]
    people = {
        name: client.post(f"{V1}/persons", json={"name": name}).json()["id"]
        for name in ("Pat Product", "Lee Dev", "Zhao Dev", "Quinn Tester")
    }
    roles = [
        [("Pat Product", "owner"), ("Lee Dev", "developer"), ("Quinn Tester", "tester")],
        [("Pat Product", "owner"), ("Zhao Dev", "developer"), ("Quinn Tester", "tester")],
    ]
    reqs = {}
    for i in range(n_reqs):
        title = f"Requirement{i + 1}"
        req = client.post(f"{V1}/versions/{version}/requirements", json={"title": title}).json()
        body = [{"person_id": people[n], "role": r} for n, r in roles[i % 2]]
        assert client.put(f"{V1}/requirements/{req['id']}/people", json=body).status_code == 200
        client.put(f"{V1}/requirements/{req['id']}/structure", json={"action": [{"text": title}]})
        assert client.post(f"{V1}/requirements/{req['id']}/confirm").status_code == 200
        reqs[req["code"]] = req["id"]
    assert client.post(f"{V1}/versions/{version}/freeze").status_code == 200
    env = client.post(f"{V1}/suts/{sut}/environments", json={"name": "test", "base_url": "http://127.0.0.1:9"}).json()[
        "id"
    ]
    return {"sut": sut, "version": version, "people": people, "reqs": reqs, "env": env, "db": db}


def make_case(client, world, title, *, req_codes=("REQ-001",), status="ready", **extra) -> str:
    body = {
        "title": title,
        "steps": [{"action": "Action", "expected": "Result"}],
        "requirement_ids": [world["reqs"][c] for c in req_codes],
        **extra,
    }
    resp = client.post(f"{V1}/suts/{world['sut']}/cases", json=body)
    assert resp.status_code == 201, resp.text
    case_id = resp.json()["id"]
    if status != "draft":
        client.post(f"{V1}/cases/{case_id}/status", json={"status": "ready"})
    if status == "deprecated":
        client.post(f"{V1}/cases/{case_id}/status", json={"status": "deprecated"})
    return case_id


def make_task(client, world, case_ids, *, executor="agent", name="Task", ready=True) -> str:
    resp = client.post(
        f"{V1}/versions/{world['version']}/tasks",
        json={
            "name": name,
            "executor": executor,
            "environment_id": world["env"],
            "case_ids": case_ids,
        },
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["id"]
    if ready:
        assert client.post(f"{V1}/tasks/{task_id}/status", json={"status": "ready"}).status_code == 200
    return task_id


class FakeRunner:
    """Executor override: verdicts by case title; records the order cases were executed in."""

    def __init__(self, verdicts: dict[str, str] | None = None, on_case=None):
        self.verdicts = verdicts or {}
        self.order: list[str] = []
        self.on_case = on_case

    def __call__(self, case, env, execution_id):
        self.order.append(case["title"])
        if self.on_case:
            self.on_case(case)
        status = self.verdicts.get(case["title"], "passed")
        if status == "crash":
            raise RuntimeError("browser crashed")
        fields = {"status": status, "result": f"fake {status}"}
        if status == "failed":
            fields["failed_assertion"] = f"{case['title']} Assertion failed"
        return fields


def install_runner(client, runner) -> None:
    client.app.state.executor_runners["agent_browser"] = runner
    client.app.state.executor_runners["pytest"] = runner


def run_task(client, task_id) -> dict:
    resp = client.post(f"{V1}/tasks/{task_id}/run")
    assert resp.status_code == 201, resp.text
    assert client.app.state.worker.run_once() is True
    return client.get(f"{V1}/runs/{resp.json()['id']}").json()
