"""Readable logs (refs resolved to Name (code)), coverage detail by name, batch case
actions, and AI completion for hand-written cases (proposal → human accept)."""

from __future__ import annotations

import logging

import pytest

from testagent.agent.fake import FakeChatModel, call
from testagent.core.errors import AppError
from testagent.services.case_complete import CaseCompletionService
from testagent.services.labels import describe, resolve_refs

V1 = "/api/v1"


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


@pytest.fixture
def world(client):
    sut = client.post(f"{V1}/suts", json={"code": "PROC", "name": "Procurement approval"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1"}).json()["id"]

    def node(kind, name):
        resp = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": kind, "name": name})
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    order, supplier = node("entity", "PurchaseOrder"), node("entity", "Supplier")
    approve, export = node("action", "Approve purchase order"), node("action", "Export purchase orders")
    amount = client.post(f"{V1}/nodes/{order}/fields", json={"name": "amount", "data_type": "number"}).json()["id"]
    supplier_id = client.post(
        f"{V1}/nodes/{order}/fields",
        json={"name": "supplier_id", "data_type": "reference", "ref_node_id": supplier},
    ).json()["id"]
    link = client.post(
        f"{V1}/suts/{sut}/links",
        json={
            "from_node_id": order,
            "to_node_id": supplier,
            "forward_name": "belongs to",
            "reverse_name": "supplies",
            "cardinality": "many_to_one",
        },
    ).json()["id"]
    req = client.post(f"{V1}/versions/{version}/requirements", json={"title": "Approve purchase order"}).json()
    structure = {
        "action": [{"text": "Approve", "node_id": approve}],
        "condition": [{"text": "Amount", "attribute_id": amount}],
        "constraint": [{"text": "Supplier", "link_id": link}],
    }
    resp = client.put(f"{V1}/requirements/{req['id']}/structure", json=structure)
    assert resp.status_code == 200, resp.text
    return {
        "sut": sut,
        "version": version,
        "req": req["id"],
        "nodes": {"order": order, "supplier": supplier, "approve": approve, "export": export},
        "fields": {"amount": amount, "supplier_id": supplier_id},
        "link": link,
    }


def new_case(client, world, title="Large-amount approval", **extra):
    body = {
        "title": title,
        "steps": [{"action": "Submit for approval"}],
        "requirement_ids": [world["req"]],
        "node_ids": [world["nodes"]["approve"]],
        "attribute_ids": [world["fields"]["amount"]],
        "origin_version_id": world["version"],
        **extra,
    }
    resp = client.post(f"{V1}/suts/{world['sut']}/cases", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ------------------------------------------------------------------ item 5: readable refs
def test_resolve_refs_names_and_links(client, world, db):
    case = new_case(client, world)
    refs = resolve_refs(db, [case["id"], world["sut"], world["version"], world["req"], "x"])
    assert refs[case["id"]]["label"] == "Large-amount approval (TC-001)"
    assert refs[case["id"]]["path"] == f"/cases/{case['id']}"
    assert refs[world["sut"]]["label"] == "Procurement approval (PROC)"
    assert refs[world["req"]]["label"] == "Approve purchase order (REQ-001)"
    assert refs[world["version"]]["kind"] == "Version"
    text = describe(refs, [case["id"], world["sut"]])
    assert text == "Case “Large-amount approval (TC-001)” · SUT “Procurement approval (PROC)”"


def test_access_log_names_the_case(client, world, caplog):
    case = new_case(client, world)
    with caplog.at_level(logging.INFO, logger="testagent.access"):
        client.patch(f"{V1}/cases/{case['id']}", json={"expected": "Approve"})
    lines = [r.getMessage() for r in caplog.records if r.name == "testagent.access"]
    assert len(lines) == 1
    assert lines[0].startswith("PATCH /api/v1/cases/{case_id} → 200 (")
    assert lines[0].endswith("· Case “Large-amount approval (TC-001)”")
    assert case["id"] not in lines[0]


def test_worker_log_names_the_job_subject(client, world, caplog):
    case = new_case(client, world)
    client.post(f"{V1}/cases/batch", json={"case_ids": [case["id"]], "action": "complete"})
    use_model(client, call("submit_result", proposal_body(world)))
    with caplog.at_level(logging.INFO, logger="testagent.worker"):
        assert client.app.state.worker.run_once() is True
    lines = [r.getMessage() for r in caplog.records if r.name == "testagent.worker"]
    assert any("AI complete case started · Case “Large-amount approval (TC-001)”" in m for m in lines), lines
    assert any("AI complete case done" in m for m in lines), lines


def test_agent_runs_list_shows_subjects(client, world):
    case = new_case(client, world)
    use_model(client, call("submit_result", proposal_body(world)))
    out = client.post(f"{V1}/cases/{case['id']}/ai-complete").json()
    runs = client.get(f"{V1}/agent/runs").json()
    row = next(r for r in runs if r["id"] == out["agent_run_id"])
    assert [s["kind"] for s in row["subjects"]] == ["Case", "Version", "SUT"]
    assert row["subjects"][0]["label"] == "Large-amount approval (TC-001)"
    assert row["subjects"][0]["path"] == f"/cases/{case['id']}"
    detail = client.get(f"{V1}/agent/runs/{out['agent_run_id']}").json()
    assert detail["subjects"][0]["label"] == "Large-amount approval (TC-001)"
    assert detail["labels"][case["id"]] == "Large-amount approval (TC-001)"


# ------------------------------------------------------------------ item 2: coverage detail
def test_case_coverage_detail_by_name(client, world):
    case = new_case(client, world, attribute_ids=[world["fields"]["supplier_id"]])
    rows = client.get(f"{V1}/suts/{world['sut']}/cases", params={"version_id": world["version"]}).json()
    cov = rows[0]["coverage"]
    assert [a["name"] for a in cov["actions"]] == ["Approve purchase order"]
    assert [f["name"] for f in cov["fields"]] == ["PurchaseOrder.supplier_id"]
    assert [r["name"] for r in cov["relations"]] == ["PurchaseOrder belongs to Supplier"]
    detail = client.get(f"{V1}/cases/{case['id']}").json()
    assert [r["name"] for r in detail["relations"]] == ["PurchaseOrder belongs to Supplier"]


def test_version_coverage_lists_covering_cases(client, world):
    case = new_case(client, world)
    new_case(client, world, title="Export", node_ids=[world["nodes"]["export"]], attribute_ids=[])
    cov = client.get(f"{V1}/versions/{world['version']}/coverage").json()
    assert cov["sut_id"] == world["sut"]
    actions = {i["name"]: i for i in cov["actions"]["items"]}
    assert [c["code"] for c in actions["Approve purchase order"]["case_list"]] == ["TC-001"]
    assert actions["Approve purchase order"]["case_list"][0]["id"] == case["id"]
    fields = {i["name"]: i for i in cov["fields"]["items"]}
    assert [c["code"] for c in fields["PurchaseOrder.amount"]["case_list"]] == ["TC-001"]
    assert fields["PurchaseOrder.amount"]["node_id"] == world["nodes"]["order"]
    rel = cov["relations"]
    assert rel["total"] == 1 and rel["covered"] == 1
    assert [c["code"] for c in rel["items"][0]["case_list"]] == ["TC-001", "TC-002"]
    reqs = cov["requirements"]["items"]
    assert [c["code"] for c in reqs[0]["case_list"]] == ["TC-001", "TC-002"]


def test_requirement_coverage_per_element(client, world):
    new_case(client, world)
    new_case(client, world, title="Steps only", node_ids=[], attribute_ids=[])
    req = client.get(f"{V1}/requirements/{world['req']}").json()
    cov = req["coverage"]
    assert [(a["name"], [c["code"] for c in a["cases"]]) for a in cov["actions"]] == [
        ("Approve purchase order", ["TC-001"])
    ]
    assert [(f["name"], [c["code"] for c in f["cases"]]) for f in cov["fields"]] == [
        ("PurchaseOrder.amount", ["TC-001"])
    ]
    assert cov["relations"][0]["name"] == "PurchaseOrder belongs to Supplier"


# ------------------------------------------------------------------ item 4: batch
def test_batch_status_reports_each_case(client, world):
    a = new_case(client, world, title="A")
    b = new_case(client, world, title="B")
    out = client.post(f"{V1}/cases/batch", json={"case_ids": [a["id"], b["id"]], "action": "ready"}).json()
    assert [c["code"] for c in out["ok"]] == ["TC-001", "TC-002"] and not out["failed"]
    again = client.post(f"{V1}/cases/batch", json={"case_ids": [a["id"]], "action": "ready"})
    assert again.json()["skipped"][0]["reason"] == "Already in the target state"
    client.post(f"{V1}/cases/{b['id']}/status", json={"status": "draft"})
    dep = client.post(f"{V1}/cases/batch", json={"case_ids": [a["id"], b["id"]], "action": "deprecated"}).json()
    assert [c["code"] for c in dep["ok"]] == ["TC-001"]
    assert dep["failed"][0]["code"] == "TC-002"  # a draft cannot be deprecated directly


def test_batch_add_to_task_and_queue_jobs(client, world):
    a = new_case(client, world, title="A")
    b = new_case(client, world, title="B")
    env = client.post(
        f"{V1}/suts/{world['sut']}/environments",
        json={"name": "test", "base_url": "http://127.0.0.1:9"},
    ).json()["id"]
    task = client.post(
        f"{V1}/versions/{world['version']}/tasks",
        json={"name": "Regression", "executor": "agent", "environment_id": env, "case_ids": [a["id"]]},
    ).json()["id"]
    out = client.post(
        f"{V1}/cases/batch",
        json={"case_ids": [a["id"], b["id"]], "action": "add_to_task", "task_id": task},
    ).json()
    assert [c["code"] for c in out["ok"]] == ["TC-002"]
    assert out["skipped"][0]["reason"] == "Already in the task"
    assert [c["code"] for c in client.get(f"{V1}/tasks/{task}").json()["cases"]] == [
        "TC-001",
        "TC-002",
    ]
    auto = client.post(f"{V1}/cases/batch", json={"case_ids": [a["id"], b["id"]], "action": "automate"}).json()
    assert auto["queued"] == 2
    progress = client.get(f"{V1}/versions/{world['version']}/automation").json()
    assert len(progress["jobs"]) == 2
    done = client.post(f"{V1}/cases/batch", json={"case_ids": [a["id"]], "action": "complete"})
    assert done.json()["queued"] == 1


# ------------------------------------------------------------------ item 3: AI completion
def proposal_body(world):
    return {
        "test_point": "Amount over 10000 needs second-level approval",
        "preconditions": "A purchase order pending approval exists",
        "steps": [
            {"action": "Sign in as approver", "expected": "Open the to-do list"},
            {
                "action": "Approve a purchase order of 20000",
                "data": "amount=20000",
                "expected": "Escalate to second level",
            },
        ],
        "test_data": {"amount": 20000},
        "expected": "The purchase order goes to second-level approval",
        "requirement_codes": ["REQ-001"],
        "node_ids": [world["nodes"]["order"]],
        "attribute_ids": [world["fields"]["amount"]],
        "rationale": "Completed the steps and amount boundary data based on REQ-001",
    }


def test_ai_complete_proposes_then_human_accepts(client, world, db):
    case = new_case(client, world, steps=[{"action": "Approve"}], node_ids=[], attribute_ids=[])
    bad = {**proposal_body(world), "node_ids": ["00000000-0000-0000-0000-000000000000"]}
    good = proposal_body(world)
    fake = use_model(client, call("submit_result", bad), call("submit_result", good))
    out = client.post(f"{V1}/cases/{case['id']}/ai-complete")
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["status"] == "succeeded" and fake.position == 2  # invalid node id fixed
    proposal = body["proposal"]
    assert proposal["fields"]["test_data"] == {"amount": 20000}
    assert proposal["labels"][world["nodes"]["order"]] == "PurchaseOrder"
    unchanged = client.get(f"{V1}/cases/{case['id']}").json()
    assert unchanged["revision"] == 1 and unchanged["ai_proposal"]["rationale"]
    # an agent can never accept its own proposal
    agent = CaseCompletionService(db, client.app.state.bus, None, actor="agent:x")
    with pytest.raises(AppError) as err:
        agent.accept(case["id"])
    assert err.value.code == "VALIDATION"
    accepted = client.post(
        f"{V1}/cases/{case['id']}/ai-complete/accept",
        json={"fields": ["steps", "test_data", "expected", "node_ids", "attribute_ids"]},
    )
    assert accepted.status_code == 200, accepted.text
    after = accepted.json()
    assert after["revision"] == 2 and after["ai_proposal"] is None
    assert after["test_data"] == {"amount": 20000} and len(after["steps"]) == 2
    assert after["test_point"] is None  # not selected
    assert [n["name"] for n in after["nodes"]] == ["PurchaseOrder"]
    assert [f["name"] for f in after["fields"]] == ["amount"]
    assert after["status"] == "draft"
    nothing = client.post(f"{V1}/cases/{case['id']}/ai-complete/accept", json={})
    assert nothing.status_code == 409


def test_ai_complete_keeps_existing_links_and_can_be_rejected(client, world):
    case = new_case(client, world)
    use_model(client, call("submit_result", {**proposal_body(world), "node_ids": []}))
    proposal = client.post(f"{V1}/cases/{case['id']}/ai-complete").json()["proposal"]
    assert proposal["fields"]["node_ids"] == [world["nodes"]["approve"]]  # human link kept
    rejected = client.post(f"{V1}/cases/{case['id']}/ai-complete/reject").json()
    assert rejected["ai_proposal"] is None and rejected["revision"] == 1


def test_ai_complete_can_propose_a_category(client, world):
    """AI completion may propose the case category; a person accepts it like any other field."""
    case = new_case(client, world)
    body = {**proposal_body(world), "category": "quality", "quality_tags": ["idempotency"]}
    use_model(client, call("submit_result", body))
    proposal = client.post(f"{V1}/cases/{case['id']}/ai-complete").json()["proposal"]
    assert proposal["fields"]["category"] == "quality"
    assert proposal["fields"]["quality_tags"] == ["idempotency"]
    accepted = client.post(
        f"{V1}/cases/{case['id']}/ai-complete/accept", json={"fields": ["category", "quality_tags"]}
    ).json()
    assert (accepted["category"], accepted["quality_tags"]) == ("quality", ["idempotency"])
    same = {**proposal_body(world), "category": "requirement"}  # unchanged → not proposed
    use_model(client, call("submit_result", same))
    other = new_case(client, world)
    again = client.post(f"{V1}/cases/{other['id']}/ai-complete").json()["proposal"]
    assert "category" not in again["fields"]
