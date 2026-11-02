"""M1-05 versions, requirements, responsible people, AI structuring/completion, freeze."""

import pytest
from langchain_core.messages import AIMessage

from testagent.agent.fake import FakeChatModel, call
from testagent.core.errors import AppError
from testagent.services.requirements import RequirementService
from testagent.services.versions import VersionService

V1 = "/api/v1"


@pytest.fixture
def world(client):
    sut = client.post(f"{V1}/suts", json={"code": "SHOP", "name": "Shop"}).json()["id"]
    version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1.0"}).json()["id"]
    people = {
        name: client.post(f"{V1}/persons", json={"name": name}).json()["id"]
        for name in ("Pat Product", "Devin Dev", "Tess Tester")
    }
    order = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": "entity", "name": "PurchaseOrder"}).json()["id"]
    create = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": "action", "name": "Create purchase order"}).json()[
        "id"
    ]
    return {"sut": sut, "version": version, "people": people, "order": order, "create": create}


def new_req(client, world, title="Create purchase order", **extra):
    resp = client.post(f"{V1}/versions/{world['version']}/requirements", json={"title": title, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


def staff(client, world, req_id, owner=True):
    p = world["people"]
    body = [
        {"person_id": p["Devin Dev"], "role": "developer"},
        {"person_id": p["Tess Tester"], "role": "tester"},
    ]
    if owner:
        body.append({"person_id": p["Pat Product"], "role": "owner"})
    resp = client.put(f"{V1}/requirements/{req_id}/people", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def structure(client, world, req_id):
    resp = client.put(
        f"{V1}/requirements/{req_id}/structure",
        json={
            "actor": [{"text": "Buyer"}],
            "action": [{"text": "Create purchase order", "node_id": world["create"]}],
            "result": [{"text": "Purchase order is a draft", "node_id": world["order"]}],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def ready_req(client, world, title="Create purchase order"):
    req = new_req(client, world, title)
    staff(client, world, req["id"])
    structure(client, world, req["id"])
    assert client.post(f"{V1}/requirements/{req['id']}/confirm").status_code == 200
    return req


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


# ------------------------------------------------------------------ versions
def test_version_transitions(client, world):
    vid = world["version"]
    assert client.get(f"{V1}/versions/{vid}").json()["status"] == "planning"
    bad = client.post(f"{V1}/versions/{vid}/status", json={"status": "closed"})
    assert bad.status_code == 409 and bad.json()["code"] == "INVALID_TRANSITION"
    ready_req(client, world)
    assert client.post(f"{V1}/versions/{vid}/freeze").json()["status"] == "requirements_frozen"
    assert client.post(f"{V1}/versions/{vid}/freeze").status_code == 409
    assert client.post(f"{V1}/versions/{vid}/status", json={"status": "testing"}).status_code == 200
    assert client.post(f"{V1}/versions/{vid}/status", json={"status": "closed"}).status_code == 200
    assert client.post(f"{V1}/versions/{vid}/unfreeze", json={"reason": "x"}).status_code == 409
    listed = client.get(f"{V1}/suts/{world['sut']}/versions").json()
    assert listed[0]["requirement_count"] == 1 and listed[0]["status"] == "closed"


def test_unfreeze_requires_reason(client, world):
    vid = world["version"]
    ready_req(client, world)
    client.post(f"{V1}/versions/{vid}/freeze")
    no_reason = client.post(f"{V1}/versions/{vid}/unfreeze", json={"reason": "  "})
    assert no_reason.status_code == 422
    assert no_reason.json()["field_errors"][0]["field"] == "reason"
    ok = client.post(f"{V1}/versions/{vid}/unfreeze", json={"reason": "Customer adds a requirement"})
    assert ok.json()["status"] == "planning" and ok.json()["model_snapshot_id"] is None
    history = client.get(f"{V1}/versions/{vid}/history").json()
    assert [h["action"] for h in history] == ["create", "freeze", "unfreeze"]
    assert history[-1]["diff"]["reason"] == "Customer adds a requirement"


# ------------------------------------------------------------------ requirements
def test_requirement_code_sequence(client, world):
    assert new_req(client, world, "a")["code"] == "REQ-001"
    assert new_req(client, world, "b")["code"] == "REQ-002"
    custom = new_req(client, world, "c", code="REQ-010")
    assert custom["code"] == "REQ-010"
    assert new_req(client, world, "d")["code"] == "REQ-011"
    dup = client.post(f"{V1}/versions/{world['version']}/requirements", json={"title": "e", "code": "REQ-001"})
    assert dup.status_code == 409
    other = client.post(f"{V1}/suts/{world['sut']}/versions", json={"name": "v2"}).json()
    resp = client.post(f"{V1}/versions/{other['id']}/requirements", json={"title": "x"})
    assert resp.json()["code"] == "REQ-001"  # unique per version


def test_requirement_locked_after_freeze(client, world):
    req = ready_req(client, world)
    vid = world["version"]
    client.post(f"{V1}/versions/{vid}/freeze")
    rid = req["id"]
    for resp in (
        client.patch(f"{V1}/requirements/{rid}", json={"title": "edit"}),
        client.put(f"{V1}/requirements/{rid}/people", json=[]),
        client.put(f"{V1}/requirements/{rid}/structure", json={}),
        client.delete(f"{V1}/requirements/{rid}"),
        client.post(f"{V1}/versions/{vid}/requirements", json={"title": "new"}),
        client.post(f"{V1}/requirements/{rid}/structure"),
    ):
        assert resp.status_code == 409, resp.text
    client.post(f"{V1}/versions/{vid}/unfreeze", json={"reason": "Edit requirement"})
    edited = client.patch(f"{V1}/requirements/{rid}", json={"title": "edit"}).json()
    assert edited["title"] == "edit" and edited["status"] == "structured"  # needs re-confirmation


def test_set_requirement_people_roles(client, world):
    req = new_req(client, world)
    p = world["people"]
    body = [
        {"person_id": p["Pat Product"], "role": "owner"},
        {"person_id": p["Devin Dev"], "role": "developer"},
        {"person_id": p["Tess Tester"], "role": "developer"},
        {"person_id": p["Tess Tester"], "role": "tester"},
    ]
    detail = client.put(f"{V1}/requirements/{req['id']}/people", json=body).json()
    roles = sorted((x["name"], x["role"]) for x in detail["people"])
    assert roles == [
        ("Devin Dev", "developer"),
        ("Pat Product", "owner"),
        ("Tess Tester", "developer"),
        ("Tess Tester", "tester"),
    ]
    bad = [{"person_id": p["Pat Product"], "role": "boss"}]
    assert client.put(f"{V1}/requirements/{req['id']}/people", json=bad).status_code == 422
    zero = [{"person_id": "00000000-0000-0000-0000-000000000000", "role": "owner"}]
    assert client.put(f"{V1}/requirements/{req['id']}/people", json=zero).status_code == 404
    listed = client.get(f"{V1}/versions/{world['version']}/requirements").json()
    assert len(listed[0]["people"]) == 4


def test_confirm_requires_owner(client, world):
    req = new_req(client, world)
    draft = client.post(f"{V1}/requirements/{req['id']}/confirm")
    assert draft.status_code == 409  # draft → confirmed is not a legal transition
    structure(client, world, req["id"])
    staff(client, world, req["id"], owner=False)
    no_owner = client.post(f"{V1}/requirements/{req['id']}/confirm")
    assert no_owner.status_code == 422 and "owner" in no_owner.json()["message"]
    staff(client, world, req["id"])
    ok = client.post(f"{V1}/requirements/{req['id']}/confirm").json()
    assert ok["status"] == "confirmed" and ok["confirmed_by"] == "local-user"


def test_inactive_person_rejected(client, world):
    req = new_req(client, world)
    p = world["people"]
    staff(client, world, req["id"])
    client.post(f"{V1}/persons/{p['Devin Dev']}/deactivate")
    # already attached inactive person may stay
    keep = [
        {"person_id": p["Pat Product"], "role": "owner"},
        {"person_id": p["Devin Dev"], "role": "developer"},
    ]
    assert client.put(f"{V1}/requirements/{req['id']}/people", json=keep).status_code == 200
    other = new_req(client, world, "Another requirement")
    resp = client.put(
        f"{V1}/requirements/{other['id']}/people",
        json=[{"person_id": p["Devin Dev"], "role": "developer"}],
    )
    assert resp.status_code == 422 and resp.json()["related"] == ["Devin Dev"]


def test_person_requirements_listing(client, world):
    a = new_req(client, world, "A")
    b = new_req(client, world, "B")
    p = world["people"]
    client.put(
        f"{V1}/requirements/{a['id']}/people",
        json=[
            {"person_id": p["Tess Tester"], "role": "tester"},
            {"person_id": p["Tess Tester"], "role": "owner"},
        ],
    )
    client.put(f"{V1}/requirements/{b['id']}/people", json=[{"person_id": p["Tess Tester"], "role": "tester"}])
    rows = client.get(f"{V1}/persons/{p['Tess Tester']}/requirements").json()
    assert [(r["code"], r["roles"]) for r in rows] == [
        ("REQ-001", ["owner", "tester"]),
        ("REQ-002", ["tester"]),
    ]
    assert rows[0]["sut_code"] == "SHOP" and rows[0]["version_name"] == "v1.0"


# ------------------------------------------------------------------ AI structuring
def test_structure_links_existing_nodes(client, world, db):
    req = new_req(client, world, raw_text="The buyer creates a purchase order; the amount must be greater than 0")
    fake = use_model(
        client,
        call("search_nodes", {"sut_id": world["sut"], "query": "Procurement"}),
        call(
            "submit_result",
            {
                "items": [
                    {"part": "action", "text": "Create purchase order", "node_id": world["create"]},
                    {"part": "result", "text": "Generate purchase order", "node_id": world["order"]},
                ]
            },
        ),
    )
    out = client.post(f"{V1}/requirements/{req['id']}/structure").json()
    assert out["status"] == "succeeded"
    detail = out["requirement"]
    assert detail["status"] == "structured" and detail["agent_run_id"] == out["agent_run_id"]
    assert detail["structured"]["action"] == [
        {"text": "Create purchase order", "node_id": world["create"], "missing": False}
    ]
    assert sorted((n["part"], n["name"]) for n in detail["nodes"]) == [
        ("action", "Create purchase order"),
        ("result", "PurchaseOrder"),
    ]
    assert "search_nodes" in fake.bound_tools and "submit_result" in fake.bound_tools
    # AI only drafts: the requirement is not confirmed
    with db.tx() as cur:
        cur.execute("SELECT status FROM requirement WHERE id=%s", (req["id"],))
        assert cur.fetchone()["status"] == "structured"


def test_missing_items_become_suggestions(client, world):
    req = new_req(client, world)
    use_model(
        client,
        call(
            "submit_result",
            {
                "items": [
                    {"part": "actor", "text": "Buyer", "missing": True},
                    {
                        "part": "constraint",
                        "text": "Amount greater than 0",
                        "missing": True,
                        "suggestion": {
                            "kind": "attribute",
                            "node_id": world["order"],
                            "attr": "constraints",
                            "text": "Amount greater than 0",
                        },
                    },
                    {"part": "action", "text": "Create purchase order", "node_id": world["create"]},
                ]
            },
        ),
    )
    out = client.post(f"{V1}/requirements/{req['id']}/structure").json()
    kinds = sorted((s["kind"], s["payload"].get("name") or s["payload"]["text"]) for s in out["suggestions"])
    assert kinds == [("attribute", "Amount greater than 0"), ("node", "Buyer")]
    assert out["requirement"]["structured"]["actor"] == [{"text": "Buyer", "node_id": None, "missing": True}]
    assert all(s["agent_run_id"] == out["agent_run_id"] for s in out["suggestions"])


def test_invalid_node_id_rejected(client, world, db):
    req = new_req(client, world)
    ghost = "11111111-1111-1111-1111-111111111111"
    bad = {"items": [{"part": "action", "text": "x", "node_id": ghost}]}
    good = {"items": [{"part": "action", "text": "Create purchase order", "node_id": world["create"]}]}
    fake = use_model(client, call("submit_result", bad), call("submit_result", good))
    out = client.post(f"{V1}/requirements/{req['id']}/structure").json()
    assert out["status"] == "succeeded"
    assert "does not exist" in fake.seen[1][-1].content
    # always invalid → run fails and nothing is written
    use_model(client, *[call("submit_result", bad)] * 3)
    other = new_req(client, world, "B")
    failed = client.post(f"{V1}/requirements/{other['id']}/structure").json()
    assert failed["status"] == "failed" and failed["error_code"] == "VALIDATION"
    with db.tx() as cur:
        cur.execute("SELECT status, structured FROM requirement WHERE id=%s", (other["id"],))
        row = cur.fetchone()
    assert row["status"] == "draft" and row["structured"] is None


def test_agent_runs_listed_newest_first(client, world):
    req = new_req(client, world)
    item = {"part": "action", "text": "Create purchase order", "node_id": world["create"]}
    use_model(client, call("submit_result", {"items": [item]}))
    run_id = client.post(f"{V1}/requirements/{req['id']}/structure").json()["agent_run_id"]
    runs = client.get(f"{V1}/agent/runs", params={"limit": 5}).json()
    assert runs[0]["id"] == run_id and runs[0]["step_count"] >= 1
    assert "steps" not in runs[0]
    assert client.get(f"{V1}/agent/runs", params={"purpose": "nope"}).json() == []


def test_structure_unconfigured_model_503(client, world):
    req = new_req(client, world)
    resp = client.post(f"{V1}/requirements/{req['id']}/structure")
    assert resp.status_code == 503 and resp.json()["code"] == "MODEL_UNAVAILABLE"


# ------------------------------------------------------------------ completion
def _complete(client, world, *suggestions):
    use_model(client, call("submit_result", {"suggestions": list(suggestions)}))
    resp = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_suggestions_deduplicated(client, world):
    supplier = {"kind": "node", "node_kind": "entity", "name": "Supplier"}
    existing = {"kind": "node", "node_kind": "entity", "name": "PurchaseOrder"}
    first = _complete(client, world, supplier, dict(supplier, name=" Supplier "), existing)
    assert [s["payload"]["name"] for s in first["suggestions"]] == ["Supplier"]
    assert first["skipped"] == 2
    again = _complete(client, world, supplier)
    assert again["suggestions"] == [] and again["skipped"] == 1
    pending = client.get(f"{V1}/suts/{world['sut']}/suggestions", params={"status": "pending"})
    assert len(pending.json()) == 1


def test_accept_creates_node_and_backfills_link(client, world):
    req = new_req(client, world)
    use_model(
        client,
        call(
            "submit_result",
            {
                "items": [
                    {"part": "actor", "text": "Buyer", "missing": True},
                    {"part": "action", "text": "Create purchase order", "node_id": world["create"]},
                ]
            },
        ),
    )
    out = client.post(f"{V1}/requirements/{req['id']}/structure").json()
    sugg = out["suggestions"][0]
    accepted = client.post(f"{V1}/suggestions/{sugg['id']}/accept", json={}).json()
    assert accepted["status"] == "accepted" and accepted["backfilled"] is True
    node = client.get(f"{V1}/nodes/{accepted['resolved_node_id']}").json()
    assert node["kind"] == "entity" and node["name"] == "Buyer"
    detail = client.get(f"{V1}/requirements/{req['id']}").json()
    assert detail["structured"]["actor"] == [{"text": "Buyer", "node_id": node["id"], "missing": False}]
    assert ("actor", "Buyer") in {(n["part"], n["name"]) for n in detail["nodes"]}
    assert client.post(f"{V1}/suggestions/{sugg['id']}/accept", json={}).status_code == 409
    # attribute suggestion appends to the node attributes
    attr = _complete(
        client,
        world,
        {"kind": "attribute", "node_id": world["order"], "attr": "states", "text": "paid"},
    )["suggestions"][0]
    client.post(f"{V1}/suggestions/{attr['id']}/accept", json={})
    order = client.get(f"{V1}/nodes/{world['order']}").json()
    assert order["attributes"]["states"] == [{"text": "paid"}]


def test_reject_keeps_record(client, world):
    sugg = _complete(client, world, {"kind": "node", "node_kind": "action", "name": "Undo"})["suggestions"][0]
    rejected = client.post(f"{V1}/suggestions/{sugg['id']}/reject", json={"reason": "Won't do"}).json()
    assert rejected["status"] == "rejected" and rejected["reason"] == "Won't do"
    rows = client.get(f"{V1}/suts/{world['sut']}/suggestions").json()
    assert [(r["status"], r["reason"]) for r in rows] == [("rejected", "Won't do")]
    names = {n["name"] for n in client.get(f"{V1}/suts/{world['sut']}/nodes").json()}
    assert "Undo" not in names


def test_completion_rejects_unknown_ids(client, world):
    fake = use_model(
        client,
        call(
            "submit_result",
            {
                "suggestions": [
                    {
                        "kind": "attribute",
                        "node_id": "22222222-2222-2222-2222-222222222222",
                        "attr": "states",
                        "text": "x",
                    }
                ]
            },
        ),
        call("submit_result", {"suggestions": []}),
    )
    out = client.post(f"{V1}/suts/{world['sut']}/model/complete", json={}).json()
    assert out["status"] == "succeeded" and out["suggestions"] == []
    assert len(fake.seen) == 2


# ------------------------------------------------------------------ freeze
def test_freeze_requires_all_confirmed(client, world):
    vid = world["version"]
    empty = client.post(f"{V1}/versions/{vid}/freeze")
    assert empty.status_code == 422
    ready_req(client, world)
    pending = new_req(client, world, "Unconfirmed")
    resp = client.post(f"{V1}/versions/{vid}/freeze")
    assert resp.status_code == 422 and resp.json()["related"] == [pending["code"]]
    client.delete(f"{V1}/requirements/{pending['id']}")
    events = []
    client.app.state.bus.subscribe("version.frozen", lambda e, p: events.append(p))
    frozen = client.post(f"{V1}/versions/{vid}/freeze").json()
    assert frozen["status"] == "requirements_frozen" and frozen["frozen_at"]
    assert events == [{"id": vid, "snapshot_id": frozen["model_snapshot_id"]}]


def test_snapshot_digest_stable(client, world, db):
    vid = world["version"]
    ready_req(client, world)
    first = client.post(f"{V1}/versions/{vid}/freeze").json()["model_snapshot_id"]
    client.post(f"{V1}/versions/{vid}/unfreeze", json={"reason": "r"})
    second = client.post(f"{V1}/versions/{vid}/freeze").json()["model_snapshot_id"]
    assert first != second
    with db.tx() as cur:
        cur.execute(
            "SELECT id::text AS id, digest, version_id::text AS v, content FROM model_snapshot"
            " WHERE id = ANY(%s::uuid[])",
            ([first, second],),
        )
        rows = {r["id"]: r for r in cur.fetchall()}
    assert rows[first]["digest"] == rows[second]["digest"]  # model unchanged → same digest
    assert rows[first]["v"] == vid
    names = sorted(n["name"] for n in rows[first]["content"]["nodes"])
    assert names == ["Create purchase order", "PurchaseOrder"]


def test_snapshot_immutable(client, world, db):
    ready_req(client, world)
    snap = client.post(f"{V1}/versions/{world['version']}/freeze").json()["model_snapshot_id"]
    with pytest.raises(AppError) as exc:
        with db.tx() as cur:
            cur.execute("UPDATE model_snapshot SET digest='x' WHERE id=%s", (snap,))
    assert exc.value.code == "CONFLICT"


def test_agent_actor_cannot_confirm_or_freeze(client, world, db):
    req = new_req(client, world)
    staff(client, world, req["id"])
    structure(client, world, req["id"])
    bus = client.app.state.bus
    with pytest.raises(AppError, match="can only be done by a person"):
        RequirementService(db, bus, actor="agent:123").confirm(req["id"])
    with pytest.raises(AppError, match="can only be done by a person"):
        VersionService(db, bus, actor="agent").freeze(world["version"])


def test_model_reply_without_submit_is_reported(client, world):
    req = new_req(client, world)
    use_model(client, *[AIMessage(content="looks fine")] * 3)
    out = client.post(f"{V1}/requirements/{req['id']}/structure").json()
    assert out["status"] == "failed" and out["error_code"] == "NO_RESULT"
