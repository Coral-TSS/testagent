"""Procurement approval demo (example SUT): suppliers, purchase orders, approval and payments.

Not part of the TestAgent platform. Start it from the repository root with
``uv run uvicorn examples.procurement.api:create_app --factory --host 127.0.0.1 --port 8766``.
"""

import re
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from examples.procurement.service import ProcurementService, env_flag

State = Literal["unknown", "pending", "approved", "rejected", "paid"]
STATE_TEXT = (
    "States: unknown cannot be decided (unknown amount or not CNY, cannot be paid) / pending awaiting approval / "
    "approved "
    "(small amount auto-approved, or approved) / rejected / paid"
)


class SupplierInput(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={"examples": [{"name": "Grand Stationery Co.", "contact": "Manager Zhao 555-0100"}]},
    )
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="Supplier name, must be unique",
            examples=["Grand Stationery Co."],
        ),
    ]
    contact: Annotated[
        str | None,
        Field(max_length=100, description="Contact person and phone (optional)", examples=["Manager Zhao 555-0100"]),
    ] = None


class SupplierOut(BaseModel):
    id: Annotated[str, Field(description="Supplier ID (UUID)")]
    name: Annotated[str, Field(description="Supplier name")]
    contact: Annotated[str | None, Field(description="Contact person and phone")] = None
    created_at: Annotated[str, Field(description="Created at (UTC, ISO 8601)")]


class OrderInput(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "title": "Buy 20 laptops",
                    "supplier_id": " (call GET /sample/suppliers first to get an id)",
                    "amount_minor": 12000000,
                    "currency": "CNY",
                }
            ]
        },
    )
    amount_minor: Annotated[
        int | None,
        Field(
            ge=0,
            description="Amount as an integer in cents (50000.00 = 5000000); null when unknown",
            examples=[5000000],
        ),
    ] = None
    currency: Annotated[
        str, Field(description="Currency, e.g. CNY; the approval rule only applies to CNY", examples=["CNY"])
    ]
    title: Annotated[
        str | None,
        Field(max_length=100, description="Purpose (optional)", examples=["Buy 20 laptops"]),
    ] = None
    supplier_id: Annotated[
        str | None,
        Field(
            description="Supplier ID (foreign key → Supplier.id); 422 if it does not exist; may be empty (no supplier)"
        ),
    ] = None


class OrderOut(BaseModel):
    id: Annotated[str, Field(description="Purchase order ID (UUID)")]
    title: Annotated[str | None, Field(description="Purpose")] = None
    supplier_id: Annotated[str | None, Field(description="Supplier ID (foreign key → Supplier.id)")] = None
    supplier_name: Annotated[str | None, Field(description="Supplier name")] = None
    amount_minor: Annotated[int | None, Field(description="Amount in cents; null when unknown")]
    currency: Annotated[str, Field(description="Currency")]
    approval_required: Annotated[
        bool | None,
        Field(description="Whether approval is required (CNY and amount ≥ 50000.00); null when it cannot be decided"),
    ]
    state: Annotated[State, Field(description=STATE_TEXT)]
    created_at: Annotated[str, Field(description="Created at (UTC, ISO 8601)")]


class DecisionInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", json_schema_extra={"examples": [{"approved": True}]})
    approved: Annotated[bool, Field(description="true = approve, false = reject")]


class DecisionOut(BaseModel):
    recorded: Annotated[bool, Field(description="Approval decision recorded")]


class PaymentInput(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={"examples": [{"callback_id": "cb-20261102-001"}]},
    )
    callback_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description="Payment callback id; re-submitting the same id is idempotent and returns the original record",
        ),
    ]


class PaymentOut(BaseModel):
    id: Annotated[str, Field(description="Payment ID (UUID)")]
    order_id: Annotated[str, Field(description="Purchase order ID (foreign key → PurchaseOrder.id)")]
    callback_id: Annotated[str, Field(description="Payment callback id")]
    amount: Annotated[int | None, Field(description="Paid amount in cents")]
    paid_at: Annotated[str, Field(description="Paid at (UTC, ISO 8601)")]


class ResetOut(BaseModel):
    reset: Annotated[bool, Field(description="Cleared")]
    suppliers: Annotated[int, Field(description="Number of default suppliers written again")]


class SpaceResetInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    confirm_space: str


OrderId = Annotated[str, PathParam(description="Purchase order ID (the id returned when the order was created)")]
SupplierId = Annotated[str, PathParam(description="Supplier ID")]
Space = Annotated[str, PathParam(description="Test space name")]


def _conflict(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, str(exc).strip("'\""))
    return HTTPException(409, str(exc))


def create_app(database: Path = Path("runtime/sample.db"), *, demo_bugs: bool | None = None) -> FastAPI:
    database.parent.mkdir(parents=True, exist_ok=True)
    bugs = env_flag("PROCUREMENT_DEMO_BUGS", True) if demo_bugs is None else demo_bugs
    sample = ProcurementService(database, demo_bugs=bugs)
    if env_flag("PROCUREMENT_RESET_ON_START", False):
        sample.reset()
    app = FastAPI(
        title="Procurement approval demo",
        version="2.0.0",
        description=(
            "The example SUT for TestAgent: suppliers, purchase orders, approval and payments. UI at /, API docs at "
            "/docs. "
            "Rules: CNY with amount ≥ 50000.00 needs approval, below that it is auto-approved; only approved "
            "purchase orders can be paid, "
            "and only once (re-submitting the same callback id returns the original record)."
        ),
        openapi_tags=[
            {"name": "Supplier", "description": "Query and create suppliers"},
            {"name": "PurchaseOrder", "description": "Create, query and approve purchase orders"},
            {"name": "Payments", "description": "Record and query payments"},
            {"name": "Demo data", "description": "Reset demo data for repeatable tests"},
        ],
    )
    static = Path(__file__).parent / "static"
    app.mount("/assets", StaticFiles(directory=static), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        html = (static / "index.html").read_text(encoding="utf-8")
        flag = f"<script>window.DEMO_BUGS = {'true' if bugs else 'false'};</script>"
        return HTMLResponse(html.replace("<!--DEMO_BUGS-->", flag))

    # ---------------------------------------------------------------- suppliers
    @app.get(
        "/sample/suppliers",
        tags=["Supplier"],
        summary="List suppliers",
        description="List all suppliers (in creation order). The demo data has 3 suppliers by default.",
        response_model=list[SupplierOut],
    )
    def list_suppliers():
        return sample.suppliers()

    @app.post(
        "/sample/suppliers",
        status_code=201,
        tags=["Supplier"],
        summary="Create supplier",
        description="Create a supplier; the name cannot be empty or duplicated (a duplicate returns 409).",
        response_model=SupplierOut,
    )
    def create_supplier(body: SupplierInput):
        try:
            return sample.create_supplier(body.name, body.contact)
        except KeyError as exc:
            raise HTTPException(409, exc.args[0]) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get(
        "/sample/suppliers/{supplier_id}",
        tags=["Supplier"],
        summary="Get supplier",
        description="Read a supplier by ID; 404 if it does not exist.",
        response_model=SupplierOut,
    )
    def get_supplier(supplier_id: SupplierId):
        row = sample.supplier(supplier_id)
        if row is None:
            raise HTTPException(404, "Supplier not found")
        return row

    # ---------------------------------------------------------------- orders
    @app.get(
        "/sample/orders",
        tags=["PurchaseOrder"],
        summary="List purchase orders",
        description="List purchase orders, newest first; filter by state or supplier.",
        response_model=list[OrderOut],
    )
    def list_orders(
        state: Annotated[State | None, Query(description="Filter by state")] = None,
        supplier_id: Annotated[str | None, Query(description="Filter by supplier ID")] = None,
    ):
        return sample.orders(state=state, supplier_id=supplier_id)

    @app.post(
        "/sample/orders",
        status_code=201,
        tags=["PurchaseOrder"],
        summary="Create purchase order",
        description=(
            "Create a purchase order and decide whether it needs approval by amount and currency: CNY with amount ≥ "
            "50000.00 becomes pending approval "
            "(pending), below that it is auto-approved (approved); unknown amount or a non-CNY currency cannot be "
            "decided (unknown). "
            "supplier_id must be an existing supplier."
        ),
        response_model=OrderOut,
    )
    def create_order(body: OrderInput):
        try:
            return sample.create_order(body.amount_minor, body.currency, supplier_id=body.supplier_id, title=body.title)
        except LookupError as exc:
            raise HTTPException(422, exc.args[0]) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get(
        "/sample/orders/{order_id}",
        tags=["PurchaseOrder"],
        summary="Get purchase order",
        description="Read one purchase order and its approval state by ID; 404 if it does not exist.",
        response_model=OrderOut,
    )
    def get_order(order_id: OrderId):
        row = sample.order(order_id)
        if row is None:
            raise HTTPException(404, "Purchase order not found")
        return row

    @app.post(
        "/sample/orders/{order_id}/decision",
        tags=["PurchaseOrder"],
        summary="Approve purchase order",
        description="Approve or reject a purchase order pending approval (pending); any other state returns 409.",
        response_model=DecisionOut,
    )
    def decide(order_id: OrderId, body: DecisionInput):
        try:
            sample.decide(order_id, approved=body.approved)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"recorded": True}

    # ---------------------------------------------------------------- payments
    @app.post(
        "/sample/orders/{order_id}/payments",
        tags=["Payments"],
        summary="Record payment",
        description=(
            "Record a payment for an approved purchase order; the order then becomes paid; re-submitting the same "
            "callback id "
            "returns the original record, paying again with a different callback id returns 409; an order that is "
            "not approved returns 409, an unknown order returns 404."
        ),
        response_model=PaymentOut,
    )
    def pay(order_id: OrderId, body: PaymentInput):
        try:
            return sample.pay(order_id, body.callback_id)
        except (LookupError, ValueError) as exc:
            raise _conflict(exc) from exc

    @app.get(
        "/sample/orders/{order_id}/payments",
        tags=["Payments"],
        summary="List payments",
        description="List the payments of this purchase order (in payment order).",
        response_model=list[PaymentOut],
    )
    def payments(order_id: OrderId):
        return sample.payments(order_id)

    @app.post(
        "/sample/reset",
        tags=["Demo data"],
        summary="Reset demo data",
        description=(
            "Clear all purchase orders, payments and suppliers, then write the 3 default suppliers again. Call it "
            "before testing for repeatable results."
        ),
        response_model=ResetOut,
    )
    def reset():
        return {"reset": True, "suppliers": sample.reset()}

    # ------------------------------------------- isolated spaces (kept for scripts, hidden)
    def space_sample(space: Space) -> ProcurementService:
        reserved = {"con", "prn", "aux", "nul"} | {f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)}
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", space) or space in reserved:
            raise HTTPException(422, "invalid sample space")
        root = database.parent / (database.stem + ".spaces")
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{space}.db"
        if not target.resolve().is_relative_to(root.resolve()):
            raise HTTPException(422, "sample space outside allowed directory")
        return ProcurementService(target, demo_bugs=bugs)

    Scoped = Annotated[ProcurementService, Depends(space_sample)]
    hidden = {"include_in_schema": False}

    @app.get("/sample/spaces/{space}/orders", **hidden)
    def space_orders(scoped: Scoped):
        return scoped.orders()

    @app.get("/sample/spaces/{space}/orders/{order_id}", **hidden)
    def space_order(order_id: OrderId, scoped: Scoped):
        row = scoped.order(order_id)
        if row is None:
            raise HTTPException(404, "order not found in sample space")
        return row

    @app.post("/sample/spaces/{space}/orders", status_code=201, **hidden)
    def space_create(body: OrderInput, scoped: Scoped):
        try:
            return scoped.create_order(body.amount_minor, body.currency, supplier_id=body.supplier_id, title=body.title)
        except (LookupError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/sample/spaces/{space}/orders/{order_id}/decision", **hidden)
    def space_decide(order_id: OrderId, body: DecisionInput, scoped: Scoped):
        try:
            scoped.decide(order_id, approved=body.approved)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"recorded": True}

    @app.post("/sample/spaces/{space}/orders/{order_id}/payments", **hidden)
    def space_pay(order_id: OrderId, body: PaymentInput, scoped: Scoped):
        try:
            return scoped.pay(order_id, body.callback_id)
        except (LookupError, ValueError) as exc:
            raise _conflict(exc) from exc

    @app.get("/sample/spaces/{space}/orders/{order_id}/payments", **hidden)
    def space_payments(order_id: OrderId, scoped: Scoped):
        return scoped.payments(order_id)

    @app.post("/sample/spaces/{space}/reset", **hidden)
    def space_reset(space: Space, body: SpaceResetInput, scoped: Scoped):
        if body.confirm_space != space:
            raise HTTPException(409, "reset confirmation does not match space")
        scoped.reset()
        return {"space": space, "reset": True}

    return app
