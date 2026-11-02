"""the procurement demo has suppliers, a full UI, readable OpenAPI, a reset endpoint and
documented seeded bugs (PROCUREMENT_DEMO_BUGS, on by default, off in platform tests)."""

import re

import pytest
from fastapi.testclient import TestClient

from examples.procurement.api import create_app
from examples.procurement.service import DEFAULT_SUPPLIERS, ProcurementService


def demo(tmp_path, bugs=False):
    return TestClient(create_app(tmp_path / "demo.db", demo_bugs=bugs))


def test_platform_tests_run_with_seeded_bugs_off(tmp_path, monkeypatch):
    monkeypatch.delenv("PROCUREMENT_DEMO_BUGS", raising=False)
    assert ProcurementService(tmp_path / "a.db").demo_bugs is True  # demo default: on
    monkeypatch.setenv("PROCUREMENT_DEMO_BUGS", "0")
    assert ProcurementService(tmp_path / "b.db").demo_bugs is False


def test_suppliers_seeded_listed_and_created(tmp_path):
    app = demo(tmp_path)
    suppliers = app.get("/sample/suppliers").json()
    assert [s["name"] for s in suppliers] == [s["name"] for s in DEFAULT_SUPPLIERS]
    created = app.post("/sample/suppliers", json={"name": "New supplier", "contact": "Wang Wu 555-0199"})
    assert created.status_code == 201
    body = created.json()
    assert app.get(f"/sample/suppliers/{body['id']}").json()["name"] == "New supplier"
    assert app.post("/sample/suppliers", json={"name": "New supplier"}).status_code == 409
    assert app.post("/sample/suppliers", json={"name": ""}).status_code == 422
    assert app.get("/sample/suppliers/nope").status_code == 404


def test_orders_reference_a_real_supplier(tmp_path):
    app = demo(tmp_path)
    supplier = app.get("/sample/suppliers").json()[0]
    order = app.post(
        "/sample/orders",
        json={
            "title": "Office chair",
            "supplier_id": supplier["id"],
            "amount_minor": 120000,
            "currency": "CNY",
        },
    )
    assert order.status_code == 201
    o = order.json()
    assert (o["supplier_id"], o["supplier_name"], o["title"]) == (
        supplier["id"],
        supplier["name"],
        "Office chair",
    )
    assert app.get(f"/sample/orders/{o['id']}").json()["id"] == o["id"]
    assert app.get("/sample/orders").json()[0]["id"] == o["id"]
    assert app.get("/sample/orders", params={"supplier_id": supplier["id"]}).json()[0]["id"] == o["id"]
    assert app.get("/sample/orders", params={"state": "pending"}).json() == []
    missing = app.post("/sample/orders", json={"supplier_id": "nope", "amount_minor": 1, "currency": "CNY"})
    assert missing.status_code == 422 and "Supplier" in missing.json()["detail"]
    assert app.get("/sample/orders/nope").status_code == 404


def test_small_orders_are_auto_approved_and_payable(tmp_path):
    app = demo(tmp_path)
    o = app.post("/sample/orders", json={"amount_minor": 4999999, "currency": "CNY"}).json()
    assert (o["approval_required"], o["state"]) == (False, "approved")
    paid = app.post(f"/sample/orders/{o['id']}/payments", json={"callback_id": "cb-1"})
    assert paid.status_code == 200 and paid.json()["amount"] == 4999999
    assert app.get(f"/sample/orders/{o['id']}").json()["state"] == "paid"


def test_errors_are_readable(tmp_path):
    app = demo(tmp_path)
    o = app.post("/sample/orders", json={"amount_minor": 5000000, "currency": "CNY"}).json()
    r = app.post(f"/sample/orders/{o['id']}/payments", json={"callback_id": "c"})
    assert r.status_code == 409 and "not approved" in r.json()["detail"]


def test_reset_restores_seed_data(tmp_path):
    app = demo(tmp_path)
    app.post("/sample/suppliers", json={"name": "Temporary"})
    app.post("/sample/orders", json={"amount_minor": 1, "currency": "CNY"})
    r = app.post("/sample/reset")
    assert r.status_code == 200 and r.json() == {"reset": True, "suppliers": len(DEFAULT_SUPPLIERS)}
    assert app.get("/sample/orders").json() == []
    assert len(app.get("/sample/suppliers").json()) == len(DEFAULT_SUPPLIERS)


def test_reset_on_start(tmp_path, monkeypatch):
    db = tmp_path / "demo.db"
    TestClient(create_app(db, demo_bugs=False)).post("/sample/orders", json={"amount_minor": 1, "currency": "CNY"})
    monkeypatch.setenv("PROCUREMENT_RESET_ON_START", "1")
    assert TestClient(create_app(db, demo_bugs=False)).get("/sample/orders").json() == []


def test_old_database_schema_is_upgraded(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:
        c.executescript(
            "CREATE TABLE orders (id TEXT PRIMARY KEY, amount INTEGER, currency TEXT,"
            " approval_required INTEGER, state TEXT NOT NULL);"
            "INSERT INTO orders VALUES ('x', 1, 'CNY', 0, 'policy_unknown');"
        )
    app = TestClient(create_app(db, demo_bugs=False))
    assert app.get("/sample/orders").json() == []
    assert len(app.get("/sample/suppliers").json()) == len(DEFAULT_SUPPLIERS)


def test_openapi_is_readable(tmp_path):
    spec = demo(tmp_path).get("/openapi.json").json()
    ops = {f"{m.upper()} {p}": op for p, item in spec["paths"].items() for m, op in item.items()}
    assert set(ops) == {
        "GET /sample/suppliers",
        "POST /sample/suppliers",
        "GET /sample/suppliers/{supplier_id}",
        "GET /sample/orders",
        "POST /sample/orders",
        "GET /sample/orders/{order_id}",
        "POST /sample/orders/{order_id}/decision",
        "POST /sample/orders/{order_id}/payments",
        "GET /sample/orders/{order_id}/payments",
        "POST /sample/reset",
    }
    for key, op in ops.items():
        assert re.fullmatch(r"[A-Z][A-Za-z ]+", op["summary"]), key
        assert op.get("description"), key
        ok = op["responses"].get("200") or op["responses"].get("201")
        assert "$ref" in str(ok["content"]["application/json"]["schema"]), key
    schemas = spec["components"]["schemas"]
    order_in = schemas["OrderInput"]
    assert order_in["properties"]["supplier_id"]["description"]
    assert order_in.get("examples") or order_in["properties"]["amount_minor"].get("examples")
    out = schemas["OrderOut"]["properties"]
    assert {"supplier_id", "supplier_name", "title", "created_at"} <= set(out)


def test_ui_has_stable_test_ids_and_bug_flag(tmp_path):
    html = demo(tmp_path).get("/").text
    for tid in [
        "order-form",
        "order-title",
        "order-supplier",
        "order-amount",
        "order-currency",
        "order-submit",
        "order-list",
        "order-detail",
        "approve",
        "reject",
        "pay-callback",
        "pay-submit",
        "payment-list",
        "supplier-form",
        "supplier-name",
        "supplier-submit",
        "supplier-list",
        "reset-demo",
    ]:
        assert f'data-testid="{tid}"' in html, tid
    assert "window.DEMO_BUGS = false" in html
    assert "window.DEMO_BUGS = true" in demo(tmp_path / "b", bugs=True).get("/").text


@pytest.mark.parametrize("bugs", [False, True])
def test_seeded_bugs_only_when_enabled(tmp_path, bugs):
    s = ProcurementService(tmp_path / "s.db", demo_bugs=bugs)
    at = s.create_order(5000000, "CNY")
    assert at["approval_required"] is (not bugs)
    small = s.create_order(100, "CNY")
    s.pay(small["id"], "cb-1")
    if bugs:
        s.pay(small["id"], "cb-2")
        assert len(s.payments(small["id"])) == 2
    else:
        with pytest.raises(ValueError):
            s.pay(small["id"], "cb-2")
        assert len(s.payments(small["id"])) == 1
