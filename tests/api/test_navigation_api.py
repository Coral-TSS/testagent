"""breadcrumbs for every detail object and the main-flow step bar."""

from __future__ import annotations

from tests.api.world import (
    V1,
    FakeRunner,
    build_world,
    install_runner,
    make_case,
    make_task,
    run_task,
)


def crumbs(client, kind, id_):
    resp = client.get(f"{V1}/nav/context", params={"kind": kind, "id": id_})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return (
        body,
        [(c["kind"], c["label"]) for c in body["crumbs"]],
        [c["path"] for c in body["crumbs"]],
    )


def test_context_chains_for_every_detail_page(client, db):
    w = build_world(client, db)
    case = make_case(client, w, "Amount approval")
    task = make_task(client, w, [case], name="Regression task")
    install_runner(client, FakeRunner({"Amount approval": "failed"}))
    run = run_task(client, task)
    execution = run["executions"][0]["id"]
    defect = client.post(f"{V1}/executions/{execution}/defect", json={}).json()
    report = client.get(f"{V1}/reports", params={"version_id": w["version"]}).json()[0]

    body, labels, paths = crumbs(client, "sut", w["sut"])
    assert labels == [("sut", "Shop (SHOP)")] and paths == [f"/suts/{w['sut']}"]
    assert body["sut"]["code"] == "SHOP" and body["version"] is None

    body, labels, _ = crumbs(client, "version", w["version"])
    assert labels == [("sut", "Shop (SHOP)"), ("version", "Version v1")]
    assert body["version"]["id"] == w["version"]
    version = client.get(f"{V1}/versions/{w['version']}").json()
    assert (version["sut_code"], version["sut_name"]) == ("SHOP", "Shop")

    _, labels, paths = crumbs(client, "requirement", w["reqs"]["REQ-001"])
    assert labels[-1] == ("requirement", "Requirement1 (REQ-001)")
    assert paths[-1] == f"/versions/{w['version']}?req={w['reqs']['REQ-001']}"

    _, labels, paths = crumbs(client, "task", task)
    assert [k for k, _ in labels] == ["sut", "version", "strategy", "task"]
    assert labels[-1] == ("task", "Regression task") and paths[2].endswith("?tab=strategy")
    assert client.get(f"{V1}/tasks/{task}").json()["version_name"] == "v1"

    _, labels, paths = crumbs(client, "run", run["id"])
    assert [k for k, _ in labels] == ["sut", "version", "strategy", "task", "run"]
    assert labels[-1][1].startswith("Run ") and paths[-1] == f"/runs/{run['id']}"

    body, labels, _ = crumbs(client, "execution", execution)
    assert [k for k, _ in labels] == ["sut", "version", "strategy", "task", "run", "execution"]
    assert labels[-1] == ("execution", "Amount approval (TC-001) execution")
    assert body["version"]["name"] == "v1"

    _, labels, paths = crumbs(client, "case", case)
    assert labels == [
        ("sut", "Shop (SHOP)"),
        ("version", "Version v1"),
        ("cases", "Case"),
        ("case", "Amount approval (TC-001)"),
    ]
    assert paths[2] == f"/versions/{w['version']}?tab=cases"

    _, labels, _ = crumbs(client, "defect", defect["id"])
    assert [k for k, _ in labels] == ["sut", "version", "defects", "defect"]
    assert labels[-1][1].endswith("(DEF-001)")

    _, labels, _ = crumbs(client, "report", report["id"])
    assert [k for k, _ in labels][:2] == ["sut", "version"] and labels[-1][0] == "report"

    assert client.get(f"{V1}/nav/context", params={"kind": "case", "id": w["sut"]}).status_code == 404


def test_progress_walks_the_main_flow(client, db):
    sut = client.post(f"{V1}/suts", json={"code": "NEW", "name": "New system"}).json()["id"]
    p = client.get(f"{V1}/suts/{sut}/progress").json()
    keys = [s["key"] for s in p["steps"]]
    assert keys == ["sut", "model", "requirements", "strategy", "tasks", "cases", "runs", "results"]
    assert [s["status"] for s in p["steps"]][:2] == ["todo", "todo"]
    assert p["next"]["key"] == "sut" and p["next"]["label"] == "Add environment"
    assert p["version"] is None and p["repo_path"].endswith("NEW")

    client.post(f"{V1}/suts/{sut}/environments", json={"name": "t", "base_url": "http://x:1"})
    p = client.get(f"{V1}/suts/{sut}/progress").json()
    assert p["steps"][0]["status"] == "done" and p["next"]["key"] == "model"

    w = build_world(client, db)  # frozen version with confirmed requirements
    client.post(f"{V1}/suts/{w['sut']}/nodes", json={"kind": "entity", "name": "Order"})
    client.post(f"{V1}/suts/{w['sut']}/nodes", json={"kind": "action", "name": "Place order"})
    p = client.get(f"{V1}/suts/{w['sut']}/progress").json()
    status = {s["key"]: s["status"] for s in p["steps"]}
    assert status["model"] == "done" and status["requirements"] == "done"
    assert p["version"]["id"] == w["version"]
    assert p["next"]["key"] == "strategy"
    case = make_case(client, w, "Order placed")
    task = make_task(client, w, [case])
    install_runner(client, FakeRunner())
    run_task(client, task)
    p = client.get(f"{V1}/suts/{w['sut']}/progress", params={"version_id": w["version"]}).json()
    status = {s["key"]: s["status"] for s in p["steps"]}
    assert status["tasks"] == "done" and status["cases"] == "done" and status["runs"] == "done"
    runs = next(s for s in p["steps"] if s["key"] == "runs")
    assert "Passed" in runs["summary"] and runs["path"].startswith("/runs/")
    assert [v["name"] for v in p["versions"]] == ["v1"]
