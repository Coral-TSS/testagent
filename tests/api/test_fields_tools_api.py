"""entity fields, tool scoping and codes, node dedup, API schemas
and OpenAPI import, schema-checked case generation, background automation, agent_api executor,
readable labels and access log."""

from __future__ import annotations

import json
import logging
import threading

import pytest

from testagent.agent.fake import FakeChatModel, call
from testagent.agent.tools import check_request_bodies
from testagent.core.access_log import level, line, route_of
from testagent.services.executions import is_api_case, select_executor
from testagent.services.model import ModelService, normalize_name

V1 = "/api/v1"


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


def invoke(client, name, args, ctx):
    registry = client.app.state.agent.runtime.registry
    spec = registry.tools[name]
    resolved = registry.resolve(name, dict(args), ctx)
    value = spec.func(ctx=ctx, **resolved) if spec.needs_ctx else spec.func(**resolved)
    return json.loads(value) if isinstance(value, str) and value[:1] in "[{" else value


@pytest.fixture
def world(client):
    sut = client.post(f"{V1}/suts", json={"code": "PROC", "name": "Procurement approval"}).json()["id"]
    other = client.post(f"{V1}/suts", json={"code": "OTHER", "name": "Other system"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v0.1"}).json()["id"]

    def node(kind, name, s=sut):
        return client.post(f"{V1}/suts/{s}/nodes", json={"kind": kind, "name": name}).json()["id"]

    order = node("entity", "PurchaseOrder")
    approver = node("entity", "Approver")
    approve = node("action", "Approve purchase order")
    node("entity", "External entity", other)
    amount = client.post(
        f"{V1}/nodes/{order}/fields",
        json={
            "name": "amount_minor",
            "display_name": "Amount",
            "data_type": "money",
            "unit": "cents",
            "constraints": [{"text": "at least 0"}],
        },
    ).json()
    req = client.post(
        f"{V1}/versions/{version}/requirements",
        json={
            "title": "Large purchases need approval",
            "raw_text": "Purchase orders over 10,000 need an approver's approval",
        },
    ).json()
    return {
        "sut": sut,
        "other": other,
        "version": version,
        "order": order,
        "approver": approver,
        "approve": approve,
        "amount": amount,
        "req": req,
    }


# ------------------------------------------------------------------ 6: entity fields
def test_field_crud_and_listing(client, world):
    amount = world["amount"]
    assert amount["data_type"] == "money" and amount["unit"] == "cents"
    untyped = client.post(f"{V1}/nodes/{world['order']}/fields", json={"name": "currency"})
    assert untyped.status_code == 422  # a field always has a type
    dup = client.post(
        f"{V1}/nodes/{world['order']}/fields",
        json={"name": "AMOUNT_MINOR", "data_type": "integer"},
    )
    assert dup.status_code == 409
    action_field = client.post(f"{V1}/nodes/{world['approve']}/fields", json={"name": "x", "data_type": "string"})
    assert action_field.status_code in (409, 422)
    listed = client.get(f"{V1}/suts/{world['sut']}/fields").json()
    assert [(f["node_name"], f["name"]) for f in listed] == [("PurchaseOrder", "amount_minor")]
    patched = client.patch(f"{V1}/fields/{amount['id']}", json={"display_name": "Purchase amount"})
    assert patched.status_code == 200 and patched.json()["display_name"] == "Purchase amount"
    node = client.get(f"{V1}/nodes/{world['order']}").json()
    assert [f["name"] for f in node["fields"]] == ["amount_minor"]


def test_snapshot_includes_fields(client, world, db):
    content = ModelService(db, client.app.state.bus).snapshot_content(world["sut"])
    assert [(f["name"], f["unit"]) for f in content["fields"]] == [("amount_minor", "cents")]


def test_structure_item_links_field(client, world):
    rid = world["req"]["id"]
    resp = client.put(
        f"{V1}/requirements/{rid}/structure",
        json={"constraint": [{"text": "Amount over 10,000", "attribute_id": world["amount"]["id"]}]},
    )
    assert resp.status_code == 200, resp.text
    detail = client.get(f"{V1}/requirements/{rid}").json()
    item = detail["structured"]["constraint"][0]
    assert item["node_id"] == world["order"]  # filled from the field's entity
    assert [(f["node_name"], f["name"]) for f in detail["fields"]] == [("PurchaseOrder", "amount_minor")]


def test_case_links_fields_and_field_coverage(client, world):
    rid = world["req"]["id"]
    client.put(
        f"{V1}/requirements/{rid}/structure",
        json={"constraint": [{"text": "Amount", "attribute_id": world["amount"]["id"]}]},
    )
    case = client.post(
        f"{V1}/suts/{world['sut']}/cases",
        json={
            "title": "Exactly 10,000 needs approval",
            "steps": [{"action": "Submit", "expected": "Pending approval"}],
            "requirement_ids": [rid],
            "attribute_ids": [world["amount"]["id"]],
        },
    ).json()
    assert [f["name"] for f in case["fields"]] == ["amount_minor"]
    cov = client.get(f"{V1}/versions/{world['version']}/coverage").json()
    assert cov["fields"]["total"] == 1 and cov["fields"]["covered"] == 1, cov["fields"]


# ------------------------------------------------------------------ 7a: scope and codes
def test_tools_default_to_current_sut_and_accept_codes(client, world):
    ctx = {"run_id": None, "sut_id": world["sut"], "inputs": {}, "resources": {}}
    # DeepSeek passed requirement / version ids as sut_id: the run's SUT wins
    for wrong in (world["req"]["id"], "REQ-001", world["version"], None):
        args = {"sut_id": wrong} if wrong else {}
        names = sorted(n["name"] for n in invoke(client, "list_nodes", args, ctx))
        assert names == ["Approve purchase order", "Approver", "PurchaseOrder"], wrong
    req = invoke(client, "get_requirement", {"requirement_id": "REQ-001"}, ctx)
    assert req["id"] == world["req"]["id"]
    fields = invoke(client, "list_fields", {}, ctx)
    assert fields[0]["entity"] == "PurchaseOrder" and fields[0]["name"] == "amount_minor"
    found = invoke(client, "search_nodes", {"query": "Amount"}, ctx)
    assert [n["name"] for n in found] == ["PurchaseOrder"]  # matched through the field display name


def test_structuring_links_existing_nodes_regression(client, world, db):
    """The model looks up nodes with a wrong sut_id, still gets this system's model, links
    existing nodes/fields, and a similar-name new node is linked instead of duplicated (7d)."""
    rid = world["req"]["id"]
    fake = use_model(
        client,
        call("list_nodes", {"sut_id": world["version"]}, "l1"),
        call(
            "submit_result",
            {
                "items": [
                    {"part": "actor", "text": "Approver (approval role)", "missing": True},
                    {"part": "action", "text": "Approve purchase order", "node_id": world["approve"]},
                    {
                        "part": "constraint",
                        "text": "Amount over 10,000",
                        "attribute_id": world["amount"]["id"],
                    },
                ]
            },
            "s1",
        ),
    )
    out = client.post(f"{V1}/requirements/{rid}/structure").json()
    assert out["status"] == "succeeded", out
    # the model received the system and its model catalog (with fields) as input
    first = json.dumps([m.content for m in fake.seen[0]], ensure_ascii=False, default=str)
    assert "amount_minor" in first and "Procurement approval" in first
    detail = out["requirement"]
    assert detail["structured"]["actor"][0]["node_id"] == world["approver"]
    assert out["suggestions"] == []
    with db.tx() as cur:
        cur.execute("SELECT count(*) AS n FROM model_node WHERE sut_id=%s", (world["sut"],))
        assert cur.fetchone()["n"] == 3  # nothing new created
    run = client.get(f"{V1}/agent/runs/{out['agent_run_id']}").json()
    tool = [s for s in run["steps"] if s["type"] == "tool"][0]
    assert "External entity" not in tool["result"]
    assert run["labels"][world["req"]["id"]] == "Large purchases need approval (REQ-001)"


def test_field_suggestion_accept_creates_field(client, world):
    rid = world["req"]["id"]
    use_model(
        client,
        call(
            "submit_result",
            {
                "items": [
                    {
                        "part": "constraint",
                        "text": "Currency can only be CNY",
                        "missing": True,
                        "suggestion": {
                            "kind": "field",
                            "node_id": world["order"],
                            "name": "currency",
                            "display_name": "Currency",
                            "data_type": "enum",
                            "enum_values": ["CNY"],
                        },
                    }
                ]
            },
        ),
    )
    resp = client.post(f"{V1}/requirements/{rid}/structure")
    assert resp.status_code == 200, resp.text
    out = resp.json()
    sugg = out["suggestions"][0]
    assert sugg["kind"] == "field" and sugg["payload"]["node_name"] == "PurchaseOrder"
    listed = client.get(f"{V1}/suts/{world['sut']}/suggestions").json()
    assert listed[0]["payload"]["node_name"] == "PurchaseOrder"
    accepted = client.post(f"{V1}/suggestions/{sugg['id']}/accept", json={}).json()
    assert accepted["status"] == "accepted"
    fields = client.get(f"{V1}/nodes/{world['order']}/fields").json()
    assert [f["name"] for f in fields] == ["amount_minor", "currency"]
    assert fields[1]["data_type"] == "enum" and fields[1]["enum_values"] == ["CNY"]
    detail = client.get(f"{V1}/requirements/{rid}").json()
    assert "currency" in [f["name"] for f in detail["fields"]]


def test_node_suggestion_for_similar_name_skipped(client, world):
    use_model(
        client,
        call(
            "submit_result",
            {"suggestions": [{"kind": "node", "node_kind": "entity", "name": "PurchaseOrder (document)"}]},
        ),
    )
    out = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={}).json()
    assert out["suggestions"] == [] and out["skipped"] == 1
    assert normalize_name("Approver (approval role)") == normalize_name("Approver")


# ------------------------------------------------------------------ 5a: API schemas
SPEC = {
    "openapi": "3.1.0",
    "paths": {
        "/sample/orders": {
            "post": {
                "operationId": "create_order",
                "summary": "Create Order",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/OrderInput"}}},
                },
                "responses": {"201": {"description": "Created"}},
            }
        },
        "/sample/orders/{order_id}/decision": {
            "post": {
                "operationId": "decide",
                "parameters": [
                    {
                        "name": "order_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"approved": {"type": "boolean"}},
                                "required": ["approved"],
                                "additionalProperties": False,
                            }
                        }
                    }
                },
                "responses": {"200": {"description": "OK"}},
            }
        },
    },
    "components": {
        "schemas": {
            "OrderInput": {
                "type": "object",
                "properties": {
                    "amount_minor": {"type": "integer", "minimum": 0},
                    "currency": {"type": "string"},
                },
                "required": ["currency"],
                "additionalProperties": False,
            }
        }
    },
}


class SpecServer:
    def __init__(self, spec):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        body = json.dumps(spec).encode()
        orders: dict[str, dict] = {}

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                if self.path == "/openapi.json":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._json(404, {"detail": "Not Found"})

            def do_POST(self):  # noqa: N802
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)))
                if self.path == "/sample/orders":
                    if set(data) - {"amount_minor", "currency"}:
                        return self._json(422, {"detail": "extra fields not permitted"})
                    oid = f"o{len(orders) + 1}"
                    big = (data.get("amount_minor") or 0) > 1_000_000
                    orders[oid] = {"id": oid, "status": "pending" if big else "approved", **data}
                    return self._json(201, orders[oid])
                return self._json(404, {"detail": "Not Found"})

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def demo():
    with SpecServer(SPEC) as server:
        yield server


def env(client, world, url):
    return client.post(f"{V1}/suts/{world['sut']}/environments", json={"name": "local", "base_url": url}).json()["id"]


def test_openapi_import_and_get_api_schema(client, world, demo):
    env_id = env(client, world, demo.url)
    resp = client.post(f"{V1}/suts/{world['sut']}/apis/import-openapi", json={"environment_id": env_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 2
    again = client.post(f"{V1}/suts/{world['sut']}/apis/import-openapi", json={"environment_id": env_id}).json()
    assert again["created"] == 0 and again["updated"] == 2
    ctx = {"run_id": None, "sut_id": world["sut"], "inputs": {}, "resources": {}}
    schema = invoke(client, "get_api_schema", {"api": "POST /sample/orders"}, ctx)
    body = schema["request"]["body"]
    assert body["properties"]["amount_minor"]["type"] == "integer"  # $ref inlined
    assert body["additionalProperties"] is False
    apis = invoke(client, "list_apis", {}, ctx)
    assert all(a["has_schema"] for a in apis)


def test_openapi_import_unreachable_502(client, world):
    resp = client.post(f"{V1}/suts/{world['sut']}/apis/import-openapi", json={"url": "http://127.0.0.1:9/x"})
    assert resp.status_code == 502


def test_case_steps_checked_against_api_schema(client, world, demo, db):
    client.post(f"{V1}/suts/{world['sut']}/apis/import-openapi", json={"url": demo.url + "/openapi.json"})
    errors = check_request_bodies(
        db,
        world["sut"],
        [
            ("s1", "Call POST /sample/orders to create a purchase order", '{"amount": 100, "approver": "x"}'),
            ("s2", "POST /sample/orders/o1/decision", '{"approved": true}'),
            ("s3", "Open the home page", None),
        ],
    )
    assert len(errors) == 1
    assert "unknown fields ['amount', 'approver']" in errors[0]
    assert "missing required ['currency']" in errors[0]


# ------------------------------------------------------------------ 5d: API cases over HTTP
def test_api_case_detection_and_selection():
    api_case = {"type_tag": "functional", "steps": [{"action": "Call POST /sample/orders"}]}
    ui_case = {"type_tag": "functional", "steps": [{"action": "Open the create page"}]}
    assert is_api_case(api_case) and not is_api_case(ui_case)
    assert select_executor("manual", None, "functional", "agent", True) == ("agent_api", None)
    assert select_executor("manual", None, "api", "agent") == ("agent_api", None)
    assert select_executor("manual", None, "functional", "agent") == ("agent_browser", None)


def test_agent_api_executor_uses_receipts(client, world, demo):
    env_id = env(client, world, demo.url)
    case = client.post(
        f"{V1}/suts/{world['sut']}/cases",
        json={
            "title": "Large purchase order pending approval",
            "steps": [
                {
                    "action": "Call POST /sample/orders",
                    "data": '{"amount_minor": 2000000, "currency": "CNY"}',
                    "expected": "201, state pending",
                }
            ],
        },
    ).json()
    use_model(
        client,
        call(
            "api_request",
            {
                "method": "POST",
                "path": "/sample/orders",
                "body": {"amount_minor": 2000000, "currency": "CNY"},
            },
            "r1",
        ),
        call("api_assert", {"kind": "status", "expected": 201}, "a1"),
        call("api_assert", {"kind": "json_equals", "path": "status", "expected": "approved"}, "a2"),
        call("submit_result", {"claimed_status": "passed", "summary": "ok"}, "s1"),
    )
    out = client.post(f"{V1}/cases/{case['id']}/debug", json={"environment_id": env_id}).json()
    assert out["executor"] == "agent_api"
    assert out["status"] == "failed", out  # the receipt decides, not the claim
    assert "expected 'approved', actual 'pending'" in out["failed_assertion"]
    assert out["steps_recorded"][0]["result"]["status"] == 201


# ------------------------------------------------------------------ C09: background automation
def three_cases(**extra) -> dict:
    return {
        "cases": [
            {
                "title": f"Amount approval {scenario}",
                "test_point": "Large-amount approval",
                "scenario": scenario,
                "steps": [{"action": "Submit purchase order", "expected": "Pending approval"}],
                "expected": "Pending approval",
                "requirement_codes": ["REQ-001"],
                **extra,
            }
            for scenario in ("normal", "boundary", "exception")
        ]
    }


def test_generate_enqueues_automation_and_batch(client, world, db):
    rid = world["req"]["id"]
    use_model(client, call("submit_result", three_cases(attribute_ids=[world["amount"]["id"]])))
    out = client.post(f"{V1}/versions/{world['version']}/cases/generate", json={"requirement_ids": [rid]})
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["status"] == "succeeded", body
    assert body["automation"]["queued"] == 3, body.get("automation")
    case_id = body["cases"][0]["id"]
    assert [f["name"] for f in client.get(f"{V1}/cases/{case_id}").json()["fields"]] == ["amount_minor"]
    progress = client.get(f"{V1}/versions/{world['version']}/automation").json()
    assert progress["counts"] == {"queued": 3}
    assert sorted(j["code"] for j in progress["jobs"]) == ["TC-001", "TC-002", "TC-003"]
    # the worker runs one: no environment → never bound, marked needs_fix with a reason
    use_model(client, *[call("submit_result", {"summary": "cannot self-check"}, f"s{i}") for i in range(3)])
    for _ in range(3):
        assert client.app.state.worker.run_once() is True
    case = client.get(f"{V1}/cases/{case_id}").json()
    jobs = client.get(f"{V1}/versions/{world['version']}/automation").json()["jobs"]
    assert case["mode"] == "manual" and case["automation_status"] == "needs_fix", jobs
    assert case["automation_note"]
    assert client.get(f"{V1}/versions/{world['version']}/automation").json()["counts"] == {"done": 3}
    # batch action: ready cases (incl. needs_fix) are queued again
    client.post(f"{V1}/cases/{case_id}/status", json={"status": "ready"})
    batch = client.post(f"{V1}/versions/{world['version']}/automate", json={}).json()
    assert batch["queued"] == 1
    drafts = client.post(f"{V1}/versions/{world['version']}/automate", json={"include_drafts": True}).json()
    assert drafts["queued"] == 3


def test_generate_without_automation(client, world):
    use_model(client, call("submit_result", three_cases()))
    out = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["req"]["id"]], "automate": False},
    ).json()
    assert out["status"] == "succeeded" and out["automation"]["queued"] == 0


def test_generate_rejects_body_not_matching_schema(client, world, demo):
    client.post(f"{V1}/suts/{world['sut']}/apis/import-openapi", json={"url": demo.url + "/openapi.json"})
    bad = three_cases()
    bad["cases"][0]["steps"] = [{"action": "Call POST /sample/orders", "data": '{"amount": 1}', "expected": "201"}]
    fake = use_model(client, call("submit_result", bad), call("submit_result", three_cases()))
    out = client.post(
        f"{V1}/versions/{world['version']}/cases/generate",
        json={"requirement_ids": [world["req"]["id"]], "automate": False},
    ).json()
    assert out["status"] == "succeeded"
    feedback = " ".join(str(m.content) for m in fake.seen[1])
    assert "unknown fields ['amount']" in feedback
    assert "get_api_schema" in fake.bound_tools


# ------------------------------------------------------------------ 7b: access log
def test_access_log_is_readable(client, world, caplog):
    class Route:
        path = "/api/v1/versions/{version_id}/requirements"

    assert route_of({"route": Route()}) == Route.path
    assert route_of({"path": f"/api/v1/suts/{world['sut']}/nodes"}) == "/api/v1/suts/{id}/nodes"
    assert line("POST", Route.path, 201, 12.3) == f"POST {Route.path} → 201 (12 ms)"
    assert level("GET", 200) == logging.DEBUG and level("POST", 201) == logging.INFO
    assert level("GET", 404) == logging.WARNING
    with caplog.at_level(logging.INFO, logger="testagent.access"):
        client.post(f"{V1}/suts/{world['sut']}/nodes", json={"kind": "entity", "name": "Supplier"})
    lines = [r.getMessage() for r in caplog.records if r.name == "testagent.access"]
    assert len(lines) == 1 and lines[0].startswith("POST /api/v1/suts/{sut_id}/nodes → 201 (")
    assert world["sut"] not in lines[0]


def test_data_schema_migrated_to_fields(client, world, db):
    """Migration 0014 turns a node's data_schema JSON into field rows (e.g. PurchaseOrder.amount)."""
    from pathlib import Path

    import testagent

    root = Path(testagent.__file__).parent / "migrations"
    sql = (root / "0014_attributes_api_schema.sql").read_text("utf-8")
    start = sql.index("INSERT INTO entity_attribute")
    statement = sql[start : sql.index(";", start)]
    supplier = client.post(f"{V1}/suts/{world['sut']}/nodes", json={"kind": "entity", "name": "Supplier"}).json()["id"]
    with db.tx() as cur:
        cur.execute(
            "UPDATE model_node SET data_schema=%s::jsonb WHERE id=%s",
            ('{"id": "string", "amount": "number", "rating": {"type": "int"}}', supplier),
        )
        cur.execute(statement)
    fields = client.get(f"{V1}/nodes/{supplier}/fields").json()
    assert [(f["name"], f["data_type"]) for f in fields] == [
        ("id", "string"),
        ("amount", "number"),
        ("rating", "integer"),
    ]
    assert fields[1]["description"].startswith("migrated from data_schema")
