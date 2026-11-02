"""M1-07 test cases: CRUD + revisions + human-only ready, AI generation, coverage, export."""

import csv
import io

import pytest

from testagent.agent.fake import FakeChatModel, call
from testagent.core.errors import AppError
from testagent.services.cases import CaseService

V1 = "/api/v1"


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


@pytest.fixture
def world(client):
    sut = client.post(f"{V1}/suts", json={"code": "SHOP", "name": "Shop"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1"}).json()["id"]
    nodes = {
        name: client.post(f"{V1}/suts/{sut}/nodes", json={"kind": kind, "name": name}).json()["id"]
        for kind, name in [
            ("entity", "PurchaseOrder"),
            ("action", "Create purchase order"),
            ("action", "Approve purchase order"),
            ("action", "Export purchase orders"),
        ]
    }
    reqs = {}
    for title in ("Create purchase order", "Approve purchase order", "Export purchase orders"):
        req = client.post(f"{V1}/versions/{version}/requirements", json={"title": title}).json()
        reqs[req["code"]] = req["id"]
    return {"sut": sut, "version": version, "nodes": nodes, "reqs": reqs}


def new_case(client, world, **extra):
    body = {
        "title": "Cannot submit when the amount is 0",
        "test_point": "Amount boundary",
        "scenario": "boundary",
        "steps": [
            {"action": "Open the create page"},
            {"action": "Enter amount 0 and submit", "expected": "An error is shown"},
        ],
        "test_data": {"amount": 0},
        "expected": "Submission refused",
        "requirement_ids": [world["reqs"]["REQ-001"]],
        "node_ids": [world["nodes"]["Create purchase order"]],
        **extra,
    }
    resp = client.post(f"{V1}/suts/{world['sut']}/cases", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ------------------------------------------------------------------ CRUD
def test_manual_case_gets_code_and_links(client, world):
    first = new_case(client, world)
    second = new_case(client, world, title="Created normally")
    assert (first["code"], second["code"]) == ("TC-001", "TC-002")
    assert first["status"] == "draft" and first["source"] == "human" and first["revision"] == 1
    assert [r["code"] for r in first["requirements"]] == ["REQ-001"]
    assert [n["name"] for n in first["nodes"]] == ["Create purchase order"]
    listed = client.get(f"{V1}/suts/{world['sut']}/cases", params={"version_id": world["version"]})
    assert [c["code"] for c in listed.json()] == ["TC-001", "TC-002"]
    by_req = client.get(f"{V1}/suts/{world['sut']}/cases", params={"requirement_id": world["reqs"]["REQ-002"]})
    assert by_req.json() == []


def test_links_must_belong_to_the_sut(client, world):
    other = client.post(f"{V1}/suts", json={"code": "OTHER", "name": "x"}).json()["id"]
    foreign = client.post(f"{V1}/suts/{other}/nodes", json={"kind": "action", "name": "x"}).json()
    resp = client.post(f"{V1}/suts/{world['sut']}/cases", json={"title": "t", "node_ids": [foreign["id"]]})
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION"


def test_case_revision_on_update(client, world):
    case = new_case(client, world)
    same = client.patch(f"{V1}/cases/{case['id']}", json={"title": case["title"]}).json()
    assert same["revision"] == 1  # no content change, no new revision
    updated = client.patch(
        f"{V1}/cases/{case['id']}",
        json={"expected": "Shows “Amount must be greater than 0”", "node_ids": []},
    ).json()
    assert updated["revision"] == 2 and updated["nodes"] == []
    revisions = client.get(f"{V1}/cases/{case['id']}/revisions").json()
    assert [r["revision"] for r in revisions] == [2, 1]
    assert revisions[1]["content"]["expected"] == "Submission refused"
    assert revisions[0]["content"]["expected"] == "Shows “Amount must be greater than 0”"
    assert revisions[0]["author"] == "local-user"


def test_only_human_sets_ready(client, world, db):
    case = new_case(client, world)
    agent = CaseService(db, client.app.state.bus, actor="agent:run-1")
    with pytest.raises(AppError) as err:
        agent.set_status(case["id"], "ready")
    assert err.value.code == "VALIDATION"
    ok = client.post(f"{V1}/cases/{case['id']}/status", json={"status": "ready"})
    assert ok.status_code == 200 and ok.json()["status"] == "ready"
    # an agent edit of a ready case sends it back to draft for human review
    edited = agent.update(case["id"], {"expected": "changed"})
    assert edited["status"] == "draft" and edited["revision"] == 2
    bad = client.post(f"{V1}/cases/{case['id']}/status", json={"status": "deprecated"})
    assert bad.status_code == 409 and bad.json()["code"] == "INVALID_TRANSITION"


def test_deprecated_case_is_read_only(client, world):
    case = new_case(client, world)
    client.post(f"{V1}/cases/{case['id']}/status", json={"status": "ready"})
    client.post(f"{V1}/cases/{case['id']}/status", json={"status": "deprecated"})
    resp = client.patch(f"{V1}/cases/{case['id']}", json={"title": "x"})
    assert resp.status_code == 409


# ------------------------------------------------------------------ generation
def drafts(world, code, n=3, node=None, scenarios=("normal", "boundary", "exception")):
    return [
        {
            "title": f"{code} Case {i}",
            "test_point": f"Test point {i}",
            "scenario": scenarios[i % len(scenarios)],
            "priority": "P1",
            "steps": [{"action": "Open the page"}, {"action": "Submit", "expected": "Success"}],
            "test_data": {"i": i},
            "expected": "Meets the requirement",
            "requirement_codes": [code],
            "node_ids": [node] if node else [],
        }
        for i in range(n)
    ]


def test_generate_cases_min_per_requirement(client, world):
    n = world["nodes"]
    short = drafts(world, "REQ-001", 2)
    full = (
        drafts(world, "REQ-001", 3, n["Create purchase order"])
        + drafts(world, "REQ-002", 3, n["Approve purchase order"])
        + drafts(world, "REQ-003", 4)
    )
    fake = use_model(client, call("submit_result", {"cases": short}), call("submit_result", {"cases": full}))
    out = client.post(f"{V1}/versions/{world['version']}/cases/generate", json={})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["status"] == "succeeded" and len(body["cases"]) == 10
    run = client.get(f"{V1}/agent/runs/{body['agent_run_id']}").json()
    invalid = [s for s in run["steps"] if s["type"] == "submit_invalid"]
    assert invalid and any("REQ-002" in e["msg"] for e in invalid[0]["errors"])
    assert fake.position == 2
    # coverage report produced at creation
    cov = body["coverage"]
    assert cov["requirements"]["covered"] == 3 and cov["requirements"]["uncovered"] == []
    assert {a["name"] for a in cov["actions"]["uncovered"]} == {"Export purchase orders"}


def test_cases_link_requirements_and_nodes(client, world):
    n = world["nodes"]
    cases = drafts(world, "REQ-001", 3, n["Create purchase order"])
    cases[0]["requirement_codes"] = ["REQ-001", "REQ-002"]
    cases += drafts(world, "REQ-002", 3, n["Approve purchase order"])
    use_model(client, call("submit_result", {"cases": cases}))
    body = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["reqs"]["REQ-001"], world["reqs"]["REQ-002"]]},
    ).json()
    assert body["status"] == "succeeded"
    first = client.get(f"{V1}/cases/{body['cases'][0]['id']}").json()
    assert [r["code"] for r in first["requirements"]] == ["REQ-001", "REQ-002"]
    assert [x["name"] for x in first["nodes"]] == ["Create purchase order"]
    assert first["source"] == "agent" and first["agent_run_id"] == body["agent_run_id"]
    assert first["status"] == "draft" and first["scenario"] == "normal"
    assert first["steps"][1] == {"action": "Submit", "expected": "Success"}
    req = client.get(f"{V1}/requirements/{world['reqs']['REQ-002']}").json()
    assert len(req["cases"]) == 4


def test_unknown_node_ref_rejected(client, world):
    bad = drafts(world, "REQ-001", 3, "00000000-0000-0000-0000-000000000001")
    good = drafts(world, "REQ-001", 3, world["nodes"]["Create purchase order"])
    use_model(
        client,
        call("submit_result", {"cases": bad}),
        call("submit_result", {"cases": bad}),
        call("submit_result", {"cases": bad}),
        call("submit_result", {"cases": good}),
    )
    body = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["reqs"]["REQ-001"]]},
    ).json()
    assert body["status"] == "failed" and body["error_code"] == "VALIDATION"
    assert client.get(f"{V1}/suts/{world['sut']}/cases").json() == []


def test_generate_unknown_requirement_404(client, world):
    use_model(client)
    resp = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": ["00000000-0000-0000-0000-000000000001"]},
    )
    assert resp.status_code == 404


# ------------------------------------------------------------------ coverage / export
def test_coverage_lists_uncovered(client, world):
    n, r = world["nodes"], world["reqs"]
    new_case(client, world, priority="P0", type_tag="functional", scenario="normal")
    new_case(
        client,
        world,
        priority="P1",
        scenario="exception",
        requirement_ids=[r["REQ-001"], r["REQ-002"]],
        node_ids=[n["Create purchase order"], n["Approve purchase order"], n["PurchaseOrder"]],
    )
    dep = new_case(client, world, requirement_ids=[r["REQ-003"]], node_ids=[n["Export purchase orders"]])
    client.post(f"{V1}/cases/{dep['id']}/status", json={"status": "ready"})
    client.post(f"{V1}/cases/{dep['id']}/status", json={"status": "deprecated"})

    cov = client.get(f"{V1}/versions/{world['version']}/coverage").json()
    # 3 requirements, REQ-003 only has a deprecated case → 2/3 covered
    assert cov["requirements"]["total"] == 3 and cov["requirements"]["covered"] == 2
    assert [u["code"] for u in cov["requirements"]["uncovered"]] == ["REQ-003"]
    assert {x["code"]: x["cases"] for x in cov["requirements"]["items"]} == {
        "REQ-001": 2,
        "REQ-002": 1,
        "REQ-003": 0,
    }
    # 3 action nodes (entity PurchaseOrder does not count), Export not covered
    assert cov["actions"]["total"] == 3 and cov["actions"]["covered"] == 2
    assert [u["name"] for u in cov["actions"]["uncovered"]] == ["Export purchase orders"]
    assert cov["cases"] == 2
    assert cov["by_priority"] == {"P0": 1, "P1": 1}
    assert cov["by_type"] == {"functional": 2}
    assert cov["by_scenario"] == {"normal": 1, "exception": 1}
    saved = client.post(f"{V1}/versions/{world['version']}/coverage").json()
    assert saved["id"] and saved["content"]["requirements"]["covered"] == 2


def test_case_list_export_columns(client, world):
    new_case(client, world)
    resp = client.get(f"{V1}/versions/{world['version']}/cases/export", params={"format": "csv"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    text = resp.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == [
        "Code",
        "Title",
        "Test point",
        "Requirements",
        "Nodes",
        "Priority",
        "Type",
        "Scenario",
        "Preconditions",
        "Steps",
        "Test data",
        "Expected result",
        "Status",
        "Mode",
    ]
    assert rows[1][0] == "TC-001" and rows[1][3] == "REQ-001" and rows[1][7] == "Boundary"
    assert "1. Open the create page" in rows[1][9] and "→ An error is shown" in rows[1][9]
    md = client.get(f"{V1}/versions/{world['version']}/cases/export", params={"format": "md"})
    assert md.headers["content-type"].startswith("text/markdown")
    lines = md.text.splitlines()
    assert lines[0].startswith("| Code | Title |") and lines[2].startswith("| TC-001 |")


# ------------------------------------------------------------------ corrections
def test_correction_saved_with_target(client, world):
    case = new_case(client, world)
    resp = client.post(
        f"{V1}/corrections",
        json={"target_type": "case", "target_id": case["id"], "content": "Boundary values should include 0.01"},
    )
    assert resp.status_code == 201 and resp.json()["status"] == "pending"
    listed = client.get(f"{V1}/corrections", params={"target_id": case["id"]}).json()
    assert [c["content"] for c in listed] == ["Boundary values should include 0.01"]
    bad = client.post(
        f"{V1}/corrections",
        json={"target_type": "case", "target_id": world["sut"], "content": "x"},
    )
    assert bad.status_code == 404


def test_generated_scenario_type_tag_is_normalised(client, world):
    """the model wrote 'boundary' into type_tag; it is a scenario, the type is functional."""
    cases = drafts(world, "REQ-001", 3)
    cases[1]["type_tag"] = "boundary"
    cases[2]["type_tag"] = "exception"
    use_model(client, call("submit_result", {"cases": cases}))
    body = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["reqs"]["REQ-001"]]},
    ).json()
    rows = [client.get(f"{V1}/cases/{c['id']}").json() for c in body["cases"]]
    assert [(r["type_tag"], r["scenario"]) for r in rows] == [
        ("functional", "normal"),
        ("functional", "boundary"),
        ("functional", "exception"),
    ]
