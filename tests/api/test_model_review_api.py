"""read-only model review with coverage, review marks and Markdown."""

from __future__ import annotations

from tests.api.world import V1, build_world, make_case


def setup_model(client, w):
    sut = w["sut"]

    def node(kind, name, **extra):
        resp = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": kind, "name": name, **extra})
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    order, pay = node("entity", "Order"), node("entity", "Pay")
    submit = node("action", "Submit order", description="Submit an order")
    state = client.post(
        f"{V1}/nodes/{order}/fields",
        json={
            "name": "state",
            "data_type": "enum",
            "enum_values": ["new", "paid"],
            "required": True,
        },
    ).json()["id"]
    order_id = client.post(
        f"{V1}/nodes/{pay}/fields",
        json={"name": "order_id", "data_type": "reference", "ref_node_id": order},
    ).json()["id"]
    link = client.post(
        f"{V1}/suts/{sut}/links",
        json={
            "from_node_id": pay,
            "to_node_id": order,
            "forward_name": "pays",
            "reverse_name": "receives",
            "cardinality": "many_to_one",
        },
    ).json()["id"]
    client.patch(
        f"{V1}/nodes/{submit}",
        json={"effects": [{"kind": "set_field", "field": "Order.state", "values": ["new"]}]},
    )
    return {
        "order": order,
        "pay": pay,
        "submit": submit,
        "state": state,
        "fk": order_id,
        "link": link,
    }


def test_review_lists_model_with_coverage_and_marks(client, db):
    w = build_world(client, db)
    m = setup_model(client, w)
    make_case(client, w, "Order submitted", node_ids=[m["submit"]])
    review = client.get(f"{V1}/suts/{w['sut']}/model-review").json()

    assert review["sut"]["code"] == "SHOP"
    ents = {e["name"]: e for e in review["entities"]}
    state = next(f for f in ents["Order"]["fields"] if f["name"] == "state")
    assert (state["data_type"], state["required"], state["enum_values"]) == (
        "enum",
        True,
        ["new", "paid"],
    )
    assert ents["Order"]["relations"] == ["Order receives Pay (1:N, foreign key Pay.order_id)"]
    assert ents["Order"]["uncovered"] is True  # no requirement or case touches it

    link = review["links"][0]
    assert link["forward"] == "Pay pays Order" and link["reverse"] == "Order receives Pay"
    assert link["cardinality"] == "N:1" and link["fk_field"] == "Pay.order_id"

    action = review["actions"][0]
    assert action["name"] == "Submit order" and action["description"] == "Submit an order"
    assert action["effects"] == ["Order.state → new"]
    assert [c["code"] for c in action["coverage"]["cases"]] == ["TC-001"]
    assert action["uncovered"] is False
    assert review["summary"]["total"] == 4  # 2 entities + 1 link + 1 action
    assert review["summary"]["reviewed"] == 0 and review["summary"]["uncovered"] == 3

    # per-element marks (UI aid, not acceptance)
    resp = client.put(
        f"{V1}/suts/{w['sut']}/model-review/marks",
        json={
            "target_type": "entity",
            "target_id": m["order"],
            "reviewed": True,
            "note": "All fields present",
        },
    )
    assert resp.status_code == 200, resp.text
    review = client.get(f"{V1}/suts/{w['sut']}/model-review").json()
    order = next(e for e in review["entities"] if e["name"] == "Order")
    assert order["mark"]["reviewed"] and not order["mark"]["stale"] and order["mark"]["note"] == "All fields present"
    assert review["summary"]["reviewed"] == 1

    # changing the element after review marks it stale
    client.post(f"{V1}/nodes/{m['order']}/fields", json={"name": "amount", "data_type": "money"})
    order = next(e for e in client.get(f"{V1}/suts/{w['sut']}/model-review").json()["entities"] if e["name"] == "Order")
    assert order["mark"]["stale"] is True
    review = client.get(f"{V1}/suts/{w['sut']}/model-review").json()
    assert review["summary"]["reviewed"] == 0 and review["summary"]["stale"] == 1

    # unmark; foreign ids are rejected
    client.put(
        f"{V1}/suts/{w['sut']}/model-review/marks",
        json={"target_type": "entity", "target_id": m["order"], "reviewed": False},
    )
    order = next(e for e in client.get(f"{V1}/suts/{w['sut']}/model-review").json()["entities"] if e["name"] == "Order")
    assert order["mark"]["reviewed"] is False
    bad = client.put(
        f"{V1}/suts/{w['sut']}/model-review/marks",
        json={"target_type": "link", "target_id": m["order"], "reviewed": True},
    )
    assert bad.status_code == 404


def test_review_markdown_export(client, db):
    w = build_world(client, db)
    setup_model(client, w)
    resp = client.get(f"{V1}/suts/{w['sut']}/model-review.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    text = resp.text
    assert text.startswith("# Model review: Shop (SHOP)")
    assert "## Entities" in text and "| state | enum (new / paid) | yes |" in text
    assert "- [ ] Pay pays Order / Order receives Pay (N:1, foreign key Pay.order_id)" in text
    assert "Effects: Order.state → new" in text
    assert "Not covered" in text
