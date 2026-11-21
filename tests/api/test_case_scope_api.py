"""Scope manifest API, prompt contents, and tools that stay inside the manifest."""

import json

from tests.api.test_cases_api import drafts, use_model

from testagent.agent.fake import call
from testagent.agent.tools import OUT_OF_SCOPE

V1 = "/api/v1"


def _world(client):
    sut = client.post(f"{V1}/suts", json={"code": "SCOPE", "name": "Scope"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1"}).json()["id"]
    order = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": "entity", "name": "PurchaseOrder"}).json()["id"]
    other = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": "action", "name": "Export purchase orders"}).json()[
        "id"
    ]
    approve = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": "action", "name": "Approve purchase order"}).json()[
        "id"
    ]
    status = client.post(
        f"{V1}/nodes/{order}/fields",
        json={"name": "status", "data_type": "enum", "enum_values": ["pending_approval", "approved"]},
    ).json()["id"]
    amount = client.post(f"{V1}/nodes/{order}/fields", json={"name": "amount", "data_type": "number"}).json()["id"]
    req = client.post(f"{V1}/versions/{version}/requirements", json={"title": "Approve"}).json()
    bare = client.post(f"{V1}/versions/{version}/requirements", json={"title": "No refs"}).json()
    linked = client.put(
        f"{V1}/requirements/{req['id']}/structure",
        json={
            "condition": [{"text": "status", "attribute_id": status}],
            "action": [{"text": "Approve", "node_id": approve}],
        },
    )
    assert linked.status_code == 200, linked.text
    return {
        "sut": sut,
        "version": version,
        "order": order,
        "other": other,
        "approve": approve,
        "status": status,
        "amount": amount,
        "req": req,
        "bare": bare,
    }


def test_scope_lists_every_registered_field_and_blocks_a_requirement_without_refs(client):
    world = _world(client)
    out = client.post(f"{V1}/versions/{world['version']}/case-gen/scope", json={})
    assert out.status_code == 200, out.text
    scopes = {s["requirement_id"]: s for s in out.json()["scopes"]}
    blocked = scopes[world["bare"]["id"]]
    assert blocked["id"] is None and "结构化引用" in blocked["message"]
    manifest = scopes[world["req"]["id"]]["manifest"]
    assert manifest["depth"] == 1
    assert {f["name"] for f in manifest["fields"]} == {"status", "amount"}
    assert {n["name"] for n in manifest["nodes"]} >= {"PurchaseOrder", "Approve purchase order"}
    assert "Export purchase orders" not in {n["name"] for n in manifest["nodes"]}
    refused = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["bare"]["id"]]},
    )
    assert refused.status_code == 422 and "结构化引用" in refused.json()["message"]


def test_preview_can_drop_a_field_and_recompute_keeps_it_dropped(client):
    world = _world(client)
    first = client.post(
        f"{V1}/versions/{world['version']}/case-gen/scope",
        json={"requirement_ids": [world["req"]["id"]]},
    ).json()["scopes"][0]
    edited = client.put(
        f"{V1}/versions/{world['version']}/case-gen/scope",
        json={
            "requirement_id": world["req"]["id"],
            "remove": [{"kind": "field", "id": world["amount"]}],
        },
    )
    assert edited.status_code == 200, edited.text
    names = {f["name"] for f in edited.json()["scopes"][0]["manifest"]["fields"]}
    assert names == {"status"}
    again = client.put(
        f"{V1}/versions/{world['version']}/case-gen/scope",
        json={"requirement_id": world["req"]["id"], "depth": 1, "recompute": True},
    ).json()["scopes"][0]
    assert {f["name"] for f in again["manifest"]["fields"]} == {"status"}
    assert first["manifest"]["depth"] == 1


def test_prompt_has_the_manifest_and_tools_reject_out_of_scope_ids(client):
    from tests.api.scope_support import ready_scope, stamp_cases

    world = _world(client)
    scopes = ready_scope(client, world["version"], [world["req"]["id"]])
    cases = stamp_cases(drafts(world, "REQ-001", 3, world["approve"]), scopes)
    fake = use_model(
        client,
        call("get_node", {"node_id": world["other"]}, "out"),
        call("get_node", {"node_id": world["approve"]}, "in"),
        call("list_nodes", {}, "list"),
        call("search_nodes", {"query": "Export"}, "search"),
        call("submit_result", {"cases": cases}, "ok"),
    )
    out = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["req"]["id"]], "automate": False},
    )
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "succeeded", out.text
    human = next(m.content for m in fake.seen[0] if m.type == "human")
    payload = json.loads(human)
    assert "actions" not in payload and "apis" not in payload and "links" not in payload
    assert payload["scopes"][0]["requirement"]["code"] == "REQ-001"
    run = client.get(f"{V1}/agent/runs/{out.json()['agent_run_id']}").json()
    tools = [s for s in run["steps"] if s["type"] == "tool"]
    assert tools[0]["status"] == "error" and OUT_OF_SCOPE in tools[0]["result"]
    assert tools[0]["lookups"] == [{"kind": "node", "id": world["other"], "hit": False}]
    assert tools[1]["status"] == "ok" and tools[1]["lookups"][0]["hit"] is True
    assert "Export purchase orders" not in tools[2]["result"]
    assert "Export purchase orders" not in tools[3]["result"]
    assert "get_requirement" in fake.bound_tools


def test_procurement_chain_is_separate_from_requirement_depth(client, db):
    from testagent.seed import seed_procurement

    sut = seed_procurement(db)["sut_id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1"}).json()["id"]
    nodes = {n["name"]: n["id"] for n in client.get(f"{V1}/suts/{sut}/nodes").json()}
    status = next(
        f["id"]
        for f in client.get(f"{V1}/suts/{sut}/fields").json()
        if f["name"] == "status" and f["node_name"] == "PurchaseOrder"
    )
    reqs = {}
    for name in ("Create purchase order", "Approve purchase order", "Record payment"):
        req = client.post(f"{V1}/versions/{version}/requirements", json={"title": name}).json()
        linked = client.put(
            f"{V1}/requirements/{req['id']}/structure",
            json={"action": [{"text": name, "node_id": nodes[name]}]},
        )
        assert linked.status_code == 200, linked.text
        reqs[name] = req
    approve = client.put(
        f"{V1}/requirements/{reqs['Approve purchase order']['id']}/structure",
        json={
            "action": [{"text": "Approve", "node_id": nodes["Approve purchase order"]}],
            "actor": [{"text": "Approver", "node_id": nodes["Approver"]}],
            "condition": [{"text": "status", "attribute_id": status}],
        },
    )
    assert approve.status_code == 200, approve.text
    scope = client.post(
        f"{V1}/versions/{version}/case-gen/scope",
        json={
            "requirement_ids": [reqs["Approve purchase order"]["id"]],
            "depths": {reqs["Approve purchase order"]["id"]: 1},
        },
    ).json()["scopes"][0]["manifest"]
    actions = {n["name"] for n in scope["nodes"] if n["kind"] == "action"}
    assert actions == {"Approve purchase order"}
    chains = client.get(f"{V1}/versions/{version}/case-gen/chains").json()["chains"]
    assert [a["name"] for a in chains[0]["actions"]] == [
        "Create purchase order",
        "Approve purchase order",
        "Record payment",
    ]
    assert {r["code"] for r in chains[0]["requirements"]} == {"REQ-001", "REQ-002", "REQ-003"}
    chain = chains[0]
    case = {
        "title": "Create, approve, then record payment",
        "test_point": "采购单从创建到付款",
        "scenario": "normal",
        "steps": [{"action": "创建采购单，审批通过，再登记付款"}],
        "expected": "订单变为 paid",
        "requirement_codes": [r["code"] for r in chain["requirements"]],
        "node_ids": [a["id"] for a in chain["actions"]],
        "covers": [t["id"] for t in chain["targets"]],
    }
    use_model(client, call("submit_result", {"cases": [case, case, case]}))
    out = client.post(f"{V1}/versions/{version}/cases/generate-e2e")
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["status"] == "succeeded", body
    saved = client.get(f"{V1}/cases/{body['cases'][0]['id']}").json()
    assert [r["code"] for r in saved["requirements"]] == ["REQ-001", "REQ-002", "REQ-003"]
    assert saved["chain_id"] == chain["id"]
    assert body["coverage"]["chains"]["covered"] == 1
    assert body["coverage"]["state_transitions"]["covered"] == body["coverage"]["state_transitions"]["total"]


def test_generate_requires_a_confirmed_scope(client):
    world = _world(client)
    client.post(f"{V1}/versions/{world['version']}/case-gen/scope", json={"requirement_ids": [world["req"]["id"]]})
    resp = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["req"]["id"]], "automate": False},
    )
    assert resp.status_code == 409 and "确认" in resp.json()["message"]


def test_uncovered_target_fails_until_a_person_confirms_the_waiver(client):
    from tests.api.scope_support import ready_scope

    world = _world(client)
    ready_scope(client, world["version"], [world["req"]["id"]])
    amount = f"field:{world['amount']}"
    cases = drafts(world, "REQ-001", 3, world["approve"])
    for case in cases:
        case["attribute_ids"] = [world["status"]]
    waived = {
        "cases": cases,
        "waivers": [{"target_id": amount, "reason": "金额与审批无关", "requirement_code": "REQ-001"}],
    }
    use_model(
        client,
        call("submit_result", waived, "w"),
        call("submit_result", waived, "w2"),
        call("submit_result", waived, "w3"),
    )
    failed = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["req"]["id"]], "automate": False},
    ).json()
    assert failed["status"] == "failed" and failed["error_code"] == "VALIDATION"
    run = client.get(f"{V1}/agent/runs/{failed['agent_run_id']}").json()
    text = " ".join(e["msg"] for s in run["steps"] if s["type"] == "submit_invalid" for e in s["errors"])
    assert "does not count until a person confirms" in text
    saved = client.put(
        f"{V1}/versions/{world['version']}/case-gen/scope",
        json={
            "requirement_id": world["req"]["id"],
            "waivers": [{"target_id": amount, "reason": "金额与这条审批需求无关"}],
        },
    )
    assert saved.status_code == 200, saved.text
    client.post(
        f"{V1}/versions/{world['version']}/case-gen/scope/confirm",
        json={"requirement_ids": [world["req"]["id"]]},
    )
    use_model(client, call("submit_result", waived, "pass"))
    ok = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["req"]["id"]], "automate": False},
    ).json()
    assert ok["status"] == "succeeded", ok
    report = ok["coverage"]["targets"]["requirements"]
    row = next(t for block in report for t in block["targets"] if t["id"] == amount)
    assert row["covered"] is True and row["waiver"]["confirmed"] is True and row["cases"] == []
