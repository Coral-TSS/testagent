"""Batch 2 #6 (where a suggestion comes from, batch accept) and #4 (completion de-duplication)."""

import pytest
from tests.api.test_requirements_api import V1, new_req, use_model

from testagent.agent.fake import call


@pytest.fixture
def world(client):
    sut = client.post(f"{V1}/suts", json={"code": "SHOP", "name": "Shop"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1.0"}).json()["id"]
    order = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": "entity", "name": "PurchaseOrder"}).json()["id"]
    create = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": "action", "name": "Create purchase order"}).json()
    return {"sut": sut, "version": version, "order": order, "create": create["id"]}


def _complete(client, world, *suggestions):
    use_model(client, call("submit_result", {"suggestions": list(suggestions)}))
    resp = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _api(client, world, method, path, bind_to=None):
    api = client.post(f"{V1}/suts/{world['sut']}/apis", json={"method": method, "path": path}).json()
    if bind_to:
        assert client.put(f"{V1}/nodes/{bind_to}/apis", json={"api_ids": [api["id"]]}).status_code == 200
    return api


# ---------------------------------------------------------------- #6 sources
def test_completion_source_needs_a_real_quote(client, world):
    req = new_req(client, world, "Approve orders", raw_text="Orders of 50,000 or more need a manager approval.")
    out = _complete(
        client,
        world,
        {
            "kind": "attribute",
            "node_id": world["order"],
            "attr": "constraints",
            "text": "50,000 or more needs approval",
            "requirement_id": req["id"],
            "evidence": "Orders of 50,000 or more need a manager approval",
        },
        {
            "kind": "attribute",
            "node_id": world["order"],
            "attr": "states",
            "text": "archived",
            "requirement_id": req["id"],
            "evidence": "Orders are archived after a year",  # not in the requirement
        },
        {"kind": "attribute", "node_id": world["order"], "attr": "states", "text": "paid"},
    )
    got = {s["payload"]["text"]: (s["source"], s["evidence"]) for s in out["suggestions"]}
    assert got["50,000 or more needs approval"] == ("requirement", "Orders of 50,000 or more need a manager approval")
    assert got["archived"][0] == "ai_inferred"
    assert got["paid"] == ("ai_inferred", None)
    review = client.get(f"{V1}/suts/{world['sut']}/model-review").json()
    assert review["pending_by_source"] == {"requirement": 1, "ai_inferred": 2}


def test_structure_alignment_and_link_sources(client, world):
    req = new_req(client, world)
    use_model(client, call("submit_result", {"items": [{"part": "actor", "text": "Buyer", "missing": True}]}))
    out = client.post(f"{V1}/requirements/{req['id']}/structure").json()
    assert [(s["source"], s["evidence"]) for s in out["suggestions"]] == [("requirement", "Buyer")]
    # a requirement suggestion is accepted without a note
    assert client.post(f"{V1}/suggestions/{out['suggestions'][0]['id']}/accept", json={}).status_code == 200


def test_accept_batch_skips_ai_inferences_by_default(client, world):
    req = new_req(client, world, "Approve orders", raw_text="Orders of 50,000 or more need approval.")
    out = _complete(
        client,
        world,
        {
            "kind": "attribute",
            "node_id": world["order"],
            "attr": "constraints",
            "text": "50,000 or more needs approval",
            "requirement_id": req["id"],
            "evidence": "50,000 or more need approval",
        },
        {"kind": "attribute", "node_id": world["order"], "attr": "states", "text": "paid"},
    )
    by_text = {s["payload"]["text"]: s["id"] for s in out["suggestions"]}
    ids = list(by_text.values())
    url = f"{V1}/suts/{world['sut']}/suggestions/accept-batch"
    first = client.post(url, json={"ids": ids}).json()
    assert first["accepted"] == [by_text["50,000 or more needs approval"]]
    assert [(s["id"], s["reason"]) for s in first["skipped"]] == [(by_text["paid"], "ai_inferred")]
    # including AI inferences needs a note
    assert client.post(url, json={"ids": ids, "include_ai_inferred": True}).status_code == 422
    second = client.post(url, json={"ids": ids, "include_ai_inferred": True, "note": "Seen in the demo"}).json()
    assert second["accepted"] == [by_text["paid"]]
    assert second["skipped"][0]["reason"] == "handled"
    order = client.get(f"{V1}/nodes/{world['order']}").json()
    assert {"text": "paid"} in order["attributes"]["states"]
    # another system's suggestions are not touched
    other = client.post(f"{V1}/suts", json={"code": "OTHER", "name": "Other"}).json()["id"]
    assert (
        client.post(f"{V1}/suts/{other}/suggestions/accept-batch", json={"ids": ids}).json()["skipped"][0]["reason"]
        == "not_found"
    )


def test_accept_batch_leaves_links_for_review(client, world):
    supplier = client.post(f"{V1}/suts/{world['sut']}/nodes", json={"kind": "entity", "name": "Supplier"}).json()
    out = _complete(
        client,
        world,
        {
            "kind": "link",
            "from_node_id": world["order"],
            "to_node_id": supplier["id"],
            "forward_name": "belongs to",
            "reverse_name": "supplies",
        },
    )
    sugg = out["suggestions"][0]
    res = client.post(
        f"{V1}/suts/{world['sut']}/suggestions/accept-batch",
        json={"ids": [sugg["id"]], "include_ai_inferred": True, "note": "From the data model"},
    ).json()
    assert res["accepted"] == [] and res["skipped"][0]["reason"] == "needs_review"


# ---------------------------------------------------------------- #4 de-duplication
def test_completion_drops_duplicates_and_empty_actions(client, world):
    _api(client, world, "POST", "/orders", bind_to=world["create"])
    _api(client, world, "POST", "/orders/{id}/approve")
    out = _complete(
        client,
        world,
        # same API as the existing "Create purchase order"
        {
            "kind": "node",
            "node_kind": "action",
            "name": "Submit order",
            "description": "Submit a new order",
            "api": "post /orders",
        },
        # new and valid, twice in the batch (same API under another name)
        {
            "kind": "node",
            "node_kind": "action",
            "name": "Approve order",
            "description": "Approve a pending order",
            "api": "POST /orders/{id}/approve",
        },
        {
            "kind": "node",
            "node_kind": "action",
            "name": "Sign off order",
            "description": "Sign off a pending order",
            "api": "POST /orders/{id}/approve",
        },
        {"kind": "node", "node_kind": "action", "name": "approve  order", "description": "Approve a pending order"},
        # empty shell / too short
        {"kind": "node", "node_kind": "action", "name": "Cancel order"},
        {"kind": "node", "node_kind": "entity", "name": "X"},
        # equivalent to an existing node
        {"kind": "node", "node_kind": "entity", "name": "Purchase order"},
    )
    assert [s["payload"]["name"] for s in out["suggestions"]] == ["Approve order"]
    assert out["dropped"] == {
        "duplicate_node": 1,
        "duplicate_api": 1,
        "duplicate_in_batch": 2,
        "previously_rejected": 0,
        "invalid": 2,
    }
    assert out["skipped"] == 6
    assert any("Create purchase order" in n and "POST /orders" in n for n in out["dropped_notes"])
    # accepting binds the API the action named
    sugg = out["suggestions"][0]
    accepted = client.post(f"{V1}/suggestions/{sugg['id']}/accept", json={"note": "Approval is in the spec"}).json()
    node = client.get(f"{V1}/nodes/{accepted['resolved_node_id']}").json()
    assert [f"{a['method']} {a['path']}" for a in node.get("apis", [])] == ["POST /orders/{id}/approve"]


def test_rejected_suggestion_is_not_proposed_again(client, world):
    first = _complete(client, world, {"kind": "node", "node_kind": "entity", "name": "Warehouse"})
    sugg = first["suggestions"][0]
    assert client.post(f"{V1}/suggestions/{sugg['id']}/reject", json={"reason": "Out of scope"}).status_code == 200
    again = _complete(
        client,
        world,
        {"kind": "node", "node_kind": "entity", "name": "Warehouse"},
        {"kind": "node", "node_kind": "entity", "name": "Warehouse (storage)"},
    )
    assert again["suggestions"] == []
    assert again["dropped"]["previously_rejected"] == 2
    # a pending similar one is not repeated either
    _complete(client, world, {"kind": "node", "node_kind": "entity", "name": "Supplier"})
    third = _complete(client, world, {"kind": "node", "node_kind": "entity", "name": "Supplier company"})
    assert third["suggestions"] == [] and third["dropped"]["duplicate_node"] == 1


def test_possible_duplicate_hint(client, world):
    out = _complete(
        client,
        world,
        {"kind": "node", "node_kind": "action", "name": "Create order draft", "description": "Save an order as draft"},
    )
    assert out["suggestions"][0]["payload"]["similar_to"] == "Create purchase order"
