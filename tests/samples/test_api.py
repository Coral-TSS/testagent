"""Real HTTP boundary for the synthetic system, never platform acceptance."""

import importlib

import pytest
from fastapi.testclient import TestClient


def client(tmp_path):
    try:
        module = importlib.import_module("examples.procurement.api")
    except ModuleNotFoundError:
        pytest.fail("Synthetic procurement HTTP application has not been implemented")
    return TestClient(module.create_app(tmp_path / "api.db"))


def test_rejected_payment_returns_conflict_and_keeps_empty_ledger(tmp_path):
    app = client(tmp_path)
    response = app.post("/sample/orders", json={"amount_minor": 5000000, "currency": "CNY"})
    assert response.status_code == 201
    order_id = response.json()["id"]
    assert app.post(f"/sample/orders/{order_id}/decision", json={"approved": False}).status_code == 200
    assert app.post(f"/sample/orders/{order_id}/payments", json={"callback_id": "c1"}).status_code == 409
    assert app.get(f"/sample/orders/{order_id}/payments").json() == []


def test_http_callback_replay_does_not_duplicate_payment(tmp_path):
    app = client(tmp_path)
    order = app.post("/sample/orders", json={"amount_minor": 5000000, "currency": "CNY"}).json()
    prefix = f"/sample/orders/{order['id']}"
    app.post(f"{prefix}/decision", json={"approved": True})
    first = app.post(f"{prefix}/payments", json={"callback_id": "c1"})
    assert first.status_code == 200
    assert app.post(f"{prefix}/payments", json={"callback_id": "c1"}).json() == first.json()
    assert len(app.get(f"{prefix}/payments").json()) == 1


@pytest.mark.parametrize("amount", [True, "5000000", -1])
def test_http_money_validation_does_not_coerce_inputs(tmp_path, amount):
    assert client(tmp_path).post("/sample/orders", json={"amount_minor": amount, "currency": "CNY"}).status_code == 422
