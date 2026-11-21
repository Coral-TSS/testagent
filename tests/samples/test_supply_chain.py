"""供应链执行演示：主链路、质检、还原可重复。"""

from fastapi.testclient import TestClient

from examples.supply_chain.api import create_app


def client(tmp_path):
    return TestClient(create_app(tmp_path / "supply.db"))


def ids(app):
    materials = {m["code"]: m for m in app.get("/sample/materials").json()}
    suppliers = {s["code"]: s for s in app.get("/sample/suppliers").json()}
    buyers = {b["code"]: b for b in app.get("/sample/buyers").json()}
    warehouses = {w["code"]: w for w in app.get("/sample/warehouses").json()}
    return materials, suppliers, buyers, warehouses


def test_v1_style_receipt_posts_without_inspection(tmp_path):
    app = client(tmp_path)
    materials, suppliers, buyers, warehouses = ids(app)
    req = app.post(
        "/sample/requisitions",
        json={
            "materialId": materials["MAT-STD"]["id"],
            "qty": 2,
            "buyerId": buyers["BUY-01"]["id"],
            "supplierId": suppliers["SUP-OK"]["id"],
        },
    )
    assert req.status_code == 201 and req.json()["status"] == "draft"
    req_id = req.json()["id"]
    assert (
        app.post(f"/sample/requisitions/{req_id}/submit", json={"buyerId": buyers["BUY-01"]["id"]}).json()["status"]
        == "submitted"
    )
    denied = app.post(
        f"/sample/requisitions/{req_id}/decision", json={"approverId": buyers["BUY-01"]["id"], "approved": True}
    )
    assert denied.status_code == 422
    assert (
        app.post(
            f"/sample/requisitions/{req_id}/decision", json={"approverId": buyers["BUY-02"]["id"], "approved": True}
        ).json()["status"]
        == "approved"
    )
    order = app.post(
        "/sample/orders",
        json={"requisitionId": req_id, "buyerId": buyers["BUY-01"]["id"], "currency": "CNY"},
    ).json()
    assert order["status"] == "draft" and order["amount"] == 25.0
    order = app.post(f"/sample/orders/{order['id']}/submit", json={"buyerId": buyers["BUY-01"]["id"]}).json()
    order = app.post(
        f"/sample/orders/{order['id']}/decision", json={"approverId": buyers["BUY-02"]["id"], "approved": True}
    ).json()
    order = app.post(f"/sample/orders/{order['id']}/issue").json()
    assert order["status"] == "issued"
    receipt = app.post(
        f"/sample/orders/{order['id']}/receive",
        json={"lineId": order["lines"][0]["id"], "warehouseId": warehouses["WH-01"]["id"], "receivedQty": 2},
    ).json()
    posted = app.post(f"/sample/receipts/{receipt['id']}/post")
    assert posted.status_code == 200 and posted.json()["status"] == "posted"
    stock = app.get("/sample/inventory").json()
    std = next(row for row in stock if row["materialCode"] == "MAT-STD")
    assert std["onHandQty"] == 10


def test_v2_inspection_blocks_post_until_passed(tmp_path):
    app = client(tmp_path)
    materials, suppliers, buyers, warehouses = ids(app)
    req = app.post(
        "/sample/requisitions",
        json={
            "materialId": materials["MAT-QC"]["id"],
            "qty": 2,
            "buyerId": buyers["BUY-01"]["id"],
            "supplierId": suppliers["SUP-OK"]["id"],
        },
    ).json()
    app.post(f"/sample/requisitions/{req['id']}/submit", json={"buyerId": buyers["BUY-01"]["id"]})
    app.post(
        f"/sample/requisitions/{req['id']}/decision", json={"approverId": buyers["BUY-02"]["id"], "approved": True}
    )
    order = app.post(
        "/sample/orders",
        json={
            "requisitionId": req["id"],
            "buyerId": buyers["BUY-01"]["id"],
            "currency": "CNY",
            "overReceiveTolerancePct": 0.1,
        },
    ).json()
    app.post(f"/sample/orders/{order['id']}/submit", json={"buyerId": buyers["BUY-01"]["id"]})
    app.post(f"/sample/orders/{order['id']}/decision", json={"approverId": buyers["BUY-02"]["id"], "approved": True})
    app.post(f"/sample/orders/{order['id']}/issue")
    receipt = app.post(
        f"/sample/orders/{order['id']}/receive",
        json={"lineId": order["lines"][0]["id"], "warehouseId": warehouses["WH-01"]["id"], "receivedQty": 2},
    ).json()
    blocked = app.post(f"/sample/receipts/{receipt['id']}/post")
    assert blocked.status_code == 422
    inspection = app.post(f"/sample/receipts/{receipt['id']}/inspections").json()
    assert inspection["result"] == "pending"
    app.post(f"/sample/inspections/{inspection['id']}/decision", json={"passed": False, "defectQty": 1})
    assert app.post(f"/sample/receipts/{receipt['id']}/post").status_code == 422
    app.post("/sample/reset")
    assert app.get("/sample/requisitions").json() == []


def test_potential_supplier_cannot_be_issued(tmp_path):
    app = client(tmp_path)
    materials, suppliers, buyers, _wh = ids(app)
    req = app.post(
        "/sample/requisitions",
        json={
            "materialId": materials["MAT-STD"]["id"],
            "qty": 1,
            "buyerId": buyers["BUY-01"]["id"],
            "supplierId": suppliers["SUP-NEW"]["id"],
        },
    ).json()
    app.post(f"/sample/requisitions/{req['id']}/submit", json={"buyerId": buyers["BUY-01"]["id"]})
    app.post(
        f"/sample/requisitions/{req['id']}/decision", json={"approverId": buyers["BUY-02"]["id"], "approved": True}
    )
    created = app.post(
        "/sample/orders", json={"requisitionId": req["id"], "buyerId": buyers["BUY-01"]["id"], "currency": "CNY"}
    )
    assert created.status_code == 422


def test_spaces_are_isolated(tmp_path):
    app = client(tmp_path)
    materials = {m["code"]: m for m in app.get("/sample/spaces/run-a/materials").json()}
    buyers = {b["code"]: b for b in app.get("/sample/spaces/run-a/buyers").json()}
    body = {"materialId": materials["MAT-STD"]["id"], "qty": 1, "buyerId": buyers["BUY-01"]["id"]}
    assert app.post("/sample/spaces/run-a/requisitions", json=body).status_code == 201
    assert app.get("/sample/spaces/run-b/requisitions").json() == []
    assert app.post("/sample/spaces/run-a/reset").json()["reset"] is True
    assert app.get("/sample/spaces/run-a/requisitions").json() == []
    assert len(app.get("/sample/materials").json()) == 3
