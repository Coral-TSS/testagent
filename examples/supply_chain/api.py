"""供应链执行演示。

从仓库根目录启动::

    uv run uvicorn examples.supply_chain.api:create_app --factory --host 127.0.0.1 --port 8766
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from examples.supply_chain.service import SPACE, SupplyChainService

STATIC = Path(__file__).resolve().parent / "static"


class ReqIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    materialId: str
    qty: float = Field(gt=0)
    buyerId: str
    supplierId: str | None = None
    needByDate: str | None = None


class SubmitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buyerId: str


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approverId: str
    approved: bool


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requisitionId: str
    buyerId: str
    currency: str
    overReceiveTolerancePct: float = 0


class ReceiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lineId: str
    warehouseId: str
    receivedQty: float = Field(gt=0)


OrderStatus = Literal[
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "issued",
    "partial_received",
    "received",
    "closed",
    "cancelled",
]


class OrderLineOut(BaseModel):
    id: str
    materialId: str
    orderedQty: float
    receivedQty: float
    unitPrice: float


class OrderOut(BaseModel):
    id: str
    code: str
    supplierId: str
    buyerId: str | None = None
    requisitionId: str | None = None
    amount: float
    currency: str
    needByDate: str | None = None
    status: OrderStatus
    overReceiveTolerancePct: float
    lines: list[OrderLineOut]


class InspectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    defectQty: float = 0


def _call(fn):
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def create_app(database: Path | None = None) -> FastAPI:
    if database is None:
        database = Path(os.environ.get("SUPPLY_CHAIN_DB", "runtime/supply_chain.db"))
    database = Path(database)
    sample = SupplyChainService(database)
    app = FastAPI(title="供应链执行（演示）", version="2.0.0")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.post("/sample/reset", summary="重置演示数据", tags=["演示"])
    def reset():
        return sample.reset()

    @app.get("/sample/materials", summary="物料列表", tags=["主数据"])
    def materials():
        return sample.materials()

    @app.get("/sample/suppliers", summary="供应商列表", tags=["主数据"])
    def suppliers():
        return sample.suppliers()

    @app.get("/sample/buyers", summary="采购员列表", tags=["主数据"])
    def buyers():
        return sample.buyers()

    @app.get("/sample/warehouses", summary="仓库列表", tags=["主数据"])
    def warehouses():
        return sample.warehouses()

    @app.get("/sample/inventory", summary="查询库存", tags=["仓储"])
    def inventory(materialId: str | None = None, warehouseId: str | None = None):
        return sample.inventory(materialId, warehouseId)

    @app.get("/sample/requisitions", summary="采购申请列表", tags=["采购"])
    def requisitions():
        return sample.requisitions()

    @app.post("/sample/requisitions", status_code=201, summary="新建采购申请", tags=["采购"])
    def create_requisition(body: ReqIn):
        return _call(
            lambda: sample.create_requisition(body.materialId, body.qty, body.buyerId, body.supplierId, body.needByDate)
        )

    @app.post("/sample/requisitions/{req_id}/submit", summary="提交采购申请", tags=["采购"])
    def submit_requisition(req_id: str, body: SubmitIn):
        return _call(lambda: sample.submit_requisition(req_id, body.buyerId))

    @app.post("/sample/requisitions/{req_id}/decision", summary="审批采购申请", tags=["采购"])
    def decide_requisition(req_id: str, body: DecisionIn):
        return _call(lambda: sample.decide_requisition(req_id, body.approverId, body.approved))

    @app.get("/sample/orders", summary="采购订单列表", tags=["采购"])
    def orders():
        return sample.orders()

    @app.post(
        "/sample/orders",
        status_code=201,
        summary="按申请创建采购订单",
        description="已批准的采购申请转换成草稿采购订单。供应商不得为冻结。",
        response_model=OrderOut,
        tags=["采购"],
    )
    def create_order(body: OrderIn):
        return _call(
            lambda: sample.create_order_from_requisition(
                body.requisitionId, body.buyerId, body.currency, body.overReceiveTolerancePct
            )
        )

    @app.post("/sample/orders/{order_id}/submit", summary="提交采购订单", tags=["采购"])
    def submit_order(order_id: str, body: SubmitIn):
        return _call(lambda: sample.submit_order(order_id, body.buyerId))

    @app.post(
        "/sample/orders/{order_id}/decision",
        summary="审批采购订单",
        description="待审批的采购订单可由审批人批准或驳回。提交人不得审批自己提交的订单。",
        tags=["采购"],
    )
    def decide_order(order_id: str, body: DecisionIn):
        return _call(lambda: sample.decide_order(order_id, body.approverId, body.approved))

    @app.post("/sample/orders/{order_id}/issue", summary="下达采购订单", tags=["采购"])
    def issue_order(order_id: str):
        return _call(lambda: sample.issue_order(order_id))

    @app.post(
        "/sample/orders/{order_id}/receive",
        status_code=201,
        summary="按订单收货",
        description="按订单收货，收货数量必须大于 0。",
        tags=["仓储"],
    )
    def receive(order_id: str, body: ReceiveIn):
        return _call(lambda: sample.receive(order_id, body.lineId, body.warehouseId, body.receivedQty))

    @app.post("/sample/orders/{order_id}/close", summary="关闭采购订单", tags=["采购"])
    def close_order(order_id: str):
        return _call(lambda: sample.close_order(order_id))

    @app.post("/sample/orders/{order_id}/cancel", summary="取消采购订单", tags=["采购"])
    def cancel_order(order_id: str):
        return _call(lambda: sample.cancel_order(order_id))

    @app.post("/sample/receipts/{receipt_id}/post", summary="收货过账入库", tags=["仓储"])
    def post_receipt(receipt_id: str):
        return _call(lambda: sample.post_receipt(receipt_id))

    @app.post("/sample/receipts/{receipt_id}/inspections", status_code=201, summary="创建质检单", tags=["质检"])
    def create_inspection(receipt_id: str):
        return _call(lambda: sample.create_inspection(receipt_id))

    @app.post("/sample/inspections/{inspection_id}/decision", summary="判定质检", tags=["质检"])
    def decide_inspection(inspection_id: str, body: InspectionIn):
        return _call(lambda: sample.decide_inspection(inspection_id, body.passed, body.defectQty))

    @app.post("/sample/suppliers/{supplier_id}/freeze", summary="冻结供应商", tags=["主数据"])
    def freeze_supplier(supplier_id: str):
        return _call(lambda: sample.freeze_supplier(supplier_id))

    class _SpaceRewrite:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                match = re.match(r"^/sample/spaces/([A-Za-z][A-Za-z0-9_-]{0,63})(/.*)?$", scope.get("path", ""))
                if match:
                    scope = dict(scope)
                    scope["path"] = "/sample" + (match.group(2) or "")
                    scope["raw_path"] = scope["path"].encode()
                    token = SPACE.set(match.group(1))
                    try:
                        await self.app(scope, receive, send)
                    finally:
                        SPACE.reset(token)
                    return
            await self.app(scope, receive, send)

    app.add_middleware(_SpaceRewrite)
    return app
