"""Demo data for the bundled procurement sample SUT (idempotent)."""

from __future__ import annotations

from testagent.core.events import EventBus
from testagent.services.apis import ApiService
from testagent.services.links import LinkService
from testagent.services.model import ModelService
from testagent.services.registry import EnvironmentService, ModuleService, PersonService, SutService

SUT_CODE = "procurement"
DEMO_START = "uv run uvicorn examples.procurement.api:create_app --factory --host 127.0.0.1 --port 8766"

PEOPLE = [
    ("Pat Product", "Product manager"),
    ("Dana Design", "Design"),
    ("Devin Dev", "Development"),
    ("Tess Tester", "Testing"),
]

ENTITIES = {
    "PurchaseOrder": {
        "data_schema": {"id": "string", "amount": "number", "status": "string"},
        "attributes": {
            "states": [
                {"text": "draft"},
                {"text": "pending_approval"},
                {"text": "approved"},
                {"text": "rejected"},
                {"text": "paid"},
            ],
            "constraints": [{"text": "Amount must be greater than 0", "expr": "amount > 0"}],
        },
    },
    "Supplier": {"data_schema": {"name": "string"}, "attributes": {}},
    "Approver": {
        "attributes": {"constraints": [{"text": "An approver cannot approve a purchase order they submitted"}]}
    },
    "Payment": {
        "data_schema": {"amount": "number"},
        "attributes": {"constraints": [{"text": "Total payments cannot exceed the purchase order amount"}]},
    },
}

ACTIONS = {
    "Create purchase order": ("POST", "/sample/orders", {"conditions": [{"text": "Amount greater than 0"}]}),
    "Approve purchase order": (
        "POST",
        "/sample/orders/{order_id}/decision",
        {"conditions": [{"text": "Purchase order is pending_approval"}]},
    ),
    "Record payment": (
        "POST",
        "/sample/orders/{order_id}/payments",
        {"conditions": [{"text": "Purchase order is approved"}]},
    ),
    "List payments": ("GET", "/sample/orders/{order_id}/payments", {}),
}

ACTION_EDGES = [
    ("Create purchase order", "PurchaseOrder", "object"),
    ("Approve purchase order", "Approver", "actor"),
    ("Approve purchase order", "PurchaseOrder", "object"),
    ("Record payment", "Payment", "object"),
    ("List payments", "Payment", "object"),
]

# former relation nodes, archived
RELATIONS = [
    ("PurchaseOrder-Supplier", "PurchaseOrder", "Supplier"),
    ("Payment-PurchaseOrder", "Payment", "PurchaseOrder"),
]
# links between entities, read both ways
LINKS = [
    ("PurchaseOrder", "belongs to", "Supplier", "supplies", "supplier", "purchaseOrders"),
    ("Payment", "pays", "PurchaseOrder", "receives", "order", "payments"),
]


def seed_procurement(db, bus: EventBus | None = None, demo_url: str | None = None) -> dict:
    bus = bus or EventBus()
    suts = SutService(db, bus)
    existing = [s for s in suts.list() if s["code"] == SUT_CODE]
    if existing:
        return {"sut_id": str(existing[0]["id"]), "created": False}
    sut = suts.create(
        {
            "code": SUT_CODE,
            "name": "Procurement approval (demo)",
            "description": "examples/procurement demo SUT",
        }
    )
    sut_id = sut["id"]
    EnvironmentService(db, bus).create(
        {
            "sut_id": sut_id,
            "name": "local",
            "base_url": demo_url or "http://127.0.0.1:8766",
            "start_command": None if demo_url else DEMO_START,
        }
    )
    module = ModuleService(db, bus).create({"sut_id": sut_id, "name": "Procurement flow"})
    people = PersonService(db, bus)
    for name, title in PEOPLE:
        if not any(p["name"] == name for p in people.list()):
            people.create({"name": name, "title": title})
    model, apis = ModelService(db, bus), ApiService(db, bus)
    ids: dict[str, str] = {}
    for name, spec in ENTITIES.items():
        node = model.create_node(sut_id, {"kind": "entity", "name": name, "module_id": module["id"], **spec})
        ids[name] = node["id"]
    for name, (method, path, attrs) in ACTIONS.items():
        node = model.create_node(
            sut_id,
            {
                "kind": "action",
                "name": name,
                "module_id": module["id"],
                "attributes": attrs,
                "code_ref": "examples/procurement/api.py",
            },
        )
        ids[name] = node["id"]
        api = apis.create(
            {
                "sut_id": sut_id,
                "method": method,
                "path": path,
                "name": name,
                "code_ref": "examples/procurement/api.py",
            }
        )
        apis.set_node_apis(node["id"], [api["id"]])
    for source, target, role in ACTION_EDGES:
        model.create_edge(sut_id, ids[source], ids[target], role)
    links = LinkService(db, bus)
    for source, forward, target, reverse, forward_api, reverse_api in LINKS:
        links.create(
            sut_id,
            {
                "from_node_id": ids[source],
                "to_node_id": ids[target],
                "forward_name": forward,
                "reverse_name": reverse,
                "forward_api_name": forward_api,
                "reverse_api_name": reverse_api,
                "cardinality": "many_to_one",
            },
        )
    return {"sut_id": str(sut_id), "created": True, "nodes": len(ids), "links": len(LINKS)}
