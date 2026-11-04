"""actions and APIs describe their purpose, inputs/outputs and formats; entity fields
always carry a type (with enum values / referenced entity, format, required)."""

from __future__ import annotations

import pytest

from examples.procurement.api import create_app as create_demo
from testagent.agent.fake import FakeChatModel, call
from testagent.agent.tools import action_summaries, api_summaries
from testagent.services.io_spec import (
    api_io,
    apply_request_fields,
    request_params,
    schema_params,
)
from testagent.services.model import ModelService
from testagent.services.openapi_import import (
    OpenApiImportService,
    is_default_summary,
    parse_operations,
)

V1 = "/api/v1"
NOTE = {"note": "Confirmed with the product owner"}  # accepting an AI inference (#6)
ORDER_INPUTS = ["amount_minor", "currency", "title", "supplier_id"]  # + supplier, title


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


@pytest.fixture
def demo_spec(tmp_path):
    return create_demo(tmp_path / "sample.db").openapi()


@pytest.fixture
def world(client, db, demo_spec):
    sut = client.post(f"{V1}/suts", json={"code": "PROC", "name": "Procurement approval"}).json()["id"]

    def node(kind, name):
        return client.post(f"{V1}/suts/{sut}/nodes", json={"kind": kind, "name": name}).json()

    order = node("entity", "PurchaseOrder")["id"]
    supplier = node("entity", "Supplier")["id"]
    create = node("action", "Create purchase order")["id"]
    approve = node("action", "Approve purchase order")["id"]
    amount = client.post(
        f"{V1}/nodes/{order}/fields",
        json={"name": "amount_minor", "display_name": "Amount", "data_type": "money", "unit": "cents"},
    ).json()
    OpenApiImportService(db, client.app.state.bus).import_spec(sut, demo_spec)
    apis = {f"{a['method']} {a['path']}": a for a in client.get(f"{V1}/suts/{sut}/apis").json()}
    return {
        "sut": sut,
        "order": order,
        "supplier": supplier,
        "create": create,
        "approve": approve,
        "amount": amount,
        "apis": apis,
    }


# ------------------------------------------------------------------ schema → readable tables
def test_schema_params_flatten_types_formats_and_enums():
    schema = {
        "type": "object",
        "required": ["state"],
        "properties": {
            "amount_minor": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
            "state": {"type": "string", "enum": ["pending", "paid"], "description": "Status"},
            "due": {"type": "string", "format": "date"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "meta": {"type": "object", "properties": {"note": {"type": "string"}}},
        },
    }
    params = {p["name"]: p for p in schema_params(schema, "body")}
    assert params["amount_minor"]["data_type"] == "integer"
    assert params["amount_minor"]["format"] == "≥ 0, nullable"
    assert params["state"]["data_type"] == "enum" and params["state"]["required"] is True
    assert params["state"]["enum_values"] == ["pending", "paid"]
    assert params["due"]["data_type"] == "date"
    assert params["tags"]["format"].startswith("string[]")
    assert "meta.note" in params


def test_edited_fields_write_back_into_schema_and_keep_limits(demo_spec):
    op = next(o for o in parse_operations(demo_spec) if o["path"] == "/sample/orders" and o["method"] == "POST")
    params = request_params(op["request_schema"])
    amount = next(p for p in params if p["name"] == "amount_minor")
    amount["format"] = "integer in cents"
    currency = next(p for p in params if p["name"] == "currency")
    currency.update(data_type="enum", enum_values=["CNY", "USD"])
    schema = apply_request_fields(op["request_schema"], params)
    body = schema["body"]
    assert body["additionalProperties"] is False and body["required"] == ["currency"]
    assert body["properties"]["currency"]["enum"] == ["CNY", "USD"]
    inner = body["properties"]["amount_minor"]["anyOf"][0]
    assert inner["minimum"] == 0 and inner["x-format"] == "integer in cents"
    again = {p["name"]: p for p in request_params(schema)}
    assert again["amount_minor"]["format"] == "integer in cents"
    assert again["currency"]["data_type"] == "enum"
    # unchanged rows do not copy derived texts into the schema
    untouched = apply_request_fields(op["request_schema"], request_params(op["request_schema"]))
    assert "x-format" not in str(untouched)


def test_api_io_from_demo_openapi(demo_spec):
    op = next(o for o in parse_operations(demo_spec) if o["path"] == "/sample/orders" and o["method"] == "POST")
    assert op["name"] == "Create purchase order" and "approval" in op["description"]
    assert op["request_content_type"] == "application/json"
    io = api_io(op)
    assert [p["name"] for p in io["inputs"]] == ORDER_INPUTS
    outputs = {p["name"]: p for p in io["outputs"]}
    assert outputs["state"]["data_type"] == "enum" and "paid" in outputs["state"]["enum_values"]
    assert io["input_format"] == "Request body JSON object (application/json)"
    assert io["output_format"] == "HTTP 201, JSON object (application/json)"


def test_default_summary_detection():
    assert is_default_summary("Create Order", "create_order_sample_orders_post")
    assert not is_default_summary("Create purchase order", "create_order_sample_orders_post")
    assert is_default_summary(None, None)


# ------------------------------------------------------------------ API registry
def test_api_list_has_purpose_content_types_and_io(client, world):
    api = world["apis"]["POST /sample/orders"]
    assert api["description"].startswith("Create a purchase order")
    assert api["request_content_type"] == "application/json"
    assert api["response_content_type"] == "application/json"
    assert [p["name"] for p in api["io"]["inputs"]] == ORDER_INPUTS
    assert "state" in [p["name"] for p in api["io"]["outputs"]]


def test_import_keeps_manual_name_and_purpose_but_replaces_default_summary(client, db, world, demo_spec):
    api = world["apis"]["POST /sample/orders/{order_id}/decision"]
    client.patch(f"{V1}/apis/{api['id']}", json={"name": "Decide", "description": "Manual note"})
    pay = world["apis"]["POST /sample/orders/{order_id}/payments"]
    client.patch(f"{V1}/apis/{pay['id']}", json={"name": "Pay", "description": ""})
    OpenApiImportService(db, client.app.state.bus).import_spec(world["sut"], demo_spec)
    rows = {f"{a['method']} {a['path']}": a for a in client.get(f"{V1}/suts/{world['sut']}/apis").json()}
    decide = rows["POST /sample/orders/{order_id}/decision"]
    assert decide["name"] == "Approve purchase order"  # "Decide" was FastAPI's fallback summary
    assert decide["description"] == "Manual note"  # a typed purpose wins
    assert rows["POST /sample/orders/{order_id}/payments"]["description"].startswith("Record a payment for an approved")


def test_patch_api_fields_tables(client, world):
    api = world["apis"]["POST /sample/orders"]
    inputs = api["io"]["inputs"]
    for p in inputs:
        if p["name"] == "currency":
            p.update(data_type="enum", enum_values=["CNY"], description="Currency")
    outputs = [p for p in api["io"]["outputs"] if p["name"] != "approval_required"]
    resp = client.patch(
        f"{V1}/apis/{api['id']}",
        json={"request_fields": inputs, "response_fields": outputs, "description": "Create order"},
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()
    assert row["schema_source"] == "manual" and row["description"] == "Create order"
    cur = {p["name"]: p for p in row["io"]["inputs"]}
    assert cur["currency"]["enum_values"] == ["CNY"]
    assert "approval_required" not in [p["name"] for p in row["io"]["outputs"]]
    bad = client.patch(
        f"{V1}/apis/{api['id']}",
        json={"request_fields": [{"name": "x", "data_type": "enum"}]},
    )
    assert bad.status_code == 422


# ------------------------------------------------------------------ action inputs / outputs
def test_action_io_crud_binds_entity_fields_and_validates(client, world):
    body = {
        "description": "Submit a purchase order; the system decides whether approval is required",
        "inputs": [
            {
                "name": "amount_minor",
                "display_name": "Amount",
                "data_type": "money",
                "required": True,
                "format": "integer in cents",
                "field": "PurchaseOrder.amount_minor",
            },
            {"name": "currency", "data_type": "enum", "enum_values": ["CNY", "USD"]},
        ],
        "outputs": [{"name": "state", "data_type": "enum", "enum_values": ["pending"]}],
        "input_format": "JSON request body",
        "output_format": "JSON object",
    }
    resp = client.patch(f"{V1}/nodes/{world['create']}", json=body)
    assert resp.status_code == 200, resp.text
    node = resp.json()
    assert node["inputs"][0]["attribute_id"] == world["amount"]["id"]
    assert node["inputs"][0]["field"] == "PurchaseOrder.amount_minor"
    assert node["input_format"] == "JSON request body" and node["outputs"][0]["name"] == "state"
    for bad in (
        {"inputs": [{"name": "x", "data_type": "enum"}]},  # enum without values
        {"inputs": [{"name": "x", "data_type": "string", "field": "PurchaseOrder.nope"}]},
        {"inputs": [{"name": "x"}]},  # type required
        {"inputs": [{"name": "a", "data_type": "string"}, {"name": "A", "data_type": "string"}]},
    ):
        assert client.patch(f"{V1}/nodes/{world['create']}", json=bad).status_code == 422, bad
    entity = client.patch(f"{V1}/nodes/{world['order']}", json={"inputs": [{"name": "x", "data_type": "string"}]})
    assert entity.status_code == 422
    graph = client.get(f"{V1}/suts/{world['sut']}/graph").json()
    listed = next(n for n in graph["nodes"] if n["id"] == world["create"])
    assert [p["name"] for p in listed["inputs"]] == ["amount_minor", "currency"]


def test_linking_api_inherits_io_and_purpose(client, world):
    api = world["apis"]["POST /sample/orders"]
    resp = client.put(f"{V1}/nodes/{world['create']}/apis", json={"api_ids": [api["id"]]})
    assert resp.status_code == 200
    node = client.get(f"{V1}/nodes/{world['create']}").json()
    assert node["description"].startswith("Create a purchase order")
    names = [p["name"] for p in node["inputs"]]
    assert names == ORDER_INPUTS
    assert node["inputs"][0]["attribute_id"] == world["amount"]["id"]  # bound by name
    assert "state" in [p["name"] for p in node["outputs"]]
    assert node["input_format"].startswith("Request body JSON")
    # explicit re-derive merges without duplicating; replace rebuilds
    again = client.post(f"{V1}/nodes/{world['create']}/io/from-apis", json={}).json()
    assert again["inputs_added"] == 0 and again["outputs_added"] == 0
    client.patch(
        f"{V1}/nodes/{world['create']}",
        json={"inputs": [{"name": "note", "data_type": "string"}]},
    )
    merged = client.post(f"{V1}/nodes/{world['create']}/io/from-apis", json={}).json()
    assert [p["name"] for p in merged["node"]["inputs"]] == ["note", *ORDER_INPUTS]
    replaced = client.post(f"{V1}/nodes/{world['create']}/io/from-apis", json={"replace": True}).json()
    assert [p["name"] for p in replaced["node"]["inputs"]] == ORDER_INPUTS
    no_api = client.post(f"{V1}/nodes/{world['approve']}/io/from-apis", json={})
    assert no_api.status_code == 422


def test_existing_io_is_not_overwritten_when_linking(client, world):
    client.patch(
        f"{V1}/nodes/{world['approve']}",
        json={"description": "Manual note", "inputs": [{"name": "ok", "data_type": "boolean"}]},
    )
    api = world["apis"]["POST /sample/orders/{order_id}/decision"]
    client.put(f"{V1}/nodes/{world['approve']}/apis", json={"api_ids": [api["id"]]})
    node = client.get(f"{V1}/nodes/{world['approve']}").json()
    assert node["description"] == "Manual note"
    assert [p["name"] for p in node["inputs"]] == ["ok"]


def test_snapshot_and_agent_context_include_io(client, db, world):
    api = world["apis"]["POST /sample/orders"]
    client.put(f"{V1}/nodes/{world['create']}/apis", json={"api_ids": [api["id"]]})
    content = ModelService(db, client.app.state.bus).snapshot_content(world["sut"])
    node = next(n for n in content["nodes"] if n["id"] == world["create"])
    assert [p["name"] for p in node["inputs"]] == ORDER_INPUTS
    snap_api = next(a for a in content["apis"] if a["path"] == "/sample/orders" and a["method"] == "POST")
    assert snap_api["description"] and snap_api["request_content_type"] == "application/json"
    assert "required" in content["fields"][0] and "enum_values" in content["fields"][0]
    actions = action_summaries(db, world["sut"])
    created = next(a for a in actions if a["action"] == "Create purchase order")
    assert created["apis"] == ["POST /sample/orders"] and created["purpose"]
    assert created["inputs"][0]["field"] == "PurchaseOrder.amount_minor"
    apis = {f"{a['method']} {a['path']}": a for a in api_summaries(db, world["sut"])}
    assert apis["POST /sample/orders"]["response_fields"]["state"] == "enum"
    assert apis["POST /sample/orders"]["purpose"].startswith("Create a purchase order")


# ------------------------------------------------------------------ entity field types
def test_field_types_enum_reference_and_required(client, world):
    order = world["order"]
    ok = client.post(
        f"{V1}/nodes/{order}/fields",
        json={
            "name": "state",
            "data_type": "enum",
            "enum_values": ["pending", "approved", "pending"],
            "required": True,
            "format": "lowercase english",
            "example": "pending",
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["enum_values"] == ["pending", "approved"] and ok.json()["required"] is True
    assert client.post(f"{V1}/nodes/{order}/fields", json={"name": "x", "data_type": "enum"}).status_code == 422
    assert client.post(f"{V1}/nodes/{order}/fields", json={"name": "y", "data_type": "reference"}).status_code == 422
    ref = client.post(
        f"{V1}/nodes/{order}/fields",
        json={"name": "supplier_id", "data_type": "reference", "ref_node_id": world["supplier"]},
    )
    assert ref.status_code == 201 and ref.json()["ref_node_name"] == "Supplier"
    to_enum = client.patch(f"{V1}/fields/{world['amount']['id']}", json={"data_type": "enum"})
    assert to_enum.status_code == 422
    cleared = client.patch(f"{V1}/fields/{world['amount']['id']}", json={"data_type": None})
    assert cleared.status_code == 422


# ------------------------------------------------------------------ AI fills purpose / IO
def test_complete_model_io_suggestion_accept_merges(client, world):
    use_model(
        client,
        call(
            "submit_result",
            {
                "suggestions": [
                    {
                        "kind": "io",
                        "node_id": world["approve"],
                        "description": "The approver approves or rejects a pending purchase order",
                        "inputs": [
                            {"name": "order_id", "data_type": "string", "required": True},
                            {
                                "name": "approved",
                                "data_type": "boolean",
                                "required": True,
                                "field": "PurchaseOrder.approved",  # not in the model: kept as a note
                            },
                        ],
                        "outputs": [{"name": "recorded", "data_type": "boolean"}],
                        "input_format": "JSON request body",
                    }
                ]
            },
        ),
    )
    out = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={}).json()
    assert len(out["suggestions"]) == 1, out
    sugg = out["suggestions"][0]
    assert sugg["kind"] == "io" and sugg["payload"]["node_name"] == "Approve purchase order"
    approved = sugg["payload"]["inputs"][1]
    assert "attribute_id" not in approved and "PurchaseOrder.approved" in approved["description"]
    accepted = client.post(f"{V1}/suggestions/{sugg['id']}/accept", json=NOTE)
    assert accepted.status_code == 200, accepted.text
    node = client.get(f"{V1}/nodes/{world['approve']}").json()
    assert node["description"].startswith("The approver")
    assert [p["name"] for p in node["inputs"]] == ["order_id", "approved"]
    assert node["input_format"] == "JSON request body"
    # a second identical suggestion adds nothing and is skipped
    use_model(
        client,
        call(
            "submit_result",
            {
                "suggestions": [
                    {
                        "kind": "io",
                        "node_id": world["approve"],
                        "inputs": [{"name": "order_id", "data_type": "string"}],
                    }
                ]
            },
        ),
    )
    out = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={}).json()
    assert out["suggestions"] == [] and out["skipped"] == 1


def test_io_suggestion_for_entity_is_rejected_by_validation(client, world):
    fake = use_model(
        client,
        call(
            "submit_result",
            {"suggestions": [{"kind": "io", "node_id": world["order"], "inputs": []}]},
        ),
        call("submit_result", {"suggestions": []}),
    )
    out = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={}).json()
    assert out["status"] == "succeeded" and out["suggestions"] == []
    assert any("not an action" in str(m) for m in fake.seen[-1])


def test_structure_io_suggestions(client, world):
    version = client.post(f"{V1}/suts/{world['sut']}/versions", json={"name": "v1"}).json()["id"]
    req = client.post(
        f"{V1}/versions/{version}/requirements",
        json={"title": "Create order", "raw_text": "The requester submits a purchase order"},
    ).json()
    use_model(
        client,
        call(
            "submit_result",
            {
                "items": [{"part": "action", "text": "Submit purchase order", "node_id": world["create"]}],
                "io_suggestions": [
                    {
                        "node_id": world["create"],
                        "description": "Submit purchase order",
                        "inputs": [
                            {
                                "name": "amount_minor",
                                "data_type": "money",
                                "field": "PurchaseOrder.amount_minor",
                            }
                        ],
                    }
                ],
            },
        ),
    )
    out = client.post(f"{V1}/requirements/{req['id']}/structure").json()
    assert [s["kind"] for s in out["suggestions"]] == ["io"], out
    assert out["suggestions"][0]["payload"]["inputs"][0]["attribute_id"] == world["amount"]["id"]


def test_inherited_io_binds_only_fields_of_the_object_entity(client, world):
    pay_node = client.post(f"{V1}/suts/{world['sut']}/nodes", json={"kind": "action", "name": "Record payment"}).json()[
        "id"
    ]
    payment = client.post(f"{V1}/suts/{world['sut']}/nodes", json={"kind": "entity", "name": "Payment"}).json()["id"]
    for owner in (world["order"], payment):
        client.post(f"{V1}/nodes/{owner}/fields", json={"name": "id", "data_type": "string"})
    client.post(f"{V1}/nodes/{payment}/fields", json={"name": "amount", "data_type": "money"})
    client.post(
        f"{V1}/suts/{world['sut']}/edges",
        json={"source_node_id": pay_node, "target_node_id": payment, "role": "object"},
    )
    api = world["apis"]["POST /sample/orders/{order_id}/payments"]
    client.put(f"{V1}/nodes/{pay_node}/apis", json={"api_ids": [api["id"]]})
    node = client.get(f"{V1}/nodes/{pay_node}").json()
    out = {p["name"]: p for p in node["outputs"]}
    assert out["id"]["field"] == "Payment.id"  # not PurchaseOrder.id
    assert out["amount"]["field"] == "Payment.amount"
    assert "field" not in out["order_id"]
