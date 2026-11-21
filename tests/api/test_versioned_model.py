"""A version owns its model. Editing one version does not change another; a new version copies."""

V1 = "/api/v1"


def _sut(client, code="SHOP"):
    return client.post(f"{V1}/suts", json={"code": code, "name": "Shop"}).json()["id"]


def _version(client, sut, name, source=None):
    body = {"name": name}
    if source:
        body["source_version_id"] = source
    resp = client.post(f"{V1}/suts/{sut}/versions", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _node(client, sut, name, kind="entity", version=None):
    params = {"version_id": version} if version else None
    resp = client.post(f"{V1}/suts/{sut}/nodes", params=params, json={"kind": kind, "name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_versions_do_not_share_a_model(client):
    sut = _sut(client)
    v1 = _version(client, sut, "v1")
    order = _node(client, sut, "PurchaseOrder", version=v1)
    client.post(
        f"{V1}/nodes/{order['id']}/fields",
        json={"name": "code", "data_type": "string", "required": True},
    )
    v2 = _version(client, sut, "v2")
    renamed = client.patch(f"{V1}/nodes/{order['id']}", json={"description": "v1 only"}).json()
    assert renamed["description"] == "v1 only"

    v2_nodes = client.get(f"{V1}/suts/{sut}/nodes", params={"version_id": v2}).json()
    copied = next(n for n in v2_nodes if n["name"] == "PurchaseOrder")
    assert copied["id"] != order["id"]
    assert copied["description"] in (None, "")
    v2_fields = client.get(f"{V1}/suts/{sut}/fields", params={"version_id": v2}).json()
    assert any(f["name"] == "code" and f["node_id"] == copied["id"] for f in v2_fields)

    client.patch(f"{V1}/nodes/{copied['id']}", json={"name": "QualityInspection"})
    v1_nodes = {n["name"] for n in client.get(f"{V1}/suts/{sut}/nodes", params={"version_id": v1}).json()}
    v2_names = {n["name"] for n in client.get(f"{V1}/suts/{sut}/nodes", params={"version_id": v2}).json()}
    assert "PurchaseOrder" in v1_nodes and "QualityInspection" not in v1_nodes
    assert "QualityInspection" in v2_names and "PurchaseOrder" not in v2_names


def test_first_version_starts_empty_and_copies_the_chosen_source(client):
    sut = _sut(client, "ALT")
    v1 = _version(client, sut, "v1")
    assert client.get(f"{V1}/suts/{sut}/nodes", params={"version_id": v1}).json() == []
    _node(client, sut, "Material", version=v1)
    _node(client, sut, "Supplier", version=v1)
    v2 = _version(client, sut, "v2")
    _node(client, sut, "QualityInspection", version=v2)
    older = _version(client, sut, "v1-copy", source=v1)
    names = {n["name"] for n in client.get(f"{V1}/suts/{sut}/nodes", params={"version_id": older}).json()}
    assert names == {"Material", "Supplier"}
    assert "QualityInspection" not in names


def test_links_and_rules_are_copied_with_new_ids(client):
    sut = _sut(client, "RULE")
    v1 = _version(client, sut, "v1")
    order = _node(client, sut, "PurchaseOrder", version=v1)
    supplier = _node(client, sut, "Supplier", version=v1)
    field = client.post(
        f"{V1}/nodes/{order['id']}/fields",
        json={"name": "status", "data_type": "enum", "enum_values": ["draft", "issued"], "required": True},
    ).json()
    link = client.post(
        f"{V1}/suts/{sut}/links",
        json={
            "from_node_id": order["id"],
            "to_node_id": supplier["id"],
            "forward_name": "向其采购",
            "reverse_name": "接受订单",
            "cardinality": "many_to_one",
            "fk_attribute_id": field["id"],
        },
    )
    assert link.status_code == 201, link.text
    action = _node(client, sut, "下达采购订单", kind="action", version=v1)
    patched = client.patch(
        f"{V1}/nodes/{action['id']}",
        json={
            "preconditions": [{"field": "PurchaseOrder.status", "op": "eq", "value": "draft"}],
            "effects": [{"kind": "set_field", "field": "PurchaseOrder.status", "values": ["issued"]}],
        },
    )
    assert patched.status_code == 200, patched.text
    v2 = _version(client, sut, "v2")
    graph = client.get(f"{V1}/suts/{sut}/graph", params={"version_id": v2}).json()
    assert {n["name"] for n in graph["nodes"]} == {"PurchaseOrder", "Supplier", "下达采购订单"}
    assert len(graph["links"]) == 1
    assert graph["links"][0]["id"] != link.json()["id"]
    copied_action = next(n for n in graph["nodes"] if n["kind"] == "action")
    detail = client.get(f"{V1}/nodes/{copied_action['id']}").json()
    assert detail["preconditions"][0]["value"] == "draft"
    assert detail["preconditions"][0]["attribute_id"] != field["id"]
    v1_detail = client.get(f"{V1}/nodes/{action['id']}").json()
    assert v1_detail["preconditions"][0]["attribute_id"] == field["id"]
