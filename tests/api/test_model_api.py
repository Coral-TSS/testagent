"""M1-03 ontology model and API registry."""

import pytest

from testagent.seed import seed_procurement
from testagent.services.model import ModelService

ZERO = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def sut(client):
    resp = client.post("/api/v1/suts", json={"code": "SHOP", "name": "Shop"})
    return resp.json()["id"]


def node(client, sut, kind, name, **extra):
    resp = client.post(f"/api/v1/suts/{sut}/nodes", json={"kind": kind, "name": name, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_relations_are_links_not_nodes(client, sut):
    """relation nodes are no longer created; relations are link types."""
    a, b = node(client, sut, "entity", "Order")["id"], node(client, sut, "entity", "Customer")["id"]
    url = f"/api/v1/suts/{sut}/nodes"
    rel = {"kind": "relation", "name": "Order-Customer", "source_node_id": a, "target_node_id": b}
    assert client.post(url, json=rel).status_code == 422
    bad = {"source_node_id": a, "target_node_id": b, "role": "source"}
    assert client.post(f"/api/v1/suts/{sut}/edges", json=bad).status_code == 422
    assert client.post(url, json={"kind": "entity", "name": "x", "source_node_id": a}).status_code == 422


def test_node_name_unique_per_kind_excluding_deleted(client, sut):
    first = node(client, sut, "entity", "Order")
    assert client.post(f"/api/v1/suts/{sut}/nodes", json={"kind": "entity", "name": "Order"}).status_code == 409
    node(client, sut, "action", "Order")  # same name, other kind is fine
    assert client.delete(f"/api/v1/nodes/{first['id']}").status_code == 200
    node(client, sut, "entity", "Order")  # name free again after soft delete


def test_attributes_schema(client, sut):
    attrs = {
        "conditions": [{"text": "Signed in"}],
        "states": [{"text": "draft"}, {"text": "paid"}],
        "constraints": [{"text": "Amount>0", "expr": "amount > 0"}],
    }
    created = node(client, sut, "entity", "Order", attributes=attrs, data_schema={"amount": "number"})
    assert created["attributes"] == attrs
    assert created["data_schema"] == {"amount": "number"}
    url = f"/api/v1/suts/{sut}/nodes"
    bad_key = client.post(url, json={"kind": "entity", "name": "x", "attributes": {"foo": []}})
    assert bad_key.status_code == 422
    assert bad_key.json()["field_errors"][0]["field"].startswith("attributes.")
    empty = client.post(url, json={"kind": "entity", "name": "y", "attributes": {"states": [{"text": ""}]}})
    assert empty.status_code == 422
    assert client.post(url, json={"kind": "state", "name": "z"}).status_code == 422
    patched = client.patch(
        f"/api/v1/nodes/{created['id']}", json={"attributes": {"states": [{"text": "closed"}]}}
    ).json()
    assert patched["attributes"] == {
        "conditions": [],
        "states": [{"text": "closed"}],
        "constraints": [],
    }
    assert client.patch(f"/api/v1/nodes/{created['id']}", json={"kind": "action"}).status_code == 422


def test_delete_lists_references_then_soft_deletes(client, sut, db):
    order = node(client, sut, "entity", "Order")
    customer = node(client, sut, "entity", "Customer")
    create = node(client, sut, "action", "Place order")
    client.post(
        f"/api/v1/suts/{sut}/links",
        json={
            "from_node_id": order["id"],
            "to_node_id": customer["id"],
            "forward_name": "belongs to",
            "reverse_name": "has",
        },
    )
    client.post(
        f"/api/v1/suts/{sut}/edges",
        json={"source_node_id": create["id"], "target_node_id": order["id"], "role": "object"},
    )
    refs = client.get(f"/api/v1/nodes/{order['id']}/references").json()
    assert sorted(r["role"] for r in refs) == ["link", "object"]
    blocked = client.delete(f"/api/v1/nodes/{order['id']}")
    assert blocked.status_code == 409 and len(blocked.json()["related"]) == 2
    assert client.get(f"/api/v1/nodes/{order['id']}").status_code == 200
    done = client.delete(f"/api/v1/nodes/{order['id']}", params={"confirm": "true"}).json()
    assert done["deleted"] is True and done["invalidated_edges"] == 1
    assert client.get(f"/api/v1/nodes/{order['id']}").status_code == 404
    with db.tx() as cur:
        cur.execute("SELECT deleted_at FROM model_node WHERE id=%s", (order["id"],))
        assert cur.fetchone()["deleted_at"] is not None  # row kept: soft delete
        cur.execute(
            "SELECT count(*) AS n FROM model_edge WHERE target_node_id=%s AND invalid_at IS NOT NULL",
            (order["id"],),
        )
        assert cur.fetchone()["n"] == 1
    graph = client.get(f"/api/v1/suts/{sut}/graph").json()
    assert "Order" not in {n["name"] for n in graph["nodes"]}
    touching = [e for e in graph["edges"] if order["id"] in (e["source_node_id"], e["target_node_id"])]
    assert touching == []
    assert graph["links"] == []  # the entity's links are archived with it


def test_graph_payload(client, sut):
    module = client.post(f"/api/v1/suts/{sut}/modules", json={"name": "Order domain"}).json()
    order = node(client, sut, "entity", "Order", module_id=module["id"])
    pay = node(client, sut, "action", "pays", module_id=module["id"])
    other = node(client, sut, "entity", "Log")
    client.post(
        f"/api/v1/suts/{sut}/edges",
        json={"source_node_id": pay["id"], "target_node_id": order["id"], "role": "object"},
    )
    client.post(
        f"/api/v1/suts/{sut}/edges",
        json={"source_node_id": pay["id"], "target_node_id": other["id"], "role": "ref"},
    )
    full = client.get(f"/api/v1/suts/{sut}/graph").json()
    assert len(full["nodes"]) == 3 and len(full["edges"]) == 2
    edge = full["edges"][0]
    assert set(edge) == {"id", "source_node_id", "target_node_id", "role"}
    scoped = client.get(f"/api/v1/suts/{sut}/graph", params={"module": module["id"]}).json()
    assert {n["name"] for n in scoped["nodes"]} == {"Order", "pays"}
    assert [e["role"] for e in scoped["edges"]] == ["object"]
    # list view and graph view come from the same data
    listed = client.get(f"/api/v1/suts/{sut}/nodes").json()
    assert {n["id"] for n in listed} == {n["id"] for n in full["nodes"]}
    assert client.get(f"/api/v1/suts/{ZERO}/graph").status_code == 404


def test_neighbors_depth_limit_and_cycle_safe(client, sut):
    names = ["A", "B", "C", "D", "E", "F", "G"]
    ids = {n: node(client, sut, "entity", n)["id"] for n in names}
    for a, b in zip(names, names[1:], strict=False):
        client.post(
            f"/api/v1/suts/{sut}/edges",
            json={"source_node_id": ids[a], "target_node_id": ids[b], "role": "ref"},
        )
    # close a cycle G -> A
    client.post(
        f"/api/v1/suts/{sut}/edges",
        json={"source_node_id": ids["G"], "target_node_id": ids["A"], "role": "ref"},
    )
    one = client.get(f"/api/v1/nodes/{ids['A']}/neighbors").json()
    assert {n["name"] for n in one} == {"B", "G"}
    two = client.get(f"/api/v1/nodes/{ids['A']}/neighbors", params={"depth": 2}).json()
    assert {(n["name"], n["depth"]) for n in two} == {("B", 1), ("G", 1), ("C", 2), ("F", 2)}
    five = client.get(f"/api/v1/nodes/{ids['A']}/neighbors", params={"depth": 5}).json()
    assert {n["name"] for n in five} == set(names) - {"A"}
    assert len(five) == len(names) - 1  # each node once despite the cycle
    assert client.get(f"/api/v1/nodes/{ids['A']}/neighbors", params={"depth": 6}).status_code == 422


def test_find_nodes_by_constraint_text(client, sut, db):
    node(client, sut, "entity", "Order", attributes={"constraints": [{"text": "Amount must be greater than 0"}]})
    node(client, sut, "entity", "Payments", attributes={"states": [{"text": "Amount locked"}]})
    node(client, sut, "entity", "Customer")
    url = f"/api/v1/suts/{sut}/nodes"
    by_constraint = client.get(url, params={"attr": "constraints", "attr_text": "Amount"}).json()
    assert [n["name"] for n in by_constraint] == ["Order"]
    any_attr = client.get(url, params={"attr_text": "Amount"}).json()
    assert {n["name"] for n in any_attr} == {"Order", "Payments"}
    assert [n["name"] for n in client.get(url, params={"q": "Cust"}).json()] == ["Customer"]
    assert client.get(url, params={"attr": "bogus", "attr_text": "x"}).status_code == 422
    exact = ModelService(db, client.app.state.bus).find_by_attribute(
        sut, "constraints", {"text": "Amount must be greater than 0"}
    )
    assert [n["name"] for n in exact] == ["Order"]


def test_api_unique_method_path(client, sut):
    url = f"/api/v1/suts/{sut}/apis"
    created = client.post(url, json={"method": "POST", "path": "/orders", "code_ref": "https://git.example/x.py#L10"})
    assert created.status_code == 201
    assert client.post(url, json={"method": "POST", "path": "/orders"}).status_code == 409
    assert client.post(url, json={"method": "GET", "path": "/orders"}).status_code == 201
    assert client.post(url, json={"method": "FETCH", "path": "/orders"}).status_code == 422
    assert client.post(url, json={"method": "GET", "path": "orders"}).status_code == 422
    api_id = created.json()["id"]
    patched = client.patch(f"/api/v1/apis/{api_id}", json={"code_ref": "src/orders.py:10"}).json()
    assert patched["code_ref"] == "src/orders.py:10"
    assert len(client.get(url).json()) == 2
    assert client.delete(f"/api/v1/apis/{api_id}").status_code == 204


def test_only_action_nodes_link_api(client, sut):
    api = client.post(
        f"/api/v1/suts/{sut}/apis", json={"method": "POST", "path": "/orders", "name": "Place order"}
    ).json()
    entity = node(client, sut, "entity", "Order")
    action = node(client, sut, "action", "Create purchase order")
    bad = client.put(f"/api/v1/nodes/{entity['id']}/apis", json={"api_ids": [api["id"]]})
    assert bad.status_code == 422
    ok = client.put(f"/api/v1/nodes/{action['id']}/apis", json={"api_ids": [api["id"]]})
    assert [a["path"] for a in ok.json()] == ["/orders"]
    detail = client.get(f"/api/v1/nodes/{action['id']}").json()
    assert [a["method"] + " " + a["path"] for a in detail["apis"]] == ["POST /orders"]
    listed = client.get(f"/api/v1/suts/{sut}/apis").json()
    assert listed[0]["node_names"] == ["Create purchase order"]
    missing = client.put(f"/api/v1/nodes/{action['id']}/apis", json={"api_ids": [ZERO]})
    assert missing.status_code == 404
    other = client.post("/api/v1/suts", json={"code": "OTHER", "name": "o"}).json()
    foreign = client.post(f"/api/v1/suts/{other['id']}/apis", json={"method": "GET", "path": "/x"}).json()
    cross = client.put(f"/api/v1/nodes/{action['id']}/apis", json={"api_ids": [foreign["id"]]})
    assert cross.status_code == 422
    assert client.put(f"/api/v1/nodes/{action['id']}/apis", json={"api_ids": []}).json() == []


def test_module_must_belong_to_same_sut(client, sut):
    other = client.post("/api/v1/suts", json={"code": "OTHER", "name": "o"}).json()
    module = client.post(f"/api/v1/suts/{other['id']}/modules", json={"name": "m"}).json()
    resp = client.post(f"/api/v1/suts/{sut}/nodes", json={"kind": "entity", "name": "x", "module_id": module["id"]})
    assert resp.status_code == 422


def test_snapshot_is_deterministic_and_immutable(client, sut, db):
    node(client, sut, "entity", "Order", attributes={"states": [{"text": "draft"}]})
    service = ModelService(db, client.app.state.bus)
    first = service.create_snapshot(sut)
    second = service.create_snapshot(sut)
    assert first["digest"] == second["digest"]
    node(client, sut, "entity", "Customer")
    assert service.create_snapshot(sut)["digest"] != first["digest"]
    with db.tx() as cur:
        cur.execute("SELECT content FROM model_snapshot WHERE id=%s", (first["id"],))
        content = cur.fetchone()["content"]
    assert [n["name"] for n in content["nodes"]] == ["Order"]


def test_seed_procurement(db):
    result = seed_procurement(db)
    assert result["created"] is True and result["nodes"] >= 8 and result["links"] == 2
    assert seed_procurement(db)["created"] is False  # idempotent
    with db.tx() as cur:
        cur.execute("SELECT kind, count(*) AS n FROM model_node GROUP BY kind")
        counts = {r["kind"]: r["n"] for r in cur.fetchall()}
        cur.execute("SELECT count(*) AS n FROM api_endpoint")
        apis = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM person")
        people = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM node_api_link")
        links = cur.fetchone()["n"]
        cur.execute("SELECT forward_name, reverse_name FROM model_link ORDER BY forward_name")
        link_names = [(r["forward_name"], r["reverse_name"]) for r in cur.fetchall()]
    assert sum(counts.values()) >= 8 and "relation" not in counts
    assert sorted(link_names) == sorted([("belongs to", "supplies"), ("pays", "receives")])
    assert apis == 4 and people == 4 and links == 4


def test_seed_procurement_with_external_demo_url(db):
    """Docker: the demo SUT runs in its own container, so the environment has no start command."""
    seed_procurement(db, demo_url="http://demo:8766")
    with db.tx() as cur:
        cur.execute("SELECT base_url, start_command FROM environment")
        env = cur.fetchone()
    assert env["base_url"] == "http://demo:8766" and env["start_command"] is None
