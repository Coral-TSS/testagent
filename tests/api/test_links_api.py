"""relations are first-class link types (two named sides, cardinality, foreign key or
junction entity); actions carry structured preconditions and effects; requirements can
reference links; links are suggested from reference / <resource>_id fields."""

from __future__ import annotations

import json

import pytest

from testagent.agent.fake import FakeChatModel, call
from testagent.agent.tools import action_summaries, link_summaries, model_catalog
from testagent.services.links import link_suggestions, link_text, migrate_relation_nodes
from testagent.services.model import ModelService

V1 = "/api/v1"
NOTE = {"note": "Confirmed with the product owner"}  # accepting an AI inference (#6)


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

    def field(node_id, name, data_type="string", **extra):
        resp = client.post(f"{V1}/nodes/{node_id}/fields", json={"name": name, "data_type": data_type, **extra})
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    ids = {n: node("entity", n) for n in ("PurchaseOrder", "Supplier", "Payment")}
    ids["Approve purchase order"] = node("action", "Approve purchase order")
    fields = {
        "state": field(ids["PurchaseOrder"], "state", "enum", enum_values=["pending", "approved", "rejected", "paid"]),
        "supplier_id": field(ids["PurchaseOrder"], "supplier_id", "reference", ref_node_id=ids["Supplier"]),
    }
    return {
        "sut": sut,
        "version": version,
        "ids": ids,
        "fields": fields,
        "node": node,
        "field": field,
    }


def test_relation_nodes_are_no_longer_created(client, world):
    ids = world["ids"]
    resp = client.post(
        f"{V1}/suts/{world['sut']}/nodes",
        json={
            "kind": "relation",
            "name": "PurchaseOrder-Supplier",
            "source_node_id": ids["PurchaseOrder"],
            "target_node_id": ids["Supplier"],
        },
    )
    assert resp.status_code == 422 and "Links are no longer nodes" in resp.json()["message"]
    edge = {"source_node_id": ids["PurchaseOrder"], "target_node_id": ids["Supplier"], "role": "source"}
    assert client.post(f"{V1}/suts/{world['sut']}/edges", json=edge).status_code == 422


def test_link_both_sides_cardinality_and_foreign_key(client, world):
    ids, sut = world["ids"], world["sut"]
    body = {
        "from_node_id": ids["PurchaseOrder"],
        "to_node_id": ids["Supplier"],
        "forward_name": "belongs to",
        "reverse_name": "supplies",
        "forward_api_name": "supplier",
        "reverse_api_name": "purchaseOrders",
        "cardinality": "many_to_one",
        "required": True,
    }
    resp = client.post(f"{V1}/suts/{sut}/links", json=body)
    assert resp.status_code == 201, resp.text
    link = resp.json()
    # the single reference field PurchaseOrder.supplier_id → Supplier becomes the foreign key
    assert link["fk_attribute_id"] == world["fields"]["supplier_id"]
    assert link["fk_field"] == "PurchaseOrder.supplier_id"
    assert link_text(link) == "PurchaseOrder belongs to Supplier (N:1, foreign key PurchaseOrder.supplier_id)"
    assert link_text(link, reverse=True).startswith("Supplier supplies PurchaseOrder")
    # same reading twice, or the same API name on one entity, is refused
    assert client.post(f"{V1}/suts/{sut}/links", json=body).status_code == 409
    clash = {**body, "forward_name": "is supplied by", "reverse_api_name": "other"}
    assert client.post(f"{V1}/suts/{sut}/links", json=clash).status_code == 409
    # the foreign key must sit on the "many" side
    wrong = {
        **body,
        "forward_name": "supplies to",
        "forward_api_name": None,
        "reverse_api_name": None,
        "cardinality": "one_to_many",
        "fk_attribute_id": world["fields"]["supplier_id"],
    }
    assert client.post(f"{V1}/suts/{sut}/links", json=wrong).status_code == 422
    bad_api = {**body, "forward_name": "x", "forward_api_name": "Bad Name"}
    assert client.post(f"{V1}/suts/{sut}/links", json=bad_api).status_code == 422
    # graph, entity detail and snapshot carry the link
    graph = client.get(f"{V1}/suts/{sut}/graph").json()
    assert [(lk["forward_name"], lk["reverse_name"]) for lk in graph["links"]] == [("belongs to", "supplies")]
    detail = client.get(f"{V1}/nodes/{ids['Supplier']}").json()
    assert [lk["id"] for lk in detail["links"]] == [link["id"]]
    content = ModelService(client.app.state.db, client.app.state.bus).snapshot_content(sut)
    assert content["links"][0]["cardinality"] == "many_to_one"
    # rename the sides
    patched = client.patch(f"{V1}/links/{link['id']}", json={"reverse_name": "supply"}).json()
    assert patched["reverse_name"] == "supply"
    assert patched["fk_attribute_id"] == link["fk_attribute_id"]
    # deleting the entity archives its links too
    refs = client.get(f"{V1}/nodes/{ids['Supplier']}/references").json()
    assert any(r["type"] == "link" for r in refs)
    client.delete(f"{V1}/nodes/{ids['Supplier']}", params={"confirm": "true"})
    assert client.get(f"{V1}/suts/{sut}/links").json() == []


def test_many_to_many_through_a_junction_entity(client, world):
    sut, node, field = world["sut"], world["node"], world["field"]
    order, product, line = node("entity", "Order"), node("entity", "Product"), node("entity", "OrderLine")
    field(line, "order_id", "reference", ref_node_id=order)
    product_fk = field(line, "product_id", "reference", ref_node_id=product)
    body = {
        "from_node_id": order,
        "to_node_id": product,
        "forward_name": "contains",
        "reverse_name": "appears in",
        "cardinality": "many_to_many",
        "via_node_id": line,
    }
    resp = client.post(f"{V1}/suts/{sut}/links", json=body)
    assert resp.status_code == 201, resp.text
    link = resp.json()
    assert link["via_name"] == "OrderLine" and link["via_to_attribute_id"] == product_fk
    assert link["via_from_field"] == "order_id" and link["via_to_field"] == "product_id"
    assert "junction entity OrderLine" in link_text(link)
    with_fk = {**body, "forward_name": "x", "fk_attribute_id": product_fk}
    assert client.post(f"{V1}/suts/{sut}/links", json=with_fk).status_code == 422
    no_fk = {**body, "forward_name": "y", "via_node_id": world["ids"]["Supplier"]}
    assert client.post(f"{V1}/suts/{sut}/links", json=no_fk).status_code == 422
    # junction fields are references: deleting one empties the link's field (confirm needed)
    refs = client.delete(f"{V1}/fields/{product_fk}")
    assert refs.status_code == 409
    client.delete(f"{V1}/fields/{product_fk}", params={"confirm": "true"})
    assert client.get(f"{V1}/links/{link['id']}").json()["via_to_attribute_id"] is None


def test_relation_nodes_are_migrated_to_links(client, db, world):
    ids, sut = world["ids"], world["sut"]
    fk = world["field"](ids["Payment"], "order_id", "reference", ref_node_id=ids["PurchaseOrder"])
    with db.tx() as cur:
        cur.execute(
            "INSERT INTO model_node(sut_id, kind, name) VALUES (%s,'relation','Payment-PurchaseOrder') RETURNING id",
            (sut,),
        )
        rel = str(cur.fetchone()["id"])
        for end, role in ((ids["Payment"], "source"), (ids["PurchaseOrder"], "target")):
            cur.execute(
                "INSERT INTO model_edge(sut_id, source_node_id, target_node_id, role) VALUES (%s,%s,%s,%s)",
                (sut, rel, end, role),
            )
    req = client.post(
        f"{V1}/versions/{world['version']}/requirements",
        json={"title": "Payment matches purchase order", "raw_text": "Each payment matches one purchase order"},
    ).json()
    client.put(
        f"{V1}/requirements/{req['id']}/structure",
        json={"constraint": [{"text": "Payment matches purchase order", "node_id": rel}]},
    )
    with db.tx() as cur:
        done = migrate_relation_nodes(cur, actor="test")
        assert migrate_relation_nodes(cur, actor="test") == []  # idempotent
    link = {k: (str(v) if k.endswith("id") and v else v) for k, v in done[0]["link"].items()}
    assert (link["from_name"], link["to_name"], link["fk_attribute_id"]) == (
        "Payment",
        "PurchaseOrder",
        fk,
    )
    assert link["legacy_node_id"] is not None
    assert client.get(f"{V1}/nodes/{rel}").status_code == 404  # archived (soft delete)
    graph = client.get(f"{V1}/suts/{sut}/graph").json()
    assert all(n["kind"] != "relation" for n in graph["nodes"])
    assert all(e["role"] not in ("source", "target") for e in graph["edges"])
    detail = client.get(f"{V1}/requirements/{req['id']}").json()
    assert [x["link_id"] for x in detail["links"]] == [link["id"]]
    item = detail["structured"]["constraint"][0]
    assert item["link_id"] == link["id"] and item["node_id"] == ids["Payment"]


def test_requirement_items_reference_links(client, world):
    ids, sut = world["ids"], world["sut"]
    link = client.post(
        f"{V1}/suts/{sut}/links",
        json={
            "from_node_id": ids["PurchaseOrder"],
            "to_node_id": ids["Supplier"],
            "forward_name": "belongs to",
            "reverse_name": "supplies",
        },
    ).json()
    req = client.post(
        f"{V1}/versions/{world['version']}/requirements",
        json={
            "title": "Purchase order must have a supplier",
            "raw_text": "Each purchase order belongs to one supplier",
        },
    ).json()
    bad = client.put(
        f"{V1}/requirements/{req['id']}/structure",
        json={"constraint": [{"text": "x", "link_id": ids["PurchaseOrder"]}]},
    )
    assert bad.status_code == 422
    ok = client.put(
        f"{V1}/requirements/{req['id']}/structure",
        json={"constraint": [{"text": "A purchase order belongs to one supplier", "link_id": link["id"]}]},
    )
    assert ok.status_code == 200, ok.text
    detail = ok.json()
    assert detail["links"][0]["forward_name"] == "belongs to"
    assert detail["structured"]["constraint"][0]["node_id"] == ids["PurchaseOrder"]
    refs = client.get(f"{V1}/links/{link['id']}").json()["references"]
    assert [r["type"] for r in refs] == ["requirement"]
    assert client.delete(f"{V1}/links/{link['id']}").status_code == 409


def test_links_are_suggested_from_reference_and_resource_fields(client, db, world):
    ids, sut, field = world["ids"], world["sut"], world["field"]
    # Create purchase order POST /orders acts on PurchaseOrder → "order" is PurchaseOrder's API resource
    create = world["node"]("action", "Create purchase order")
    client.post(
        f"{V1}/suts/{sut}/edges",
        json={"source_node_id": create, "target_node_id": ids["PurchaseOrder"], "role": "object"},
    )
    api = client.post(f"{V1}/suts/{sut}/apis", json={"method": "POST", "path": "/sample/orders"}).json()
    client.put(f"{V1}/nodes/{create}/apis", json={"api_ids": [api["id"]]})
    # the reference field PurchaseOrder.supplier_id was created in the fixture → already suggested
    pending = client.get(f"{V1}/suts/{sut}/suggestions", params={"status": "pending"}).json()
    by_fk = {s["payload"].get("fk_field"): s for s in pending if s["kind"] == "link"}
    assert set(by_fk) == {"PurchaseOrder.supplier_id"}
    # a plain order_id string field matches the PurchaseOrder resource
    field(ids["Payment"], "order_id")
    with db.tx() as cur:
        items = link_suggestions(cur, sut)
    pay = next(i for i in items if i["fk_field"] == "Payment.order_id")
    assert (pay["from_name"], pay["to_name"]) == ("Payment", "PurchaseOrder")
    assert pay["cardinality"] == "many_to_one"
    assert pay["forward_api_name"] == "order"
    out = client.post(f"{V1}/suts/{sut}/links/suggest").json()
    assert out["created"] == 0  # already pending from the field creation
    pending = client.get(f"{V1}/suts/{sut}/suggestions", params={"status": "pending"}).json()
    sugg = next(s for s in pending if s["payload"].get("fk_field") == "Payment.order_id")
    assert (sugg["source"], sugg["evidence"]) == ("model_rule", "foreign-key field Payment.order_id")  # #6
    accepted = client.post(
        f"{V1}/suggestions/{sugg['id']}/accept",
        json={"forward_name": "pays", "reverse_name": "receives"},
    )
    assert accepted.status_code == 200, accepted.text
    links = client.get(f"{V1}/suts/{sut}/links").json()
    paid = next(lk for lk in links if lk["from_name"] == "Payment")
    assert (paid["forward_name"], paid["reverse_name"]) == ("pays", "receives")
    assert accepted.json()["payload"]["link_id"] == paid["id"]
    assert client.post(f"{V1}/suts/{sut}/links/suggest").json()["created"] == 0


def test_action_preconditions_and_effects(client, db, world):
    ids, fields = world["ids"], world["fields"]
    link = client.post(
        f"{V1}/suts/{world['sut']}/links",
        json={
            "from_node_id": ids["Payment"],
            "to_node_id": ids["PurchaseOrder"],
            "forward_name": "pays",
            "reverse_name": "receives",
        },
    ).json()
    action = ids["Approve purchase order"]
    body = {
        "preconditions": [
            {"field": "PurchaseOrder.state", "op": "eq", "value": "pending", "message": "Only pending can be approved"},
            {"text": "The approver is not the submitter"},
        ],
        "effects": [
            {"kind": "set_field", "field": "PurchaseOrder.state", "values": ["approved", "rejected"]},
            {"kind": "create_object", "entity": "Payment", "when": "example only"},
            {"kind": "create_link", "link_id": link["id"]},
        ],
    }
    resp = client.patch(f"{V1}/nodes/{action}", json=body)
    assert resp.status_code == 200, resp.text
    node = resp.json()
    assert node["preconditions"][0]["attribute_id"] == fields["state"]
    assert node["effects"][0]["attribute_id"] == fields["state"]
    assert node["effects"][1]["node_id"] == ids["Payment"]
    # enum values are checked; unknown fields and invalid shapes are refused
    bad = client.patch(
        f"{V1}/nodes/{action}",
        json={"preconditions": [{"field": "PurchaseOrder.state", "value": "submitted"}]},
    )
    assert bad.status_code == 422 and "submitted" in json.dumps(bad.json(), ensure_ascii=False)
    for wrong in (
        {"preconditions": [{"field": "PurchaseOrder.nope", "value": "x"}]},
        {"preconditions": [{"field": "PurchaseOrder.state", "op": "in", "value": "pending"}]},
        {"effects": [{"kind": "create_link"}]},
    ):
        assert client.patch(f"{V1}/nodes/{action}", json=wrong).status_code == 422
    entity = client.patch(f"{V1}/nodes/{ids['PurchaseOrder']}", json={"preconditions": [{"text": "x"}]})
    assert entity.status_code == 422
    # renaming the field refreshes the Entity.field labels
    client.patch(f"{V1}/fields/{fields['state']}", json={"name": "status"})
    node = client.get(f"{V1}/nodes/{action}").json()
    assert node["preconditions"][0]["field"] == "PurchaseOrder.status"
    assert node["effects"][0]["field"] == "PurchaseOrder.status"
    # agent context: actions carry preconditions/effects, the model lists links
    summary = next(a for a in action_summaries(db, world["sut"]) if a["action"] == "Approve purchase order")
    assert summary["preconditions"][0] == "PurchaseOrder.status == pending"
    assert summary["effects"][0] == "PurchaseOrder.status → approved | rejected"
    assert "Create link Payment pays PurchaseOrder" in summary["effects"][2]
    catalog = model_catalog(db, world["sut"])
    assert catalog["links"][0]["forward"] == "Payment pays PurchaseOrder"
    assert link_summaries(db, world["sut"])[0]["reverse"] == "PurchaseOrder receives Payment"
    content = ModelService(db, client.app.state.bus).snapshot_content(world["sut"])
    snap = next(n for n in content["nodes"] if n["id"] == action)
    assert len(snap["preconditions"]) == 2 and len(snap["effects"]) == 3


def test_ai_suggests_links_and_action_rules(client, world):
    ids = world["ids"]
    use_model(
        client,
        call(
            "submit_result",
            {
                "suggestions": [
                    {
                        "kind": "link",
                        "from_node_id": ids["Payment"],
                        "to_node_id": ids["PurchaseOrder"],
                        "forward_name": "pays",
                        "reverse_name": "receives",
                        "cardinality": "many_to_one",
                    },
                    {
                        "kind": "rules",
                        "node_id": ids["Approve purchase order"],
                        "preconditions": [{"field": "PurchaseOrder.state", "op": "eq", "value": "pending"}],
                        "effects": [{"kind": "set_field", "field": "PurchaseOrder.state", "values": ["approved"]}],
                    },
                ]
            },
        ),
    )
    out = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={}).json()
    kinds = sorted(s["kind"] for s in out["suggestions"])
    assert kinds == ["link", "rules"]
    for sugg in out["suggestions"]:
        resp = client.post(f"{V1}/suggestions/{sugg['id']}/accept", json=NOTE)
        assert resp.status_code == 200, resp.text
    node = client.get(f"{V1}/nodes/{ids['Approve purchase order']}").json()
    assert node["preconditions"][0]["field"] == "PurchaseOrder.state"
    links = client.get(f"{V1}/suts/{world['sut']}/links").json()
    assert any(lk["forward_name"] == "pays" for lk in links)


def test_case_generation_sees_links_and_action_rules(client, world):
    ids = world["ids"]
    client.post(
        f"{V1}/suts/{world['sut']}/links",
        json={
            "from_node_id": ids["PurchaseOrder"],
            "to_node_id": ids["Supplier"],
            "forward_name": "belongs to",
            "reverse_name": "supplies",
            "required": True,
        },
    )
    client.patch(
        f"{V1}/nodes/{ids['Approve purchase order']}",
        json={"preconditions": [{"field": "PurchaseOrder.state", "value": "pending"}]},
    )
    client.post(
        f"{V1}/versions/{world['version']}/requirements",
        json={"title": "Approve", "raw_text": "Only pending purchase orders can be approved"},
    )
    fake = use_model(client, call("submit_result", {"cases": []}))
    client.post(f"{V1}/versions/{world['version']}/cases/generate", json={"automate": False})
    seen = json.dumps([str(m.content) for m in fake.seen[0]], ensure_ascii=False)
    assert "PurchaseOrder belongs to Supplier" in seen and "N:1" in seen
    assert "PurchaseOrder.state == pending" in seen
    assert "cardinality" in seen.lower()
