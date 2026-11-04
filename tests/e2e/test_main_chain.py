"""T-12.5 end-to-end main chain over the bundled procurement demo SUT (fake model, real browser).

modelling (seed) → AI model completion → requirement + people → AI structuring → confirm →
freeze → AI strategy → AI cases → AI automation (pytest code committed to the local test repo) →
task run: agent browser execution against the demo app with an injected bug + the automated case
→ defect (requirement ownership, attributed to the developer) → report + people ranking →
correction → digest into memory → regenerated cases get the memory injected.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
from tests.fixtures.mini_shop import browser_available

from testagent.agent.fake import FakeChatModel, call
from testagent.seed import seed_procurement

pytestmark = pytest.mark.skipif(not browser_available(), reason="playwright chromium not installed")

V1 = "/api/v1"
NOTE = {"note": "Confirmed with the product owner"}  # accepting an AI inference (#6)


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


def ok(resp, code=200):
    assert resp.status_code == code, resp.text
    return resp.json()


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    """examples/procurement with an injected bug: the approval threshold is off by one cent,
    so exactly CNY 50,000.00 no longer requires approval."""
    import uvicorn

    import examples.procurement.api as demo

    class Buggy(demo.ProcurementService):
        def __init__(self, database, threshold_minor=5_000_001, **kwargs):
            super().__init__(database, threshold_minor, **kwargs)

    monkeypatch.setattr(demo, "ProcurementService", Buggy)
    app = demo.create_app(tmp_path / "sample.db")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


def case_drafts(nodes):
    base = {
        "priority": "P0",
        "steps": [
            {"action": "Open the procurement approval lab"},
            {
                "action": "Enter purchase amount 50000.00, currency CNY, click “Create order”",
                "expected": "The order is pending approval",
            },
        ],
        "expected": "Orders of 50,000.00 or more go to pending approval",
        "requirement_codes": ["REQ-001"],
        "node_ids": [nodes["Create purchase order"], nodes["PurchaseOrder"]],
    }
    return [
        {
            **base,
            "title": "Exactly 50,000.00 needs approval",
            "test_point": "Approval threshold (inclusive)",
            "scenario": "boundary",
            "test_data": {"amount": "50000.00", "currency": "CNY"},
        },
        {
            **base,
            "title": "Amount 49,999.99 needs no approval",
            "test_point": "Just below the threshold",
            "scenario": "boundary",
            "test_data": {"amount": "49999.99", "amount_minor": 4999999, "currency": "CNY"},
        },
        {
            **base,
            "title": "Rule unconfirmed for an empty amount",
            "test_point": "Amount missing",
            "scenario": "exception",
            "test_data": {"amount": None, "currency": "CNY"},
        },
    ]


AUTOMATED = """import json
import urllib.request


def test_below_threshold_needs_no_approval(base_url, test_data):
    body = json.dumps({"amount_minor": test_data["amount_minor"], "currency": "CNY"}).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + "/sample/spaces/auto/orders",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        order = json.load(response)
    assert order["approval_required"] is False
"""

BADGE = {"selector": "#orders .badge"}
BROWSER_SCRIPT = [
    call("browser_goto", {"url": "/"}, "b1"),
    call("browser_fill", {"target": {"label": "Amount (CNY)"}, "value": "50000.00"}, "b2"),
    call("browser_click", {"target": {"role": "button", "name": "Create order"}}, "b3"),
    call("browser_assert", {"kind": "text", "target": BADGE, "expected": "Pending approval"}, "b4"),
    call("submit_result", {"claimed_status": "failed", "summary": "The order did not go to pending approval"}, "b5"),
]


def test_main_chain(client, db, demo_app):
    # ---------------------------------------------------------------- modelling (AC-01..03)
    sut = seed_procurement(db)["sut_id"]
    nodes = {n["name"]: n["id"] for n in ok(client.get(f"{V1}/suts/{sut}/nodes"))}
    people = {p["name"]: p["id"] for p in ok(client.get(f"{V1}/persons"))}
    env = ok(
        client.post(f"{V1}/suts/{sut}/environments", json={"name": "e2e", "base_url": demo_app}),
        201,
    )["id"]
    version = ok(client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1.0"}), 201)["id"]

    # ---------------------------------------------------------------- AI model completion (AC-06)
    use_model(
        client,
        call(
            "submit_result",
            {
                "suggestions": [
                    {
                        "kind": "attribute",
                        "node_id": nodes["PurchaseOrder"],
                        "attr": "constraints",
                        "text": "An amount of 50,000.00 or more needs approval",
                    }
                ]
            },
        ),
    )
    completion = ok(client.post(f"{V1}/suts/{sut}/model/complete", json={}))
    (sugg,) = completion["suggestions"]
    ok(client.post(f"{V1}/suggestions/{sugg['id']}/accept", json=NOTE))
    order = ok(client.get(f"{V1}/nodes/{nodes['PurchaseOrder']}"))
    assert {"text": "An amount of 50,000.00 or more needs approval"} in order["attributes"]["constraints"]

    # ---------------------------------------------------------------- requirement + people (AC-04)
    req = ok(
        client.post(
            f"{V1}/versions/{version}/requirements",
            json={
                "title": "Create purchase order decides approval by amount",
                "raw_text": (
                    "The buyer creates a purchase order; at 50,000 or more (inclusive) it goes to pending approval"
                ),
            },
        ),
        201,
    )
    ok(
        client.put(
            f"{V1}/requirements/{req['id']}/people",
            json=[
                {"person_id": people["Pat Product"], "role": "owner"},
                {"person_id": people["Devin Dev"], "role": "developer"},
                {"person_id": people["Tess Tester"], "role": "tester"},
            ],
        )
    )
    # ---------------------------------------------------------------- AI structuring (AC-05)
    use_model(
        client,
        call("search_nodes", {"sut_id": sut, "query": "PurchaseOrder"}),
        call(
            "submit_result",
            {
                "items": [
                    {"part": "actor", "text": "Buyer", "missing": True},
                    {"part": "action", "text": "Create purchase order", "node_id": nodes["Create purchase order"]},
                    {
                        "part": "result",
                        "text": "The purchase order goes to pending approval",
                        "node_id": nodes["PurchaseOrder"],
                    },
                    {
                        "part": "constraint",
                        "text": "Amount ≥ 50,000.00 needs approval",
                        "node_id": nodes["PurchaseOrder"],
                    },
                ]
            },
        ),
    )
    structured = ok(client.post(f"{V1}/requirements/{req['id']}/structure"))
    assert structured["status"] == "succeeded"
    ok(client.post(f"{V1}/requirements/{req['id']}/confirm"))
    frozen = ok(client.post(f"{V1}/versions/{version}/freeze"))  # AC-07
    assert frozen["model_snapshot_id"]

    # ---------------------------------------------------------------- AI strategy (AC-08)
    use_model(
        client,
        call(
            "submit_result",
            {
                "scope": "Purchase order creation and approval threshold",
                "test_types": ["functional"],
                "intensity": "standard",
                "tasks": [{"name": "Approval threshold", "requirement_codes": ["REQ-001"]}],
            },
        ),
    )
    strategy = ok(client.post(f"{V1}/versions/{version}/strategy/generate"))["strategy"]
    ok(client.post(f"{V1}/strategy/{strategy['id']}/confirm"))
    # one requirement task per requirement + quality + regression/smoke, all rule tasks
    assert sorted(t["kind"] for t in strategy["tasks"]) == ["quality", "regression", "requirement"]
    (task,) = [t for t in strategy["tasks"] if t["kind"] == "requirement"]
    assert task["case_count"] == 0  # no executable cases yet

    # ---------------------------------------------------------------- AI cases (AC-09)
    use_model(client, call("submit_result", {"cases": case_drafts(nodes)}))
    generated = ok(client.post(f"{V1}/versions/{version}/cases/generate", json={"automate": False}))
    assert generated["status"] == "succeeded" and len(generated["cases"]) == 3
    assert generated["coverage"]["requirements"]["uncovered"] == []
    by_title = {c["title"]: c["id"] for c in generated["cases"]}
    first, second = by_title["Exactly 50,000.00 needs approval"], by_title["Amount 49,999.99 needs no approval"]

    # ---------------------------------------------------------------- AI automation (AC-12)
    use_model(
        client,
        call("write_test_file", {"content": AUTOMATED}, "w1"),
        call("run_pytest", {}, "p1"),  # only a passing final self-check is bound (BR-13)
        call("submit_result", {"summary": "Generate pytest cases"}, "s1"),
    )
    automated = ok(client.post(f"{V1}/cases/{second}/automate", json={"environment_id": env}))
    assert automated["status"] == "succeeded", automated
    assert automated["code_path"].startswith("tests/REQ-001/") and automated["code_commit"]
    for case_id in (first, second):  # human-only (C01)
        ok(client.post(f"{V1}/cases/{case_id}/status", json={"status": "ready"}))

    # ---------------------------------------------------------------- agent execution (AC-10/13)
    ok(client.patch(f"{V1}/tasks/{task['id']}", json={"environment_id": env, "executor": "agent"}))
    joined = ok(client.get(f"{V1}/tasks/{task['id']}"))["cases"]  # ready cases joined the rule
    assert {c["id"] for c in joined} == {first, second}
    assert {c["source"] for c in joined} == {"rule"}
    ok(client.put(f"{V1}/tasks/{task['id']}/cases", json={"case_ids": [first, second]}))
    ok(client.post(f"{V1}/tasks/{task['id']}/status", json={"status": "ready"}))
    use_model(
        client,
        *BROWSER_SCRIPT,
        call("submit_result", {"summary": "2 cases, 1 failed: the 50,000.00 order did not go to pending approval."}),
    )
    run = ok(client.post(f"{V1}/tasks/{task['id']}/run"), 201)
    assert client.app.state.worker.run_once() is True
    run = ok(client.get(f"{V1}/runs/{run['id']}"))
    assert run["status"] == "failed", run
    execution, auto_run = run["executions"]
    auto_detail = ok(client.get(f"{V1}/executions/{auto_run['id']}"))
    assert (auto_detail["executor"], auto_detail["status"]) == ("pytest", "passed"), (
        auto_detail["failed_assertion"],
        auto_detail["error"],
        auto_detail.get("result"),
    )
    assert auto_detail["code_commit"] == automated["code_commit"]
    detail = ok(client.get(f"{V1}/executions/{execution['id']}"))
    assert detail["status"] == "failed" and detail["executor"] == "agent_browser"
    assert "Pending approval" in detail["failed_assertion"] and "Approved" in detail["failed_assertion"]
    assert run["report_id"]  # task report generated on finish (AC-16)

    # ---------------------------------------------------------------- defect (AC-14/15)
    defect = ok(
        client.post(
            f"{V1}/executions/{execution['id']}/defect",
            json={
                "title": "Exactly 50,000.00 did not go to approval",
                "severity": "major",
                "cause_category": "development",
            },
        ),
        201,
    )
    assert [r["code"] for r in defect["requirements"]] == ["REQ-001"]
    assert [(p["person_name"], p["role"]) for p in defect["responsible"]] == [("Devin Dev", "developer")]

    # ---------------------------------------------------------------- report + ranking (AC-16/17)
    use_model(client, call("submit_result", {"summary": "Failures concentrate on the REQ-001 approval threshold."}))
    report = ok(client.post(f"{V1}/runs/{run['id']}/report"), 201)
    content = report["content"]
    assert content["summary"]["failed"] == 1 and content["summary"]["passed"] == 1
    assert content["summary"]["pass_rate"] == 0.5
    (req_row,) = content["by_requirement"]
    assert (req_row["code"], req_row["defect_count"], req_row["weighted_score"]) == (
        "REQ-001",
        1,
        3.0,
    )
    assert req_row["density"] == 0.5  # 1 defect / 2 executed cases
    top = content["by_person"][0]
    assert (top["name"], top["attributed_count"], top["attributed_score"]) == ("Devin Dev", 1, 3.0)
    assert any(a["path"] == "/sample/orders" for a in content["code_links"][0]["apis"])
    assert report["ai_summary"] == "Failures concentrate on the REQ-001 approval threshold."
    ranking = ok(client.get(f"{V1}/stats/people", params={"version_id": version}))
    assert ranking[0]["name"] == "Devin Dev"
    version_report = ok(client.post(f"{V1}/versions/{version}/report"), 201)
    assert version_report["content"]["summary"]["total"] == 3

    # ---------------------------------------------------------------- correction loop (AC-18)
    lesson = "Threshold boundaries must cover 49,999.99 / 50,000.00 / 50,000.01, and 50,000.00 needs approval"
    use_model(
        client,
        call(
            "submit_result",
            {
                "memories": [{"scope": "sut", "content": lesson, "tags": ["generate_cases"]}],
                "prompt_patches": [],
            },
        ),
    )
    raw = "The cases missed 50,000.01; all three boundary points must be tested.\n"
    corr = ok(
        client.post(f"{V1}/corrections", json={"target_type": "case", "target_id": first, "content": raw}),
        201,
    )
    while client.app.state.worker.run_once():
        pass
    corr = ok(client.get(f"{V1}/corrections/{corr['id']}"))
    assert corr["status"] == "processed" and corr["content"] == raw
    (memory,) = ok(client.get(f"{V1}/agent/memories", params={"sut_id": sut}))
    assert memory["source_correction_ids"] == [corr["id"]]

    fake = use_model(client, call("submit_result", {"cases": case_drafts(nodes)}))
    again = ok(client.post(f"{V1}/versions/{version}/cases/generate", json={}))
    trace = ok(client.get(f"{V1}/agent/runs/{again['agent_run_id']}"))
    assert trace["injected"]["memory_ids"] == [memory["id"]]
    assert lesson in fake.seen[0][0].content
