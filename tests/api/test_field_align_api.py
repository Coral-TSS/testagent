"""entity fields follow the code entity / API field names; a different database column is
kept as storage_name. Mismatching names are proposed as renames that keep every link."""

from __future__ import annotations

import pytest

from examples.procurement.api import create_app as create_demo
from testagent.agent.fake import FakeChatModel, call
from testagent.services.field_align import field_suggestions, rename_match, suggest_alignment
from testagent.services.model import ModelService
from testagent.services.openapi_import import OpenApiImportService

V1 = "/api/v1"
NOTE = {"note": "Confirmed with the product owner"}  # accepting an AI inference (#6)


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


@pytest.fixture
def world(client, db, tmp_path):
    sut = client.post(f"{V1}/suts", json={"code": "PROC", "name": "Procurement approval"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v0.1"}).json()["id"]

    def node(kind, name):
        return client.post(f"{V1}/suts/{sut}/nodes", json={"kind": kind, "name": name}).json()

    order = node("entity", "PurchaseOrder")["id"]
    create = node("action", "Create purchase order")["id"]
    client.post(
        f"{V1}/suts/{sut}/edges",
        json={"source_node_id": create, "target_node_id": order, "role": "object"},
    )
    fields = {}
    for name, data_type in (("id", "string"), ("amount", "number"), ("status", "string")):
        fields[name] = client.post(f"{V1}/nodes/{order}/fields", json={"name": name, "data_type": data_type}).json()
    OpenApiImportService(db, client.app.state.bus).import_spec(sut, create_demo(tmp_path / "sample.db").openapi())
    apis = {f"{a['method']} {a['path']}": a for a in client.get(f"{V1}/suts/{sut}/apis").json()}
    client.put(f"{V1}/nodes/{create}/apis", json={"api_ids": [apis["POST /sample/orders"]["id"]]})
    req = client.post(
        f"{V1}/versions/{version}/requirements",
        json={"title": "Large purchases need approval", "raw_text": "Amount of 50,000 or more needs approval"},
    ).json()
    client.put(
        f"{V1}/requirements/{req['id']}/structure",
        json={"constraint": [{"text": "Amount ≥ 50,000", "attribute_id": fields["amount"]["id"]}]},
    )
    case = client.post(
        f"{V1}/suts/{sut}/cases",
        json={
            "title": "Exactly 50,000 needs approval",
            "steps": [{"action": "Submit", "expected": "Pending approval"}],
            "requirement_ids": [req["id"]],
            "attribute_ids": [fields["amount"]["id"], fields["status"]["id"]],
        },
    ).json()
    return {
        "sut": sut,
        "order": order,
        "create": create,
        "fields": fields,
        "req": req,
        "case": case,
    }


def test_rename_match():
    assert rename_match("amount", "amount_minor")
    assert rename_match("status", "state") and rename_match("state", "status")
    assert not rename_match("id", "order_id")  # suffix matches are too loose
    assert not rename_match("amount", "amount")
    assert not rename_match("name", "currency")


def test_alignment_proposes_renames_and_missing_fields(client, db, world):
    with db.tx() as cur:
        items = {i["name"]: i for i in field_suggestions(cur, world["sut"])}
    assert items["amount_minor"]["rename_from"] == "amount"
    assert items["state"]["rename_from"] == "status"
    assert items["state"]["data_type"] == "enum" and "pending" in items["state"]["enum_values"]
    assert "rename_from" not in items["currency"] and "not registered" in items["currency"]["reason"]
    assert "id" not in items  # already matches the API
    created = suggest_alignment(db, client.app.state.bus, world["sut"])
    assert len(created) == len(items)
    rename = next(s for s in created if s["payload"]["name"] == "amount_minor")
    assert rename["payload"]["rename_attribute_id"] == world["fields"]["amount"]["id"]
    assert suggest_alignment(db, client.app.state.bus, world["sut"]) == []  # de-duplicated


def test_accepting_a_rename_keeps_requirement_and_case_links(client, db, world):
    created = suggest_alignment(db, client.app.state.bus, world["sut"])
    by_name = {s["payload"]["name"]: s for s in created}
    # #6: from the OpenAPI schema, so accepted without a note
    assert by_name["amount_minor"]["source"] == "openapi" and "amount_minor" in by_name["amount_minor"]["evidence"]
    resp = client.post(f"{V1}/suggestions/{by_name['amount_minor']['id']}/accept", json={})
    assert resp.status_code == 200, resp.text
    field = client.get(f"{V1}/fields/{world['fields']['amount']['id']}").json()
    assert field["name"] == "amount_minor" and field["data_type"] == "integer"
    assert {r["code"] for r in field["references"]} >= {world["req"]["code"]}
    assert world["case"]["code"] in {r["code"] for r in field["references"]}
    req = client.get(f"{V1}/requirements/{world['req']['id']}").json()
    assert [f["name"] for f in req["fields"]] == ["amount_minor"]
    # the action's parameters now point at the renamed field
    node = client.get(f"{V1}/nodes/{world['create']}").json()
    amount_in = next(p for p in node["inputs"] if p["name"] == "amount_minor")
    assert amount_in["attribute_id"] == field["id"] and amount_in["field"] == "PurchaseOrder.amount_minor"
    # accepting a new-field suggestion binds the action outputs too
    client.post(f"{V1}/suggestions/{by_name['currency']['id']}/accept", json={})
    node = client.get(f"{V1}/nodes/{world['create']}").json()
    out = {p["name"]: p for p in node["outputs"]}
    assert out["currency"]["field"] == "PurchaseOrder.currency"


def test_storage_name_is_kept_and_in_snapshot(client, db, world):
    fid = world["fields"]["status"]["id"]
    resp = client.patch(f"{V1}/fields/{fid}", json={"name": "state", "storage_name": "status"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["storage_name"] == "status"
    content = ModelService(db, client.app.state.bus).snapshot_content(world["sut"])
    snap = next(f for f in content["fields"] if f["id"] == fid)
    assert snap["name"] == "state" and snap["storage_name"] == "status"
    cleared = client.patch(f"{V1}/fields/{fid}", json={"storage_name": "  "}).json()
    assert cleared["storage_name"] is None


def test_ai_field_rename_suggestion(client, world):
    fake = use_model(
        client,
        call(
            "submit_result",
            {
                "suggestions": [
                    {
                        "kind": "field",
                        "node_id": world["order"],
                        "name": "amount_minor",
                        "data_type": "integer",
                        "rename_from": "price",  # no such field: sent back to the model
                    }
                ]
            },
        ),
        call(
            "submit_result",
            {
                "suggestions": [
                    {
                        "kind": "field",
                        "node_id": world["order"],
                        "name": "amount_minor",
                        "data_type": "integer",
                        "rename_from": "amount",
                    }
                ]
            },
        ),
    )
    out = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={}).json()
    assert any("rename_from price" in str(m) for m in fake.seen[-1])
    sugg = out["suggestions"][0]
    assert sugg["payload"]["rename_attribute_id"] == world["fields"]["amount"]["id"]
    assert client.post(f"{V1}/suggestions/{sugg['id']}/accept", json=NOTE).status_code == 200
    names = [f["name"] for f in client.get(f"{V1}/nodes/{world['order']}/fields").json()]
    assert names == ["id", "amount_minor", "status"]
