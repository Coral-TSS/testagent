"""Request and response schemas for the supply-chain demo API registry.

Shapes follow ``examples/supply_chain/api.py`` and ``service.py``: path and query
parameters, JSON bodies, and the fields those handlers actually return.
"""

from __future__ import annotations


def _str() -> dict:
    return {"type": "string"}


def _num() -> dict:
    return {"type": "number"}


def _bool() -> dict:
    return {"type": "boolean"}


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _array(items: dict) -> dict:
    return {"type": "array", "items": items}


def _enum(values: list[str]) -> dict:
    return {"type": "string", "enum": values}


def _param(name: str, where: str, schema: dict, *, required: bool) -> dict:
    return {"name": name, "in": where, "required": required, "schema": schema}


def _request(*, parameters: list[dict] | None = None, body: dict | None = None) -> dict:
    out: dict = {}
    if parameters:
        out["parameters"] = parameters
    if body is not None:
        out["body"] = body
    return out


def _response(code: str, schema: dict, description: str) -> dict:
    return {code: {"description": description, "schema": schema}}


_REQ_STATUS = _enum(["draft", "submitted", "approved", "rejected", "converted"])
_ORDER_STATUS = _enum(
    [
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
)
_RECEIPT_STATUS = _enum(["draft", "posted"])
_SUPPLIER_STATUS = _enum(["potential", "qualified", "frozen"])
_INSPECTION_RESULT = _enum(["pending", "passed", "failed"])

REQUISITION = _obj(
    {
        "id": _str(),
        "code": _str(),
        "materialId": _str(),
        "materialCode": _str(),
        "qty": _num(),
        "needByDate": _str(),
        "status": _REQ_STATUS,
        "buyerId": _str(),
        "supplierId": _str(),
    },
    ["id", "code", "materialId", "qty", "status", "buyerId"],
)

ORDER_LINE = _obj(
    {
        "id": _str(),
        "materialId": _str(),
        "orderedQty": _num(),
        "receivedQty": _num(),
        "unitPrice": _num(),
    },
    ["id", "materialId", "orderedQty", "receivedQty", "unitPrice"],
)

ORDER = _obj(
    {
        "id": _str(),
        "code": _str(),
        "supplierId": _str(),
        "buyerId": _str(),
        "requisitionId": _str(),
        "amount": _num(),
        "currency": _str(),
        "needByDate": _str(),
        "status": _ORDER_STATUS,
        "overReceiveTolerancePct": _num(),
        "lines": _array(ORDER_LINE),
    },
    ["id", "code", "supplierId", "amount", "currency", "status", "overReceiveTolerancePct", "lines"],
)

RECEIPT = _obj(
    {
        "id": _str(),
        "code": _str(),
        "orderId": _str(),
        "lineId": _str(),
        "warehouseId": _str(),
        "materialId": _str(),
        "receivedQty": _num(),
        "status": _RECEIPT_STATUS,
    },
    ["id", "code", "orderId", "lineId", "warehouseId", "materialId", "receivedQty", "status"],
)

SUPPLIER = _obj(
    {"id": _str(), "code": _str(), "name": _str(), "status": _SUPPLIER_STATUS},
    ["id", "code", "name", "status"],
)

INSPECTION = _obj(
    {
        "id": _str(),
        "code": _str(),
        "receiptId": _str(),
        "materialId": _str(),
        "result": _INSPECTION_RESULT,
        "defectQty": _num(),
    },
    ["id", "code", "receiptId", "materialId", "result", "defectQty"],
)

INVENTORY = _obj(
    {
        "id": _str(),
        "materialId": _str(),
        "materialCode": _str(),
        "warehouseId": _str(),
        "warehouseCode": _str(),
        "onHandQty": _num(),
        "reservedQty": _num(),
    },
    ["id", "materialId", "materialCode", "warehouseId", "warehouseCode", "onHandQty", "reservedQty"],
)

_REQ_IN = _obj(
    {
        "materialId": _str(),
        "qty": _num(),
        "buyerId": _str(),
        "supplierId": _str(),
        "needByDate": _str(),
    },
    ["materialId", "qty", "buyerId"],
)
_SUBMIT_IN = _obj({"buyerId": _str()}, ["buyerId"])
_DECISION_IN = _obj({"approverId": _str(), "approved": _bool()}, ["approverId", "approved"])
_ORDER_IN = _obj(
    {
        "requisitionId": _str(),
        "buyerId": _str(),
        "currency": _str(),
        "overReceiveTolerancePct": _num(),
    },
    ["requisitionId", "buyerId", "currency"],
)
_RECEIVE_IN = _obj(
    {"lineId": _str(), "warehouseId": _str(), "receivedQty": _num()},
    ["lineId", "warehouseId", "receivedQty"],
)
_INSPECTION_IN = _obj({"passed": _bool(), "defectQty": _num()}, ["passed"])


def _path(name: str) -> list[dict]:
    return [_param(name, "path", _str(), required=True)]


# One registry per system. v1 uses the purchase/warehouse endpoints; inspection endpoints are v2-only.
API_SPECS = [
    {
        "method": "POST",
        "path": "/sample/requisitions",
        "name": "新建采购申请",
        "request_schema": _request(body=_REQ_IN),
        "response_schema": _response("201", REQUISITION, "已创建的采购申请"),
    },
    {
        "method": "POST",
        "path": "/sample/requisitions/{req_id}/submit",
        "name": "提交采购申请",
        "request_schema": _request(parameters=_path("req_id"), body=_SUBMIT_IN),
        "response_schema": _response("200", REQUISITION, "提交后的采购申请"),
    },
    {
        "method": "POST",
        "path": "/sample/requisitions/{req_id}/decision",
        "name": "审批采购申请",
        "request_schema": _request(parameters=_path("req_id"), body=_DECISION_IN),
        "response_schema": _response("200", REQUISITION, "审批后的采购申请"),
    },
    {
        "method": "POST",
        "path": "/sample/orders",
        "name": "按申请创建采购订单",
        "request_schema": _request(body=_ORDER_IN),
        "response_schema": _response("201", ORDER, "已创建的采购订单"),
    },
    {
        "method": "POST",
        "path": "/sample/orders/{order_id}/submit",
        "name": "提交采购订单",
        "request_schema": _request(parameters=_path("order_id"), body=_SUBMIT_IN),
        "response_schema": _response("200", ORDER, "提交后的采购订单"),
    },
    {
        "method": "POST",
        "path": "/sample/orders/{order_id}/decision",
        "name": "审批采购订单",
        "request_schema": _request(parameters=_path("order_id"), body=_DECISION_IN),
        "response_schema": _response("200", ORDER, "审批后的采购订单"),
    },
    {
        "method": "POST",
        "path": "/sample/orders/{order_id}/issue",
        "name": "下达采购订单",
        "request_schema": _request(parameters=_path("order_id")),
        "response_schema": _response("200", ORDER, "已下达的采购订单"),
    },
    {
        "method": "POST",
        "path": "/sample/orders/{order_id}/receive",
        "name": "按订单收货",
        "request_schema": _request(parameters=_path("order_id"), body=_RECEIVE_IN),
        "response_schema": _response("201", RECEIPT, "已创建的收货单"),
    },
    {
        "method": "POST",
        "path": "/sample/receipts/{receipt_id}/post",
        "name": "收货过账入库",
        "request_schema": _request(parameters=_path("receipt_id")),
        "response_schema": _response("200", RECEIPT, "过账后的收货单"),
    },
    {
        "method": "POST",
        "path": "/sample/orders/{order_id}/close",
        "name": "关闭采购订单",
        "request_schema": _request(parameters=_path("order_id")),
        "response_schema": _response("200", ORDER, "已关闭的采购订单"),
    },
    {
        "method": "POST",
        "path": "/sample/orders/{order_id}/cancel",
        "name": "取消采购订单",
        "request_schema": _request(parameters=_path("order_id")),
        "response_schema": _response("200", ORDER, "已取消的采购订单"),
    },
    {
        "method": "POST",
        "path": "/sample/suppliers/{supplier_id}/freeze",
        "name": "冻结供应商",
        "request_schema": _request(parameters=_path("supplier_id")),
        "response_schema": _response("200", SUPPLIER, "冻结后的供应商"),
    },
    {
        "method": "GET",
        "path": "/sample/inventory",
        "name": "查询库存",
        "request_schema": _request(
            parameters=[
                _param("materialId", "query", _str(), required=False),
                _param("warehouseId", "query", _str(), required=False),
            ]
        ),
        "response_schema": _response("200", _array(INVENTORY), "库存列表"),
    },
    {
        "method": "POST",
        "path": "/sample/receipts/{receipt_id}/inspections",
        "name": "创建质检单",
        "request_schema": _request(parameters=_path("receipt_id")),
        "response_schema": _response("201", INSPECTION, "已创建的质检单"),
    },
    {
        "method": "POST",
        "path": "/sample/inspections/{inspection_id}/decision",
        "name": "判定质检",
        "request_schema": _request(parameters=_path("inspection_id"), body=_INSPECTION_IN),
        "response_schema": _response("200", INSPECTION, "判定后的质检单"),
    },
]
