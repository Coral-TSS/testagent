"""M1-01 CRUD APIs for persons, SUTs, environments, modules."""


def _sut(client, code="SHOP"):
    resp = client.post("/api/v1/suts", json={"code": code, "name": "Shop"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_sut_crud(client, db):
    sut = _sut(client)
    assert client.get(f"/api/v1/suts/{sut['id']}").json()["code"] == "SHOP"
    assert [s["code"] for s in client.get("/api/v1/suts").json()] == ["SHOP"]
    patched = client.patch(f"/api/v1/suts/{sut['id']}", json={"description": "d"}).json()
    assert patched["description"] == "d"
    assert client.delete(f"/api/v1/suts/{sut['id']}").status_code == 204
    assert client.get(f"/api/v1/suts/{sut['id']}").status_code == 404
    with db.tx() as cur:
        cur.execute("SELECT action FROM change_log WHERE entity='sut' ORDER BY id")
        assert [r["action"] for r in cur.fetchall()] == ["create", "update", "delete"]


def test_sut_validation_and_conflict(client):
    bad = client.post("/api/v1/suts", json={"code": "1x", "name": ""})
    assert bad.status_code == 422
    body = bad.json()
    assert body["code"] == "VALIDATION"
    assert {f["field"] for f in body["field_errors"]} == {"code", "name"}
    _sut(client)
    dup = client.post("/api/v1/suts", json={"code": "SHOP", "name": "x"})
    assert dup.status_code == 409 and dup.json()["code"] == "CONFLICT"
    assert client.post("/api/v1/suts", json={"code": "A", "name": "a", "x": 1}).status_code == 422


def test_unknown_id_404(client):
    resp = client.get("/api/v1/suts/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404 and resp.json()["code"] == "NOT_FOUND"
    assert client.get("/api/v1/suts/not-a-uuid").status_code == 422


def test_environment_crud(client):
    sut = _sut(client)
    url = f"/api/v1/suts/{sut['id']}/environments"
    env = client.post(url, json={"name": "test", "base_url": "http://localhost:3000"})
    assert env.status_code == 201
    assert client.post(url, json={"name": "x", "base_url": "ftp://a"}).status_code == 422
    assert client.post(url, json={"name": "test", "base_url": "http://b"}).status_code == 409
    env_id = env.json()["id"]
    resp = client.patch(f"/api/v1/environments/{env_id}", json={"base_url": "https://b.example"})
    assert resp.json()["base_url"] == "https://b.example"
    assert len(client.get(url).json()) == 1
    assert client.delete(f"/api/v1/environments/{env_id}").status_code == 204
    assert client.get(url).json() == []
    missing = "/api/v1/suts/00000000-0000-0000-0000-000000000000/environments"
    assert client.post(missing, json={"name": "e", "base_url": "http://x"}).status_code == 404


def test_module_crud_has_no_owner(client):
    sut = _sut(client)
    url = f"/api/v1/suts/{sut['id']}/modules"
    mod = client.post(url, json={"name": "Order"}).json()
    assert "owner_id" not in mod
    assert client.post(url, json={"name": "x", "owner_id": "p"}).status_code == 422
    assert client.patch(f"/api/v1/modules/{mod['id']}", json={"name": "Order center"}).status_code == 200
    assert [m["name"] for m in client.get(url).json()] == ["Order center"]
    assert client.delete(f"/api/v1/modules/{mod['id']}").status_code == 204


def test_person_deactivate_not_delete(client):
    person = client.post("/api/v1/persons", json={"name": "Sam Lee", "title": "Development"}).json()
    assert person["active"] is True
    resp = client.post(f"/api/v1/persons/{person['id']}/deactivate")
    assert resp.json()["active"] is False
    assert client.get(f"/api/v1/persons/{person['id']}").status_code == 200
    assert client.get("/api/v1/persons", params={"active": "true"}).json() == []
    assert len(client.get("/api/v1/persons").json()) == 1
    assert client.delete(f"/api/v1/persons/{person['id']}").status_code == 405


def test_sut_delete_blocked_when_referenced(client, db):
    sut = _sut(client)
    with db.tx() as cur:
        cur.execute("INSERT INTO model_node(sut_id, kind, name) VALUES (%s,'entity','Order')", (sut["id"],))
    resp = client.delete(f"/api/v1/suts/{sut['id']}")
    assert resp.status_code == 409 and resp.json()["code"] == "CONFLICT"


def test_events_published_on_create(client):
    seen = []
    client.app.state.bus.subscribe("sut.created", lambda e, p: seen.append(p["id"]))
    sut = _sut(client)
    assert seen == [sut["id"]]
