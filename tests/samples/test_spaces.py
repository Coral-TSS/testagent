"""Namespace isolation and explicit synthetic-data reset for repeatable local runs."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from examples.procurement.api import create_app


def test_orders_and_ledger_are_isolated_between_spaces(tmp_path):
    app = TestClient(create_app(tmp_path / "sample.db"))
    a = "/sample/spaces/run-a/orders"
    b = "/sample/spaces/run-b/orders"
    created = app.post(a, json={"amount_minor": 5000000, "currency": "CNY"})
    assert created.status_code == 201
    order_id = created.json()["id"]
    assert app.get(b).json() == []
    assert app.get(f"{b}/{order_id}").status_code == 404
    assert app.post(f"{b}/{order_id}/decision", json={"approved": True}).status_code == 409
    assert len(app.get(a).json()) == 1


def test_reset_requires_matching_space_and_does_not_reset_other_spaces(tmp_path):
    app = TestClient(create_app(tmp_path / "sample.db"))
    base = "/sample/spaces/run-a"
    order = app.post(f"{base}/orders", json={"amount_minor": 5000000, "currency": "CNY"})
    assert order.status_code == 201
    order_id = order.json()["id"]
    app.post(f"{base}/orders/{order_id}/decision", json={"approved": True})
    app.post(f"{base}/orders/{order_id}/payments", json={"callback_id": "callback-1"})
    other = app.post("/sample/spaces/run-b/orders", json={"amount_minor": 5000000, "currency": "CNY"})
    assert other.status_code == 201
    assert app.post(f"{base}/reset", json={"confirm_space": "run-b"}).status_code == 409
    assert len(app.get(f"{base}/orders").json()) == 1
    assert app.post(f"{base}/reset", json={"confirm_space": "run-a"}).json() == {
        "space": "run-a",
        "reset": True,
    }
    assert app.get(f"{base}/orders").json() == []
    assert app.get(f"{base}/orders/{order_id}").status_code == 404
    assert app.get(f"{base}/orders/{order_id}/payments").json() == []
    assert len(app.get("/sample/spaces/run-b/orders").json()) == 1


@pytest.mark.parametrize("space", ["bad.name", "中文", "a" * 65, "CON"])
def test_unsafe_space_names_rejected_before_access(tmp_path, space):
    app = TestClient(create_app(tmp_path / "sample.db"))
    assert app.get(f"/sample/spaces/{space}/orders").status_code == 422


def test_space_survives_application_restart(tmp_path):
    database = tmp_path / "sample.db"
    app = TestClient(create_app(database))
    url = "/sample/spaces/run-a/orders"
    created = app.post(url, json={"amount_minor": 5000001, "currency": "CNY"})
    assert created.status_code == 201
    restarted = TestClient(create_app(database))
    assert restarted.get(url).json()[0]["id"] == created.json()["id"]
    assert restarted.get(url).json()[0]["approval_required"] is True


def test_concurrent_callbacks_commit_only_one_ledger_entry(tmp_path):
    from examples.procurement.service import ProcurementService

    sample = ProcurementService(tmp_path / "concurrent.db")
    order = sample.create_order(5000000, "CNY")
    sample.decide(order["id"], approved=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: sample.pay(order["id"], "same"), range(4)))
    assert len({x["id"] for x in results}) == 1
    assert len(sample.payments(order["id"])) == 1
