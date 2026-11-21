"""Scope rules from the case-generation design, including the procurement example in §5.5."""

from testagent.services.scope_manifest import (
    ActionRec,
    ApiRec,
    EntityRec,
    FieldRec,
    Graph,
    LinkRec,
    RequirementRefs,
    compute_manifest,
    names_of,
)

PO = "po"
SUP = "sup"
APR = "apr"
PAY = "pay"
CAT = "cat"
F_STATUS = "f-status"
F_AMOUNT = "f-amount"
F_ID = "f-id"
F_SUP = "f-sup"
F_PAY = "f-pay"
A_CREATE = "a-create"
A_APPROVE = "a-approve"
A_PAY = "a-pay"
A_LIST = "a-list"
A_REG = "a-reg"
L_SUP = "l-sup"
L_PAY = "l-pay"
L_FAR = "l-far"
API_APPROVE = "api-approve"


def procurement() -> Graph:
    """The demo ontology in design §5.5, plus a ref edge, a far-side link and a far-side action."""
    graph = Graph()
    graph.entities = {
        PO: EntityRec(
            PO,
            "PurchaseOrder",
            ["draft", "pending_approval", "approved", "rejected", "paid"],
            ["Amount must be greater than 0"],
        ),
        SUP: EntityRec(SUP, "Supplier"),
        APR: EntityRec(APR, "Approver", constraints=["An approver cannot approve a purchase order they submitted"]),
        PAY: EntityRec(PAY, "Payment", constraints=["Total payments cannot exceed the purchase order amount"]),
        CAT: EntityRec(CAT, "Catalog"),
    }
    graph.fields = {
        F_ID: FieldRec(F_ID, PO, "PurchaseOrder", "id"),
        F_AMOUNT: FieldRec(F_AMOUNT, PO, "PurchaseOrder", "amount"),
        F_STATUS: FieldRec(F_STATUS, PO, "PurchaseOrder", "status"),
        F_SUP: FieldRec(F_SUP, SUP, "Supplier", "name"),
        F_PAY: FieldRec(F_PAY, PAY, "Payment", "amount"),
    }
    graph.actions = {
        A_CREATE: ActionRec(
            A_CREATE,
            "Create purchase order",
            effects=[
                {
                    "kind": "set_field",
                    "field": "PurchaseOrder.status",
                    "attribute_id": F_STATUS,
                    "values": ["pending_approval"],
                }
            ],
            object_ids=[PO],
        ),
        A_APPROVE: ActionRec(
            A_APPROVE,
            "Approve purchase order",
            preconditions=[
                {"field": "PurchaseOrder.status", "attribute_id": F_STATUS, "op": "eq", "value": "pending_approval"}
            ],
            effects=[
                {
                    "kind": "set_field",
                    "field": "PurchaseOrder.status",
                    "attribute_id": F_STATUS,
                    "values": ["approved", "rejected"],
                }
            ],
            actor_ids=[APR],
            object_ids=[PO],
            ref_ids=[CAT],
            api_ids=[API_APPROVE],
        ),
        A_PAY: ActionRec(
            A_PAY,
            "Record payment",
            preconditions=[
                {"field": "PurchaseOrder.status", "attribute_id": F_STATUS, "op": "eq", "value": "approved"}
            ],
            object_ids=[PAY],
        ),
        A_LIST: ActionRec(A_LIST, "List payments", object_ids=[PAY], api_ids=["api-list"]),
        A_REG: ActionRec(A_REG, "Register supplier", object_ids=[SUP]),
    }
    graph.apis = {
        API_APPROVE: ApiRec(API_APPROVE, "POST", "/sample/orders/{order_id}/decision", A_APPROVE),
        "api-list": ApiRec("api-list", "GET", "/sample/orders/{order_id}/payments", A_LIST),
    }
    graph.links = {
        L_SUP: LinkRec(L_SUP, PO, SUP, "PurchaseOrder", "Supplier", "belongs to", "many_to_one", required=False),
        L_PAY: LinkRec(L_PAY, PAY, PO, "Payment", "PurchaseOrder", "pays", "many_to_one", required=False),
        L_FAR: LinkRec(L_FAR, SUP, CAT, "Supplier", "Catalog", "listed in", "many_to_one", required=False),
    }
    return graph


def approval_refs(**extra) -> RequirementRefs:
    refs = RequirementRefs(
        "req-1",
        "REQ-001",
        "待审批的采购订单可由审批人批准或驳回",
        nodes=[(A_APPROVE, "action"), (APR, "actor")],
        fields=[(F_STATUS, "condition")],
    )
    for key, value in extra.items():
        setattr(refs, key, value)
    return refs


def test_depth_1_matches_the_procurement_example():
    manifest = compute_manifest(procurement(), approval_refs(), 1)
    assert manifest.get("blocked") is not True
    assert names_of(manifest, "action") == {"Approve purchase order"}
    assert "PurchaseOrder" in names_of(manifest, "node") and "Approver" in names_of(manifest, "node")
    assert names_of(manifest, "field") == {
        "PurchaseOrder.id",
        "PurchaseOrder.amount",
        "PurchaseOrder.status",
        "Supplier.name",
        "Payment.amount",
    }
    assert names_of(manifest, "link") == {"PurchaseOrder belongs to Supplier", "Payment pays PurchaseOrder"}
    assert "Supplier" in names_of(manifest, "node") and "Payment" in names_of(manifest, "node")
    assert "Catalog" not in names_of(manifest, "node")
    assert "Create purchase order" not in names_of(manifest, "action")
    assert "Record payment" not in names_of(manifest, "action")
    assert "List payments" not in names_of(manifest, "action")
    assert "Register supplier" not in names_of(manifest, "action")
    kinds = {t["type"] for t in manifest["targets"]}
    assert {
        "field",
        "action",
        "precondition_met",
        "precondition_violated",
        "effect",
        "constraint",
        "link_missing",
        "link_dangling",
        "link_cardinality",
    } <= kinds
    assert any(t["type"] == "constraint" and "cannot approve" in t["text"] for t in manifest["targets"])
    assert any(t["type"] == "effect" and t["then"].endswith("approved") for t in manifest["targets"])
    assert any(t["type"] == "effect" and t["then"].endswith("rejected") for t in manifest["targets"])
    missing = [t for t in manifest["targets"] if t["type"] == "link_missing"]
    assert missing and all(t["nullable"] is True for t in missing)
    status = next(f for f in manifest["fields"] if f["name"] == "status")
    assert status["origin"] == "seed"
    amount = next(f for f in manifest["fields"] if f["entity"] == "PurchaseOrder" and f["name"] == "amount")
    assert amount["origin"] == "expanded"
    supplier = next(n for n in manifest["nodes"] if n["name"] == "Supplier")
    assert supplier["far_side"] is True


def test_depth_0_is_only_the_seed():
    manifest = compute_manifest(procurement(), approval_refs(), 0)
    assert names_of(manifest, "action") == {"Approve purchase order"}
    assert names_of(manifest, "field") == {"PurchaseOrder.status"}
    assert names_of(manifest, "link") == set()
    assert "Supplier" not in names_of(manifest, "node")
    assert "Payment" not in names_of(manifest, "node")


def test_depth_2_still_excludes_downstream_and_far_side_expansion():
    manifest = compute_manifest(procurement(), approval_refs(), 2)
    assert "Record payment" not in names_of(manifest, "action")
    assert "Create purchase order" not in names_of(manifest, "action")
    assert "List payments" not in names_of(manifest, "action")
    assert "Supplier listed in Catalog" not in names_of(manifest, "link")
    assert "Catalog" not in names_of(manifest, "node")


def test_read_only_action_is_included_only_when_cited_as_result():
    graph = procurement()
    cited = RequirementRefs("req-2", "REQ-002", "List", nodes=[(A_LIST, "result")])
    manifest = compute_manifest(graph, cited, 1)
    assert "List payments" in names_of(manifest, "action")
    plain = RequirementRefs("req-3", "REQ-003", "Payment entity", nodes=[(PAY, "actor")])
    assert "List payments" not in names_of(compute_manifest(graph, plain, 1), "action")
    assert "Record payment" not in names_of(compute_manifest(graph, plain, 1), "action")


def test_missing_refs_block_without_a_manifest():
    manifest = compute_manifest(procurement(), RequirementRefs("req", "REQ-009", "Title only"), 1)
    assert manifest["blocked"] is True
    assert "REQ-009" in manifest["message"]
    assert manifest["targets"] == []


def test_effect_to_precondition_chain_stays_out_of_depth_1():
    from testagent.services.scope_manifest import derive_chains

    graph = procurement()
    chains = derive_chains(graph)
    assert [[a["name"] for a in c["actions"]] for c in chains] == [
        ["Create purchase order", "Approve purchase order", "Record payment"]
    ]
    assert "List payments" not in chains[0]["actions"][0]["name"]
    for depth in (1, 2):
        actions = names_of(compute_manifest(graph, approval_refs(), depth), "action")
        assert actions == {"Approve purchase order"}


def test_a_cover_claim_without_the_node_is_not_a_hit():
    from testagent.services.scope_manifest import case_covers_target

    target = {"id": "pre_met:a", "type": "precondition_met", "action_id": "a"}
    assert case_covers_target(target, {"covers": ["pre_met:a"], "node_ids": [], "attribute_ids": []}) is False
    assert case_covers_target(target, {"covers": ["pre_met:a"], "node_ids": ["a"], "attribute_ids": []}) is True
    field = {"id": "field:f", "type": "field", "attribute_id": "f"}
    assert case_covers_target(field, {"covers": ["field:f"], "node_ids": [], "attribute_ids": []}) is False
    assert case_covers_target(field, {"covers": [], "node_ids": [], "attribute_ids": ["f"]}) is True


def test_same_inputs_are_deterministic():
    graph = procurement()
    refs = approval_refs()
    assert compute_manifest(graph, refs, 1) == compute_manifest(procurement(), approval_refs(), 1)
