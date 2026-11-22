"""供应链执行演示被测系统：先有完整模型，再写入固定需求。v2 从 v1 复制后扩展。"""

from __future__ import annotations

from testagent.core.events import EventBus
from testagent.demo_api_schemas import API_SPECS
from testagent.services.apis import ApiService
from testagent.services.attributes import AttributeService
from testagent.services.links import LinkService
from testagent.services.model import ModelService
from testagent.services.registry import EnvironmentService, ModuleService, PersonService, SutService
from testagent.services.requirements import RequirementService
from testagent.services.versions import VersionService

SUT_CODE = "supply-chain"
SUT_NAME = "供应链执行（演示）"
DEMO_START = "uv run uvicorn examples.supply_chain.api:create_app --factory --host 127.0.0.1 --port 8766"
CODE_REF = "examples/supply_chain/api.py"

PEOPLE = [
    ("Pat Product", "产品"),
    ("Dana Design", "设计"),
    ("Devin Dev", "开发"),
    ("Tess Tester", "测试"),
]

APIS = API_SPECS


def seed_supply_chain(db, bus: EventBus | None = None, demo_url: str | None = None) -> dict:
    bus = bus or EventBus()
    suts = SutService(db, bus)
    existing = [s for s in suts.list() if s["code"] == SUT_CODE]
    if existing and _has_model(db, existing[0]["id"]):
        return {"sut_id": str(existing[0]["id"]), "created": False}
    if existing:
        sut_id = existing[0]["id"]
    else:
        sut = suts.create({"code": SUT_CODE, "name": SUT_NAME, "description": "examples/supply_chain 演示被测系统"})
        sut_id = sut["id"]
        EnvironmentService(db, bus).create(
            {
                "sut_id": sut_id,
                "name": "local",
                "base_url": demo_url or "http://127.0.0.1:8766",
                "start_command": None if demo_url else DEMO_START,
            }
        )
        people = PersonService(db, bus)
        have = {p["name"] for p in people.list()}
        for name, title in PEOPLE:
            if name not in have:
                people.create({"name": name, "title": title})
    modules = {m["name"]: m["id"] for m in ModuleService(db, bus).list({"sut_id": sut_id})}
    for name in ("主数据", "采购", "仓储质检"):
        if name not in modules:
            modules[name] = ModuleService(db, bus).create({"sut_id": sut_id, "name": name})["id"]
    apis = ApiService(db, bus)
    api_ids = {}
    for spec in APIS:
        method, path, name = spec["method"], spec["path"], spec["name"]
        schema = {
            "request_schema": spec["request_schema"],
            "response_schema": spec["response_schema"],
        }
        found = [a for a in apis.list_for_sut(sut_id) if a["method"] == method and a["path"] == path]
        if found:
            api_ids[(method, path)] = found[0]["id"]
            if not found[0].get("request_schema") and not found[0].get("response_schema"):
                apis.update(found[0]["id"], schema)
        else:
            api_ids[(method, path)] = apis.create(
                {"sut_id": sut_id, "method": method, "path": path, "name": name, "code_ref": CODE_REF, **schema}
            )["id"]
    versions = VersionService(db, bus)
    v1 = versions.create(sut_id, "v1.0")["id"]
    _build_v1(db, bus, sut_id, v1, modules, api_ids)
    _requirements(db, bus, v1, _index(db, v1), v2=False)
    _seal(db, v1)
    v2 = versions.create(sut_id, "v2.0", v1)["id"]
    _extend_v2(db, bus, sut_id, v2, modules, api_ids)
    _requirements(db, bus, v2, _index(db, v2), v2=True)
    return {"sut_id": str(sut_id), "created": True, "versions": [str(v1), str(v2)]}


def _seal(db, version_id) -> None:
    with db.tx() as cur:
        cur.execute("UPDATE version SET sealed=true WHERE id=%s", (version_id,))


def _has_model(db, sut_id) -> bool:
    with db.tx() as cur:
        cur.execute("SELECT 1 FROM model_node WHERE sut_id=%s AND deleted_at IS NULL LIMIT 1", (sut_id,))
        return cur.fetchone() is not None


def _index(db, version_id) -> dict:
    with db.tx() as cur:
        cur.execute(
            "SELECT id::text AS id, kind, name FROM model_node WHERE version_id=%s AND deleted_at IS NULL",
            (version_id,),
        )
        nodes = {(r["kind"], r["name"]): r["id"] for r in cur.fetchall()}
        cur.execute(
            "SELECT a.id::text AS id, a.name, n.name AS node FROM entity_attribute a"
            " JOIN model_node n ON n.id=a.node_id WHERE n.version_id=%s AND a.deleted_at IS NULL",
            (version_id,),
        )
        fields = {(r["node"], r["name"]): r["id"] for r in cur.fetchall()}
        cur.execute(
            "SELECT l.id::text AS id, f.name AS src, l.forward_name FROM model_link l"
            " JOIN model_node f ON f.id=l.from_node_id WHERE l.version_id=%s AND l.deleted_at IS NULL",
            (version_id,),
        )
        links = {(r["src"], r["forward_name"]): r["id"] for r in cur.fetchall()}
    return {"nodes": nodes, "fields": fields, "links": links}


def _entity(model, sut_id, module, name, states=None, constraints=None):
    attributes = {}
    if states:
        attributes["states"] = [{"text": s} for s in states]
    if constraints:
        attributes["constraints"] = [{"text": c} for c in constraints]
    return model.create_node(
        sut_id,
        {"kind": "entity", "name": name, "module_id": module, "attributes": attributes, "version_id": None},
    )


def _build_v1(db, bus, sut_id, version_id, modules, api_ids) -> None:
    model = ModelService(db, bus)
    fields = AttributeService(db, bus)
    links = LinkService(db, bus)
    master, buy, wh = modules["主数据"], modules["采购"], modules["仓储质检"]

    def ent(module, name, **kw):
        node = model.create_node(
            sut_id,
            {
                "kind": "entity",
                "name": name,
                "module_id": module,
                "attributes": {
                    **({"states": [{"text": s} for s in kw.get("states", [])]} if kw.get("states") else {}),
                    **(
                        {"constraints": [{"text": c} for c in kw.get("constraints", [])]}
                        if kw.get("constraints")
                        else {}
                    ),
                },
                "version_id": version_id,
            },
        )
        return node["id"]

    ids = {
        "Material": ent(master, "Material", constraints=["编码唯一"]),
        "Supplier": ent(
            master,
            "Supplier",
            states=["potential", "qualified", "frozen"],
            constraints=["冻结供应商不能用于新建或下达采购订单"],
        ),
        "SupplierMaterial": ent(master, "SupplierMaterial"),
        "Warehouse": ent(master, "Warehouse"),
        "Inventory": ent(master, "Inventory", constraints=["onHandQty 不得为负", "reservedQty 不得超过 onHandQty"]),
        "Buyer": ent(master, "Buyer", constraints=["采购员不能审批自己提交的采购申请或采购订单"]),
        "PurchaseRequisition": ent(
            buy,
            "PurchaseRequisition",
            states=["draft", "submitted", "approved", "rejected", "converted"],
        ),
        "PurchaseOrder": ent(
            buy,
            "PurchaseOrder",
            states=[
                "draft",
                "pending_approval",
                "approved",
                "issued",
                "partial_received",
                "received",
                "closed",
                "cancelled",
                "rejected",
            ],
            constraints=["金额必须大于 0", "已取消或已关闭的订单不能再收货或改数量"],
        ),
        "PurchaseOrderLine": ent(buy, "PurchaseOrderLine", constraints=["v1 下 receivedQty 不得超过 orderedQty"]),
        "GoodsReceipt": ent(wh, "GoodsReceipt", states=["draft", "posted"]),
    }
    spec = {
        "Material": [
            ("code", "string", True),
            ("name", "string", True),
            ("unit", "enum", True),
            ("safetyStock", "number", False),
        ],
        "Supplier": [("code", "string", True), ("name", "string", True), ("status", "enum", True)],
        "SupplierMaterial": [
            ("price", "money", True),
            ("leadTimeDays", "integer", True),
            ("minOrderQty", "number", True),
        ],
        "Warehouse": [("code", "string", True), ("name", "string", True)],
        "Inventory": [("onHandQty", "number", True), ("reservedQty", "number", True)],
        "Buyer": [("code", "string", True), ("name", "string", True)],
        "PurchaseRequisition": [
            ("code", "string", True),
            ("qty", "number", True),
            ("needByDate", "date", False),
            ("status", "enum", True),
        ],
        "PurchaseOrder": [
            ("code", "string", True),
            ("amount", "money", True),
            ("currency", "string", True),
            ("needByDate", "date", False),
            ("status", "enum", True),
        ],
        "PurchaseOrderLine": [
            ("orderedQty", "number", True),
            ("receivedQty", "number", True),
            ("unitPrice", "money", True),
        ],
        "GoodsReceipt": [("code", "string", True), ("receivedQty", "number", True), ("status", "enum", True)],
    }
    enums = {
        ("Material", "unit"): ["PCS", "KG", "BOX"],
        ("Supplier", "status"): ["potential", "qualified", "frozen"],
        ("PurchaseRequisition", "status"): ["draft", "submitted", "approved", "rejected", "converted"],
        ("PurchaseOrder", "status"): [
            "draft",
            "pending_approval",
            "approved",
            "issued",
            "partial_received",
            "received",
            "closed",
            "cancelled",
            "rejected",
        ],
        ("GoodsReceipt", "status"): ["draft", "posted"],
    }
    for entity, cols in spec.items():
        for name, data_type, required in cols:
            payload = {"name": name, "data_type": data_type, "required": required}
            if (entity, name) in enums:
                payload["enum_values"] = enums[(entity, name)]
            fields.create(ids[entity], payload)
    actions = {
        "新建采购申请": ("POST", "/sample/requisitions"),
        "提交采购申请": ("POST", "/sample/requisitions/{req_id}/submit"),
        "审批采购申请": ("POST", "/sample/requisitions/{req_id}/decision"),
        "按申请创建采购订单": ("POST", "/sample/orders"),
        "提交采购订单": ("POST", "/sample/orders/{order_id}/submit"),
        "审批采购订单": ("POST", "/sample/orders/{order_id}/decision"),
        "下达采购订单": ("POST", "/sample/orders/{order_id}/issue"),
        "按订单收货": ("POST", "/sample/orders/{order_id}/receive"),
        "收货过账入库": ("POST", "/sample/receipts/{receipt_id}/post"),
        "关闭采购订单": ("POST", "/sample/orders/{order_id}/close"),
        "取消采购订单": ("POST", "/sample/orders/{order_id}/cancel"),
        "冻结供应商": ("POST", "/sample/suppliers/{supplier_id}/freeze"),
        "查询库存": ("GET", "/sample/inventory"),
    }
    apis = ApiService(db, bus)
    for name, (method, path) in actions.items():
        node = model.create_node(
            sut_id,
            {
                "kind": "action",
                "name": name,
                "module_id": buy
                if "采购" in name
                or name.startswith("按")
                or name.startswith("提交")
                or name.startswith("审批")
                or name.startswith("下达")
                or name.startswith("关闭")
                or name.startswith("取消")
                else wh
                if name.startswith("收") or name.startswith("查")
                else master,
                "code_ref": CODE_REF,
                "version_id": version_id,
            },
        )
        ids[name] = node["id"]
        apis.set_node_apis(node["id"], [api_ids[(method, path)]])
    pairs = [
        ("新建采购申请", "Buyer", "actor"),
        ("新建采购申请", "PurchaseRequisition", "object"),
        ("提交采购申请", "Buyer", "actor"),
        ("提交采购申请", "PurchaseRequisition", "object"),
        ("审批采购申请", "Buyer", "actor"),
        ("审批采购申请", "PurchaseRequisition", "object"),
        ("按申请创建采购订单", "PurchaseRequisition", "object"),
        ("按申请创建采购订单", "PurchaseOrder", "object"),
        ("提交采购订单", "Buyer", "actor"),
        ("提交采购订单", "PurchaseOrder", "object"),
        ("审批采购订单", "Buyer", "actor"),
        ("审批采购订单", "PurchaseOrder", "object"),
        ("下达采购订单", "PurchaseOrder", "object"),
        ("按订单收货", "PurchaseOrder", "object"),
        ("按订单收货", "GoodsReceipt", "object"),
        ("收货过账入库", "GoodsReceipt", "object"),
        ("收货过账入库", "Inventory", "object"),
        ("关闭采购订单", "PurchaseOrder", "object"),
        ("取消采购订单", "PurchaseOrder", "object"),
        ("冻结供应商", "Supplier", "object"),
        ("查询库存", "Inventory", "object"),
    ]
    for source, target, role in pairs:
        model.create_edge(sut_id, ids[source], ids[target], role)
    link_rows = [
        ("PurchaseRequisition", "申请", "Material", "被申请", "material", "requisitions", "many_to_one", True),
        ("PurchaseRequisition", "由采购员提交", "Buyer", "提交申请", "buyer", "requisitions", "many_to_one", True),
        (
            "PurchaseRequisition",
            "建议供应商",
            "Supplier",
            "被建议",
            "supplier",
            "suggestedRequisitions",
            "many_to_one",
            False,
        ),
        ("PurchaseRequisition", "转换成", "PurchaseOrder", "来源于申请", "order", "requisition", "one_to_one", False),
        ("PurchaseOrder", "向其采购", "Supplier", "接受订单", "supplier", "orders", "many_to_one", True),
        ("PurchaseOrder", "由采购员负责", "Buyer", "负责订单", "buyer", "orders", "many_to_one", True),
        ("PurchaseOrder", "包含", "PurchaseOrderLine", "属于订单", "lines", "order", "one_to_many", True),
        ("PurchaseOrderLine", "采购", "Material", "被采购", "material", "orderLines", "many_to_one", True),
        ("SupplierMaterial", "属于", "Supplier", "可供物料", "supplier", "materials", "many_to_one", True),
        ("SupplierMaterial", "供应", "Material", "由供应商供应", "material", "supplierMaterials", "many_to_one", True),
        ("GoodsReceipt", "针对", "PurchaseOrderLine", "被收货", "line", "receipts", "many_to_one", True),
        ("GoodsReceipt", "收入", "Warehouse", "收到", "warehouse", "receipts", "many_to_one", True),
        ("GoodsReceipt", "记录", "Material", "被收货", "material", "receipts", "many_to_one", True),
        ("Inventory", "存放于", "Warehouse", "存放", "warehouse", "inventories", "many_to_one", True),
        ("Inventory", "对应", "Material", "库存", "material", "inventories", "many_to_one", True),
    ]
    for src, forward, dst, reverse, f_api, r_api, card, required in link_rows:
        links.create(
            sut_id,
            {
                "from_node_id": ids[src],
                "to_node_id": ids[dst],
                "forward_name": forward,
                "reverse_name": reverse,
                "forward_api_name": f_api,
                "reverse_api_name": r_api,
                "cardinality": card,
                "required": required,
            },
        )
    rules = {
        "新建采购申请": (
            [{"field": "PurchaseRequisition.qty", "op": "gt", "value": 0}],
            [{"kind": "set_field", "field": "PurchaseRequisition.status", "values": ["draft"]}],
        ),
        "提交采购申请": (
            [
                {"field": "PurchaseRequisition.status", "op": "eq", "value": "draft"},
                {"field": "PurchaseRequisition.qty", "op": "gt", "value": 0},
            ],
            [{"kind": "set_field", "field": "PurchaseRequisition.status", "values": ["submitted"]}],
        ),
        "审批采购申请": (
            [{"field": "PurchaseRequisition.status", "op": "eq", "value": "submitted"}, {"text": "审批人不是提交人"}],
            [{"kind": "set_field", "field": "PurchaseRequisition.status", "values": ["approved", "rejected"]}],
        ),
        "按申请创建采购订单": (
            [
                {"field": "PurchaseRequisition.status", "op": "eq", "value": "approved"},
                {"text": "若指定供应商则供应商不是冻结"},
            ],
            [
                {"kind": "set_field", "field": "PurchaseOrder.status", "values": ["draft"]},
                {"kind": "set_field", "field": "PurchaseRequisition.status", "values": ["converted"]},
            ],
        ),
        "提交采购订单": (
            [
                {"field": "PurchaseOrder.status", "op": "eq", "value": "draft"},
                {"field": "PurchaseOrder.amount", "op": "gt", "value": 0},
                {"text": "至少一行，且行数量不低于最小起订量"},
            ],
            [{"kind": "set_field", "field": "PurchaseOrder.status", "values": ["pending_approval"]}],
        ),
        "审批采购订单": (
            [{"field": "PurchaseOrder.status", "op": "eq", "value": "pending_approval"}, {"text": "审批人不是提交人"}],
            [{"kind": "set_field", "field": "PurchaseOrder.status", "values": ["approved", "rejected"]}],
        ),
        "下达采购订单": (
            [{"field": "PurchaseOrder.status", "op": "eq", "value": "approved"}, {"text": "供应商不得为冻结"}],
            [{"kind": "set_field", "field": "PurchaseOrder.status", "values": ["issued"]}],
        ),
        "按订单收货": (
            [
                {"field": "PurchaseOrder.status", "op": "in", "value": ["issued", "partial_received"]},
                {"field": "GoodsReceipt.receivedQty", "op": "gt", "value": 0},
            ],
            [
                {"kind": "set_field", "field": "GoodsReceipt.status", "values": ["draft"]},
                {"kind": "set_field", "field": "PurchaseOrder.status", "values": ["partial_received", "received"]},
            ],
        ),
        "收货过账入库": (
            [{"field": "GoodsReceipt.status", "op": "eq", "value": "draft"}],
            [{"kind": "set_field", "field": "GoodsReceipt.status", "values": ["posted"]}],
        ),
        "关闭采购订单": (
            [{"field": "PurchaseOrder.status", "op": "eq", "value": "received"}],
            [{"kind": "set_field", "field": "PurchaseOrder.status", "values": ["closed"]}],
        ),
        "取消采购订单": (
            [
                {
                    "field": "PurchaseOrder.status",
                    "op": "in",
                    "value": ["draft", "pending_approval", "approved", "issued"],
                },
                {"text": "所有行累计收货数量为 0"},
            ],
            [{"kind": "set_field", "field": "PurchaseOrder.status", "values": ["cancelled"]}],
        ),
        "冻结供应商": (
            [{"text": "供应商不是已冻结"}],
            [{"kind": "set_field", "field": "Supplier.status", "values": ["frozen"]}],
        ),
        "查询库存": ([{"text": "物料与仓库存在"}], []),
    }
    for name, (pre, eff) in rules.items():
        model.update_node(ids[name], {"preconditions": pre, "effects": eff})


def _extend_v2(db, bus, sut_id, version_id, modules, api_ids) -> None:
    model = ModelService(db, bus)
    fields = AttributeService(db, bus)
    links = LinkService(db, bus)
    idx = _index(db, version_id)
    material = idx["nodes"][("entity", "Material")]
    order = idx["nodes"][("entity", "PurchaseOrder")]
    receipt = idx["nodes"][("entity", "GoodsReceipt")]
    fields.create(material, {"name": "inspectionRequired", "data_type": "boolean", "required": True})
    fields.create(order, {"name": "overReceiveTolerancePct", "data_type": "number", "required": False})
    qi = model.create_node(
        sut_id,
        {
            "kind": "entity",
            "name": "QualityInspection",
            "module_id": modules["仓储质检"],
            "version_id": version_id,
            "attributes": {
                "states": [{"text": "pending"}, {"text": "passed"}, {"text": "failed"}],
                "constraints": [{"text": "inspectionRequired = true 的物料，质检未合格不得过账入库"}],
            },
        },
    )["id"]
    fields.create(qi, {"name": "code", "data_type": "string", "required": True})
    fields.create(
        qi, {"name": "result", "data_type": "enum", "required": True, "enum_values": ["pending", "passed", "failed"]}
    )
    fields.create(qi, {"name": "defectQty", "data_type": "number", "required": False})
    links.create(
        sut_id,
        {
            "from_node_id": qi,
            "to_node_id": receipt,
            "forward_name": "针对收货",
            "reverse_name": "质检",
            "forward_api_name": "receipt",
            "reverse_api_name": "inspections",
            "cardinality": "many_to_one",
            "required": True,
        },
    )
    links.create(
        sut_id,
        {
            "from_node_id": qi,
            "to_node_id": material,
            "forward_name": "检验",
            "reverse_name": "被检验",
            "forward_api_name": "material",
            "reverse_api_name": "inspections",
            "cardinality": "many_to_one",
            "required": True,
        },
    )
    apis = ApiService(db, bus)
    for name, key in (
        ("创建质检单", ("POST", "/sample/receipts/{receipt_id}/inspections")),
        ("判定质检", ("POST", "/sample/inspections/{inspection_id}/decision")),
    ):
        node = model.create_node(
            sut_id,
            {
                "kind": "action",
                "name": name,
                "module_id": modules["仓储质检"],
                "code_ref": CODE_REF,
                "version_id": version_id,
            },
        )
        apis.set_node_apis(node["id"], [api_ids[key]])
        if name == "创建质检单":
            model.create_edge(sut_id, node["id"], receipt, "object")
            model.create_edge(sut_id, node["id"], qi, "object")
            model.update_node(
                node["id"],
                {
                    "preconditions": [
                        {"field": "GoodsReceipt.status", "op": "eq", "value": "draft"},
                        {"field": "Material.inspectionRequired", "op": "eq", "value": True},
                    ],
                    "effects": [{"kind": "set_field", "field": "QualityInspection.result", "values": ["pending"]}],
                },
            )
        else:
            model.create_edge(sut_id, node["id"], qi, "object")
            model.update_node(
                node["id"],
                {
                    "preconditions": [{"field": "QualityInspection.result", "op": "eq", "value": "pending"}],
                    "effects": [
                        {"kind": "set_field", "field": "QualityInspection.result", "values": ["passed", "failed"]}
                    ],
                },
            )
    issue = idx["nodes"][("action", "下达采购订单")]
    post = idx["nodes"][("action", "收货过账入库")]
    model.update_node(
        issue,
        {
            "preconditions": [
                {"field": "PurchaseOrder.status", "op": "eq", "value": "approved"},
                {"field": "Supplier.status", "op": "eq", "value": "qualified"},
            ],
            "effects": [{"kind": "set_field", "field": "PurchaseOrder.status", "values": ["issued"]}],
        },
    )
    model.update_node(
        post,
        {
            "preconditions": [
                {"field": "GoodsReceipt.status", "op": "eq", "value": "draft"},
                {"text": "若物料需要质检，则须已有结果为合格的质检单"},
            ],
            "effects": [{"kind": "set_field", "field": "GoodsReceipt.status", "values": ["posted"]}],
        },
    )


REQS = {
    "REQ-001": ("新建采购申请", "采购员可为指定物料创建采购申请。数量必须大于 0，物料必须已存在。创建后申请处于草稿。"),
    "REQ-002": ("提交采购申请", "草稿状态的采购申请可由提交人提交，提交后进入待审批。数量仍须大于 0。"),
    "REQ-003": (
        "审批采购申请",
        "待审批的采购申请可由审批人批准或驳回。提交人不得审批自己提交的申请。批准后状态为已批准，驳回后为已驳回。",
    ),
    "REQ-004": (
        "按已批准申请创建采购订单",
        "已批准的采购申请可转换成草稿采购订单，转换后申请状态为已转换，不得再次转换。若申请指定了供应商，该供应商不得为冻结。",
    ),
    "REQ-005": (
        "提交采购订单",
        "草稿采购订单至少包含一行、金额大于 0 方可提交。若该供应商物料存在最小起订量，"
        "则行数量不得低于最小起订量。提交后进入待审批。",
    ),
    "REQ-006": ("审批采购订单", "待审批的采购订单可由审批人批准或驳回。提交人不得审批自己提交的订单。"),
    "REQ-007": ("下达采购订单给供应商", None),
    "REQ-008": ("按订单收货", None),
    "REQ-009": ("收货过账入库", None),
    "REQ-010": ("关闭采购订单", "已收货且各行在收货规则内已收齐的订单可以关闭。关闭后不得再收货。"),
    "REQ-011": (
        "取消尚未收货的采购订单",
        "草稿、待审批、已批准或已下达、且所有行累计收货数量为 0 的采购订单可以取消。"
        "已有收货的订单不得取消。取消后不得再收货。",
    ),
    "REQ-012": (
        "冻结供应商",
        "可将供应商冻结。冻结后不得用该供应商新建或下达采购订单。已经下达且未取消的订单仍可继续收货、过账（按该版本的收货规则）。",
    ),
}
REQ_007 = "已批准的采购订单可下达给供应商。供应商不得为冻结。下达后订单为已下达，此后才允许收货。"
REQ_008 = (
    "已下达或部分收货的订单可分次收货，收货数量必须大于 0。累计收货数量不得超过订购数量。"
    "已取消或已关闭的订单不得收货。收货后，若尚未收齐则为部分收货，收齐则为已收货。"
)
REQ_009 = "草稿收货单可过账，过账后对应仓库中该物料的在库数量按收货数量增加，库存不得变为负数。"
# v2 keeps the titles only. Bodies and structure stay empty.
V2_ONLY = {
    "REQ-013": "物料质检要求",
    "REQ-014": "创建质检单",
    "REQ-015": "判定质检",
    "REQ-016": "供应商准入",
}


def _requirements(db, bus, version_id, idx, *, v2: bool) -> None:
    reqs = RequirementService(db, bus)
    if v2:
        # Code, title, and priority only. No raw text, people, or structured refs.
        rows = [(code, REQS[code][0]) for code in ("REQ-007", "REQ-008", "REQ-009")]
        rows += list(V2_ONLY.items())
        for code, title in rows:
            reqs.create(version_id, {"code": code, "title": title, "priority": "P1"})
        return
    nodes, fields, links = idx["nodes"], idx["fields"], idx["links"]

    def add(code, title, text, structure):
        row = reqs.create(version_id, {"code": code, "title": title, "raw_text": text})
        reqs.set_structure(row["id"], structure)

    def n(name, kind="action"):
        return nodes[(kind, name)]

    def f(entity, name):
        return fields[(entity, name)]

    def lk(src, forward):
        return links[(src, forward)]

    common = {
        "REQ-001": {
            "actor": [{"text": "采购员", "node_id": n("Buyer", "entity")}],
            "action": [{"text": "新建采购申请", "node_id": n("新建采购申请")}],
            "condition": [
                {"text": "物料已存在", "node_id": n("Material", "entity")},
                {"text": "数量大于 0", "attribute_id": f("PurchaseRequisition", "qty")},
            ],
            "result": [{"text": "申请处于草稿", "attribute_id": f("PurchaseRequisition", "status")}],
            "constraint": [{"text": "数量必须大于 0", "attribute_id": f("PurchaseRequisition", "qty")}],
        },
        "REQ-002": {
            "actor": [{"text": "提交人", "node_id": n("Buyer", "entity")}],
            "action": [{"text": "提交采购申请", "node_id": n("提交采购申请")}],
            "condition": [{"text": "草稿", "attribute_id": f("PurchaseRequisition", "status")}],
            "result": [{"text": "进入待审批", "attribute_id": f("PurchaseRequisition", "status")}],
            "constraint": [{"text": "数量仍须大于 0", "attribute_id": f("PurchaseRequisition", "qty")}],
        },
        "REQ-003": {
            "actor": [{"text": "审批人", "node_id": n("Buyer", "entity")}],
            "action": [{"text": "审批采购申请", "node_id": n("审批采购申请")}],
            "condition": [{"text": "待审批", "attribute_id": f("PurchaseRequisition", "status")}],
            "result": [{"text": "已批准或已驳回", "attribute_id": f("PurchaseRequisition", "status")}],
            "constraint": [{"text": "提交人不得审批自己提交的申请", "node_id": n("Buyer", "entity")}],
        },
        "REQ-004": {
            "action": [{"text": "按申请创建采购订单", "node_id": n("按申请创建采购订单")}],
            "condition": [
                {"text": "申请已批准", "attribute_id": f("PurchaseRequisition", "status")},
                {"text": "供应商不得为冻结", "attribute_id": f("Supplier", "status")},
            ],
            "result": [
                {"text": "申请已转换", "attribute_id": f("PurchaseRequisition", "status")},
                {"text": "草稿订单", "node_id": n("PurchaseOrder", "entity")},
            ],
            "constraint": [{"text": "不得再次转换", "link_id": lk("PurchaseRequisition", "转换成")}],
        },
        "REQ-005": {
            "action": [{"text": "提交采购订单", "node_id": n("提交采购订单")}],
            "condition": [
                {"text": "至少一行", "node_id": n("PurchaseOrderLine", "entity")},
                {"text": "金额大于 0", "attribute_id": f("PurchaseOrder", "amount")},
            ],
            "result": [{"text": "进入待审批", "attribute_id": f("PurchaseOrder", "status")}],
            "constraint": [
                {
                    "text": "行数量不得低于最小起订量",
                    "attribute_id": f("SupplierMaterial", "minOrderQty"),
                    "link_id": lk("SupplierMaterial", "供应"),
                }
            ],
        },
        "REQ-006": {
            "actor": [{"text": "审批人", "node_id": n("Buyer", "entity")}],
            "action": [{"text": "审批采购订单", "node_id": n("审批采购订单")}],
            "condition": [{"text": "待审批", "attribute_id": f("PurchaseOrder", "status")}],
            "result": [{"text": "批准或驳回", "attribute_id": f("PurchaseOrder", "status")}],
            "constraint": [{"text": "提交人不得审批自己提交的订单", "node_id": n("Buyer", "entity")}],
        },
        "REQ-007": {
            "action": [{"text": "下达采购订单", "node_id": n("下达采购订单")}],
            "condition": [
                {"text": "已批准", "attribute_id": f("PurchaseOrder", "status")},
                {"text": "供应商状态", "attribute_id": f("Supplier", "status")},
            ],
            "result": [{"text": "已下达", "attribute_id": f("PurchaseOrder", "status")}],
            "constraint": [{"text": "此后才允许收货", "link_id": lk("PurchaseOrder", "向其采购")}],
        },
        "REQ-008": {
            "action": [{"text": "按订单收货", "node_id": n("按订单收货")}],
            "condition": [{"text": "已下达或部分收货", "attribute_id": f("PurchaseOrder", "status")}],
            "result": [{"text": "部分收货或已收货", "attribute_id": f("PurchaseOrder", "status")}],
            "constraint": [
                {
                    "text": "收货数量",
                    "attribute_id": f("PurchaseOrderLine", "receivedQty"),
                    "link_id": lk("GoodsReceipt", "针对"),
                }
            ],
        },
        "REQ-009": {
            "action": [{"text": "收货过账入库", "node_id": n("收货过账入库")}],
            "condition": [{"text": "草稿收货单", "attribute_id": f("GoodsReceipt", "status")}],
            "result": [{"text": "在库数量增加", "attribute_id": f("Inventory", "onHandQty")}],
            "constraint": [
                {
                    "text": "库存不得变为负数",
                    "attribute_id": f("Inventory", "onHandQty"),
                    "link_id": lk("Inventory", "存放于"),
                }
            ],
        },
        "REQ-010": {
            "action": [{"text": "关闭采购订单", "node_id": n("关闭采购订单")}],
            "condition": [{"text": "已收货", "attribute_id": f("PurchaseOrder", "status")}],
            "result": [{"text": "已关闭", "attribute_id": f("PurchaseOrder", "status")}],
            "constraint": [{"text": "关闭后不得再收货", "attribute_id": f("PurchaseOrderLine", "receivedQty")}],
        },
        "REQ-011": {
            "action": [{"text": "取消采购订单", "node_id": n("取消采购订单")}],
            "condition": [{"text": "尚未收货", "attribute_id": f("PurchaseOrderLine", "receivedQty")}],
            "result": [{"text": "已取消", "attribute_id": f("PurchaseOrder", "status")}],
            "constraint": [{"text": "已有收货的订单不得取消", "attribute_id": f("PurchaseOrderLine", "receivedQty")}],
        },
        "REQ-012": {
            "action": [{"text": "冻结供应商", "node_id": n("冻结供应商")}],
            "result": [{"text": "供应商冻结", "attribute_id": f("Supplier", "status")}],
            "constraint": [
                {
                    "text": "冻结后不得新建或下达",
                    "attribute_id": f("Supplier", "status"),
                    "link_id": lk("PurchaseOrder", "向其采购"),
                }
            ],
        },
    }
    bodies = {
        **{code: text for code, (_title, text) in REQS.items() if text},
        "REQ-007": REQ_007,
        "REQ-008": REQ_008,
        "REQ-009": REQ_009,
    }
    for code, (title, _text) in REQS.items():
        add(code, title, bodies[code], common[code])
