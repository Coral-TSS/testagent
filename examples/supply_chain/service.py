"""供应链执行演示的业务规则。

运行中的示例应用是已经开发完成的 v2：需要质检的物料必须质检合格才能过账，
下达订单时供应商必须为合格，收货不得超过订购数量 ×（1 + 超收容差）。
容差按小数保存（0.1 表示允许超收 10%），与需求里的公式一致。
"""

from __future__ import annotations

import contextvars
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

SPACE = contextvars.ContextVar("supply_chain_space", default="")

SCHEMA = """
CREATE TABLE IF NOT EXISTS material (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, name TEXT NOT NULL,
  unit TEXT NOT NULL, inspection_required INTEGER NOT NULL, safety_stock REAL NOT NULL,
  UNIQUE(space, code));
CREATE TABLE IF NOT EXISTS supplier (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, name TEXT NOT NULL,
  status TEXT NOT NULL, UNIQUE(space, code));
CREATE TABLE IF NOT EXISTS supplier_material (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', supplier_id TEXT NOT NULL, material_id TEXT NOT NULL,
  price REAL NOT NULL, lead_time_days INTEGER NOT NULL, min_order_qty REAL NOT NULL,
  UNIQUE(space, supplier_id, material_id));
CREATE TABLE IF NOT EXISTS warehouse (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, name TEXT NOT NULL,
  UNIQUE(space, code));
CREATE TABLE IF NOT EXISTS inventory (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', warehouse_id TEXT NOT NULL, material_id TEXT NOT NULL,
  on_hand_qty REAL NOT NULL, reserved_qty REAL NOT NULL, UNIQUE(space, warehouse_id, material_id));
CREATE TABLE IF NOT EXISTS buyer (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, name TEXT NOT NULL,
  UNIQUE(space, code));
CREATE TABLE IF NOT EXISTS requisition (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, material_id TEXT NOT NULL,
  qty REAL NOT NULL, need_by_date TEXT, status TEXT NOT NULL, buyer_id TEXT, supplier_id TEXT,
  UNIQUE(space, code));
CREATE TABLE IF NOT EXISTS purchase_order (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, supplier_id TEXT NOT NULL,
  buyer_id TEXT, requisition_id TEXT, amount REAL NOT NULL, currency TEXT NOT NULL,
  need_by_date TEXT, status TEXT NOT NULL, tolerance REAL NOT NULL DEFAULT 0, UNIQUE(space, code));
CREATE TABLE IF NOT EXISTS order_line (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', order_id TEXT NOT NULL, material_id TEXT NOT NULL,
  ordered_qty REAL NOT NULL, received_qty REAL NOT NULL, unit_price REAL NOT NULL);
CREATE TABLE IF NOT EXISTS receipt (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, order_id TEXT NOT NULL,
  line_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, material_id TEXT NOT NULL,
  received_qty REAL NOT NULL, status TEXT NOT NULL, UNIQUE(space, code));
CREATE TABLE IF NOT EXISTS inspection (
  id TEXT PRIMARY KEY, space TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, receipt_id TEXT NOT NULL,
  material_id TEXT NOT NULL, result TEXT NOT NULL, defect_qty REAL NOT NULL DEFAULT 0, UNIQUE(space, code));
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _id() -> str:
    return str(uuid4())


class SupplyChainService:
    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database, timeout=10)
        try:
            db.executescript(SCHEMA)
            db.commit()
        finally:
            db.close()
        with self._connect():
            pass

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            space = self._space()
            if not db.execute("SELECT 1 FROM material WHERE space=? LIMIT 1", (space,)).fetchone():
                self._seed(db, space)
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _space(self) -> str:
        return SPACE.get()

    def reset(self) -> dict:
        space = self._space()
        with self._connect() as db:
            for table in (
                "inspection",
                "receipt",
                "order_line",
                "purchase_order",
                "requisition",
                "inventory",
                "supplier_material",
                "buyer",
                "warehouse",
                "supplier",
                "material",
            ):
                db.execute(f"DELETE FROM {table} WHERE space=?", (space,))
            self._seed(db, space)
        return {"reset": True, "space": space or "default"}

    def _seed(self, db, space: str) -> None:
        materials = [
            ("MAT-STD", "普通件", "PCS", 0, 10),
            ("MAT-QC", "需质检件", "PCS", 1, 5),
            ("MAT-BULK", "大宗件", "KG", 0, 20),
        ]
        mat = {}
        for code, name, unit, inspect, safety in materials:
            mid = _id()
            mat[code] = mid
            db.execute(
                "INSERT INTO material(id, space, code, name, unit, inspection_required, safety_stock)"
                " VALUES (?,?,?,?,?,?,?)",
                (mid, space, code, name, unit, inspect, safety),
            )
        suppliers = [("SUP-OK", "合格供应商", "qualified"), ("SUP-NEW", "潜在供应商", "potential")]
        sup = {}
        for code, name, status in suppliers:
            sid = _id()
            sup[code] = sid
            db.execute(
                "INSERT INTO supplier(id, space, code, name, status) VALUES (?,?,?,?,?)",
                (sid, space, code, name, status),
            )
        for code, price, lead, moq in (("MAT-STD", 12.5, 7, 1), ("MAT-QC", 30, 14, 2)):
            db.execute(
                "INSERT INTO supplier_material(id, space, supplier_id, material_id, price, lead_time_days,"
                " min_order_qty) VALUES (?,?,?,?,?,?,?)",
                (_id(), space, sup["SUP-OK"], mat[code], price, lead, moq),
            )
        wid = _id()
        db.execute(
            "INSERT INTO warehouse(id, space, code, name) VALUES (?,?,?,?)",
            (wid, space, "WH-01", "中心仓"),
        )
        for code, qty in (("MAT-STD", 8), ("MAT-QC", 3), ("MAT-BULK", 25)):
            db.execute(
                "INSERT INTO inventory(id, space, warehouse_id, material_id, on_hand_qty, reserved_qty)"
                " VALUES (?,?,?,?,?,0)",
                (_id(), space, wid, mat[code], qty),
            )
        for code, name in (("BUY-01", "采购员甲"), ("BUY-02", "采购员乙")):
            db.execute(
                "INSERT INTO buyer(id, space, code, name) VALUES (?,?,?,?)",
                (_id(), space, code, name),
            )

    def _one(self, db, sql, args):
        return db.execute(sql, args).fetchone()

    def _must(self, row, label: str):
        if row is None:
            raise LookupError(f"{label}不存在")
        return row

    def materials(self):
        with self._connect() as db:
            return [
                self._material(r)
                for r in db.execute("SELECT * FROM material WHERE space=? ORDER BY code", (self._space(),))
            ]

    def suppliers(self):
        with self._connect() as db:
            return [
                self._supplier(r)
                for r in db.execute("SELECT * FROM supplier WHERE space=? ORDER BY code", (self._space(),))
            ]

    def buyers(self):
        with self._connect() as db:
            return [
                dict(r)
                for r in db.execute("SELECT id, code, name FROM buyer WHERE space=? ORDER BY code", (self._space(),))
            ]

    def warehouses(self):
        with self._connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id, code, name FROM warehouse WHERE space=? ORDER BY code", (self._space(),)
                )
            ]

    def inventory(self, material_id=None, warehouse_id=None):
        with self._connect() as db:
            rows = db.execute(
                "SELECT i.*, m.code AS material_code, w.code AS warehouse_code FROM inventory i"
                " JOIN material m ON m.id=i.material_id JOIN warehouse w ON w.id=i.warehouse_id"
                " WHERE i.space=? AND (? IS NULL OR i.material_id=?) AND (? IS NULL OR i.warehouse_id=?)"
                " ORDER BY w.code, m.code",
                (self._space(), material_id, material_id, warehouse_id, warehouse_id),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "materialId": r["material_id"],
                "materialCode": r["material_code"],
                "warehouseId": r["warehouse_id"],
                "warehouseCode": r["warehouse_code"],
                "onHandQty": r["on_hand_qty"],
                "reservedQty": r["reserved_qty"],
            }
            for r in rows
        ]

    def requisitions(self):
        with self._connect() as db:
            return [
                self._req(db, r)
                for r in db.execute("SELECT * FROM requisition WHERE space=? ORDER BY code", (self._space(),))
            ]

    def orders(self):
        with self._connect() as db:
            return [
                self._order(db, r)
                for r in db.execute("SELECT * FROM purchase_order WHERE space=? ORDER BY code", (self._space(),))
            ]

    def _material(self, r):
        return {
            "id": r["id"],
            "code": r["code"],
            "name": r["name"],
            "unit": r["unit"],
            "inspectionRequired": bool(r["inspection_required"]),
            "safetyStock": r["safety_stock"],
        }

    def _supplier(self, r):
        return {"id": r["id"], "code": r["code"], "name": r["name"], "status": r["status"]}

    def _req(self, db, r):
        material = db.execute("SELECT code, name FROM material WHERE id=?", (r["material_id"],)).fetchone()
        return {
            "id": r["id"],
            "code": r["code"],
            "materialId": r["material_id"],
            "materialCode": material["code"] if material else None,
            "qty": r["qty"],
            "needByDate": r["need_by_date"],
            "status": r["status"],
            "buyerId": r["buyer_id"],
            "supplierId": r["supplier_id"],
        }

    def _order(self, db, r):
        lines = [
            {
                "id": line["id"],
                "materialId": line["material_id"],
                "orderedQty": line["ordered_qty"],
                "receivedQty": line["received_qty"],
                "unitPrice": line["unit_price"],
            }
            for line in db.execute("SELECT * FROM order_line WHERE order_id=? ORDER BY id", (r["id"],))
        ]
        return {
            "id": r["id"],
            "code": r["code"],
            "supplierId": r["supplier_id"],
            "buyerId": r["buyer_id"],
            "requisitionId": r["requisition_id"],
            "amount": r["amount"],
            "currency": r["currency"],
            "needByDate": r["need_by_date"],
            "status": r["status"],
            "overReceiveTolerancePct": r["tolerance"],
            "lines": lines,
        }

    def _next(self, db, table, prefix):
        space = self._space()
        n = db.execute(f"SELECT count(*) AS n FROM {table} WHERE space=?", (space,)).fetchone()["n"] + 1
        return f"{prefix}-{n:03d}"

    def create_requisition(
        self,
        material_id: str,
        qty: float,
        buyer_id: str,
        supplier_id: str | None = None,
        need_by_date: str | None = None,
    ):
        if qty <= 0:
            raise ValueError("数量必须大于 0")
        with self._connect() as db:
            self._must(
                self._one(db, "SELECT * FROM material WHERE id=? AND space=?", (material_id, self._space())), "物料"
            )
            self._must(self._one(db, "SELECT * FROM buyer WHERE id=? AND space=?", (buyer_id, self._space())), "采购员")
            if supplier_id:
                self._must(
                    self._one(db, "SELECT * FROM supplier WHERE id=? AND space=?", (supplier_id, self._space())),
                    "供应商",
                )
            code = self._next(db, "requisition", "PR")
            rid = _id()
            db.execute(
                "INSERT INTO requisition(id, space, code, material_id, qty, need_by_date, status,"
                " buyer_id, supplier_id)"
                " VALUES (?,?,?,?,?,?, 'draft', ?, ?)",
                (rid, self._space(), code, material_id, qty, need_by_date, buyer_id, supplier_id),
            )
            row = db.execute("SELECT * FROM requisition WHERE id=?", (rid,)).fetchone()
            return self._req(db, row)

    def submit_requisition(self, req_id: str, buyer_id: str):
        with self._connect() as db:
            row = self._must(
                self._one(db, "SELECT * FROM requisition WHERE id=? AND space=?", (req_id, self._space())), "采购申请"
            )
            if row["status"] != "draft":
                raise ValueError("只有草稿申请可以提交")
            if row["qty"] <= 0:
                raise ValueError("数量必须大于 0")
            db.execute("UPDATE requisition SET status='submitted', buyer_id=? WHERE id=?", (buyer_id, req_id))
            return self._req(db, db.execute("SELECT * FROM requisition WHERE id=?", (req_id,)).fetchone())

    def decide_requisition(self, req_id: str, approver_id: str, approved: bool):
        with self._connect() as db:
            row = self._must(
                self._one(db, "SELECT * FROM requisition WHERE id=? AND space=?", (req_id, self._space())), "采购申请"
            )
            if row["status"] != "submitted":
                raise ValueError("只有待审批的申请可以审批")
            if approver_id == row["buyer_id"]:
                raise ValueError("提交人不得审批自己提交的申请")
            status = "approved" if approved else "rejected"
            db.execute("UPDATE requisition SET status=? WHERE id=?", (status, req_id))
            return self._req(db, db.execute("SELECT * FROM requisition WHERE id=?", (req_id,)).fetchone())

    def create_order_from_requisition(self, req_id: str, buyer_id: str, currency: str = "CNY", tolerance: float = 0):
        if tolerance < 0:
            raise ValueError("超收容差不能为负")
        with self._connect() as db:
            req = self._must(
                self._one(db, "SELECT * FROM requisition WHERE id=? AND space=?", (req_id, self._space())), "采购申请"
            )
            if req["status"] != "approved":
                raise ValueError("只有已批准的申请可以转换成订单")
            if not req["supplier_id"]:
                raise ValueError("创建订单需要供应商")
            supplier = self._must(self._one(db, "SELECT * FROM supplier WHERE id=?", (req["supplier_id"],)), "供应商")
            if supplier["status"] == "frozen":
                raise ValueError("冻结供应商不能用于新建采购订单")
            offer = self._one(
                db,
                "SELECT * FROM supplier_material WHERE supplier_id=? AND material_id=? AND space=?",
                (req["supplier_id"], req["material_id"], self._space()),
            )
            if offer is None:
                raise ValueError("该供应商物料不存在")
            if req["qty"] < offer["min_order_qty"]:
                raise ValueError("行数量不得低于最小起订量")
            amount = round(req["qty"] * offer["price"], 2)
            if amount <= 0:
                raise ValueError("金额必须大于 0")
            oid = _id()
            code = self._next(db, "purchase_order", "PO")
            db.execute(
                "INSERT INTO purchase_order(id, space, code, supplier_id, buyer_id, requisition_id, amount,"
                " currency, need_by_date, status, tolerance) VALUES (?,?,?,?,?,?,?,?,?, 'draft', ?)",
                (
                    oid,
                    self._space(),
                    code,
                    req["supplier_id"],
                    buyer_id,
                    req_id,
                    amount,
                    currency,
                    req["need_by_date"],
                    tolerance,
                ),
            )
            db.execute(
                "INSERT INTO order_line(id, space, order_id, material_id, ordered_qty, received_qty, unit_price)"
                " VALUES (?,?,?,?,?,0,?)",
                (_id(), self._space(), oid, req["material_id"], req["qty"], offer["price"]),
            )
            db.execute("UPDATE requisition SET status='converted' WHERE id=?", (req_id,))
            return self._order(db, db.execute("SELECT * FROM purchase_order WHERE id=?", (oid,)).fetchone())

    def submit_order(self, order_id: str, buyer_id: str):
        with self._connect() as db:
            order = self._must(
                self._one(db, "SELECT * FROM purchase_order WHERE id=? AND space=?", (order_id, self._space())),
                "采购订单",
            )
            if order["status"] != "draft":
                raise ValueError("只有草稿订单可以提交")
            lines = db.execute("SELECT * FROM order_line WHERE order_id=?", (order_id,)).fetchall()
            if not lines or order["amount"] <= 0:
                raise ValueError("草稿采购订单至少包含一行、金额大于 0 方可提交")
            for line in lines:
                if line["ordered_qty"] <= 0 or line["unit_price"] <= 0:
                    raise ValueError("行数量和单价必须大于 0")
                offer = self._one(
                    db,
                    "SELECT * FROM supplier_material WHERE supplier_id=? AND material_id=? AND space=?",
                    (order["supplier_id"], line["material_id"], self._space()),
                )
                if offer and line["ordered_qty"] < offer["min_order_qty"]:
                    raise ValueError("行数量不得低于最小起订量")
            db.execute(
                "UPDATE purchase_order SET status='pending_approval', buyer_id=? WHERE id=?", (buyer_id, order_id)
            )
            return self._order(db, db.execute("SELECT * FROM purchase_order WHERE id=?", (order_id,)).fetchone())

    def decide_order(self, order_id: str, approver_id: str, approved: bool):
        with self._connect() as db:
            order = self._must(
                self._one(db, "SELECT * FROM purchase_order WHERE id=? AND space=?", (order_id, self._space())),
                "采购订单",
            )
            if order["status"] != "pending_approval":
                raise ValueError("只有待审批的订单可以审批")
            if approver_id == order["buyer_id"]:
                raise ValueError("提交人不得审批自己提交的订单")
            status = "approved" if approved else "rejected"
            db.execute("UPDATE purchase_order SET status=? WHERE id=?", (status, order_id))
            return self._order(db, db.execute("SELECT * FROM purchase_order WHERE id=?", (order_id,)).fetchone())

    def issue_order(self, order_id: str):
        with self._connect() as db:
            order = self._must(
                self._one(db, "SELECT * FROM purchase_order WHERE id=? AND space=?", (order_id, self._space())),
                "采购订单",
            )
            if order["status"] != "approved":
                raise ValueError("只有已批准的订单可以下达")
            supplier = self._must(self._one(db, "SELECT * FROM supplier WHERE id=?", (order["supplier_id"],)), "供应商")
            if supplier["status"] != "qualified":
                raise ValueError("供应商必须为合格")
            db.execute("UPDATE purchase_order SET status='issued' WHERE id=?", (order_id,))
            return self._order(db, db.execute("SELECT * FROM purchase_order WHERE id=?", (order_id,)).fetchone())

    def _max_receive(self, ordered, tolerance):
        return ordered * (1 + tolerance)

    def receive(self, order_id: str, line_id: str, warehouse_id: str, qty: float):
        if qty <= 0:
            raise ValueError("收货数量必须大于 0")
        with self._connect() as db:
            order = self._must(
                self._one(db, "SELECT * FROM purchase_order WHERE id=? AND space=?", (order_id, self._space())),
                "采购订单",
            )
            if order["status"] not in ("issued", "partial_received"):
                raise ValueError("已取消或已关闭的订单不得收货，且须已下达")
            line = self._must(
                self._one(db, "SELECT * FROM order_line WHERE id=? AND order_id=?", (line_id, order_id)), "订单行"
            )
            self._must(
                self._one(db, "SELECT * FROM warehouse WHERE id=? AND space=?", (warehouse_id, self._space())), "仓库"
            )
            if line["received_qty"] + qty > self._max_receive(line["ordered_qty"], order["tolerance"]) + 1e-9:
                raise ValueError("累计收货数量不得超过允许上限")
            received = line["received_qty"] + qty
            db.execute("UPDATE order_line SET received_qty=? WHERE id=?", (received, line_id))
            rid = _id()
            code = self._next(db, "receipt", "GR")
            db.execute(
                "INSERT INTO receipt(id, space, code, order_id, line_id, warehouse_id, material_id,"
                " received_qty, status)"
                " VALUES (?,?,?,?,?,?,?,?, 'draft')",
                (rid, self._space(), code, order_id, line_id, warehouse_id, line["material_id"], qty),
            )
            lines = db.execute("SELECT * FROM order_line WHERE order_id=?", (order_id,)).fetchall()
            complete = all(line["received_qty"] + 1e-9 >= line["ordered_qty"] for line in lines)
            db.execute(
                "UPDATE purchase_order SET status=? WHERE id=?",
                ("received" if complete else "partial_received", order_id),
            )
            receipt = db.execute("SELECT * FROM receipt WHERE id=?", (rid,)).fetchone()
            return self._receipt(db, receipt)

    def _receipt(self, db, r):
        return {
            "id": r["id"],
            "code": r["code"],
            "orderId": r["order_id"],
            "lineId": r["line_id"],
            "warehouseId": r["warehouse_id"],
            "materialId": r["material_id"],
            "receivedQty": r["received_qty"],
            "status": r["status"],
        }

    def post_receipt(self, receipt_id: str):
        with self._connect() as db:
            receipt = self._must(
                self._one(db, "SELECT * FROM receipt WHERE id=? AND space=?", (receipt_id, self._space())), "收货单"
            )
            if receipt["status"] != "draft":
                raise ValueError("只有草稿收货单可以过账")
            material = self._must(self._one(db, "SELECT * FROM material WHERE id=?", (receipt["material_id"],)), "物料")
            if material["inspection_required"]:
                passed = self._one(
                    db,
                    "SELECT 1 FROM inspection WHERE receipt_id=? AND result='passed'",
                    (receipt_id,),
                )
                if passed is None:
                    raise ValueError("需要质检的物料须质检合格后方可过账入库")
            inv = self._one(
                db,
                "SELECT * FROM inventory WHERE warehouse_id=? AND material_id=? AND space=?",
                (receipt["warehouse_id"], receipt["material_id"], self._space()),
            )
            on_hand = (inv["on_hand_qty"] if inv else 0) + receipt["received_qty"]
            if on_hand < 0:
                raise ValueError("库存不得变为负数")
            if inv:
                db.execute("UPDATE inventory SET on_hand_qty=? WHERE id=?", (on_hand, inv["id"]))
            else:
                db.execute(
                    "INSERT INTO inventory(id, space, warehouse_id, material_id, on_hand_qty, reserved_qty)"
                    " VALUES (?,?,?,?,?,0)",
                    (_id(), self._space(), receipt["warehouse_id"], receipt["material_id"], on_hand),
                )
            db.execute("UPDATE receipt SET status='posted' WHERE id=?", (receipt_id,))
            return self._receipt(db, db.execute("SELECT * FROM receipt WHERE id=?", (receipt_id,)).fetchone())

    def close_order(self, order_id: str):
        with self._connect() as db:
            order = self._must(
                self._one(db, "SELECT * FROM purchase_order WHERE id=? AND space=?", (order_id, self._space())),
                "采购订单",
            )
            lines = db.execute("SELECT * FROM order_line WHERE order_id=?", (order_id,)).fetchall()
            if order["status"] != "received":
                raise ValueError("只有已收货的订单可以关闭")
            for line in lines:
                if line["received_qty"] + 1e-9 < line["ordered_qty"]:
                    raise ValueError("各行须在收货规则内收齐")
                if line["received_qty"] > self._max_receive(line["ordered_qty"], order["tolerance"]) + 1e-9:
                    raise ValueError("收货数量超出允许上限")
            db.execute("UPDATE purchase_order SET status='closed' WHERE id=?", (order_id,))
            return self._order(db, db.execute("SELECT * FROM purchase_order WHERE id=?", (order_id,)).fetchone())

    def cancel_order(self, order_id: str):
        with self._connect() as db:
            order = self._must(
                self._one(db, "SELECT * FROM purchase_order WHERE id=? AND space=?", (order_id, self._space())),
                "采购订单",
            )
            if order["status"] not in ("draft", "pending_approval", "approved", "issued"):
                raise ValueError("当前状态的订单不能取消")
            lines = db.execute("SELECT * FROM order_line WHERE order_id=?", (order_id,)).fetchall()
            if any(line["received_qty"] != 0 for line in lines):
                raise ValueError("已有收货的订单不得取消")
            db.execute("UPDATE purchase_order SET status='cancelled' WHERE id=?", (order_id,))
            return self._order(db, db.execute("SELECT * FROM purchase_order WHERE id=?", (order_id,)).fetchone())

    def freeze_supplier(self, supplier_id: str):
        with self._connect() as db:
            row = self._must(
                self._one(db, "SELECT * FROM supplier WHERE id=? AND space=?", (supplier_id, self._space())), "供应商"
            )
            if row["status"] == "frozen":
                raise ValueError("供应商已冻结")
            db.execute("UPDATE supplier SET status='frozen' WHERE id=?", (supplier_id,))
            return self._supplier(db.execute("SELECT * FROM supplier WHERE id=?", (supplier_id,)).fetchone())

    def create_inspection(self, receipt_id: str):
        with self._connect() as db:
            receipt = self._must(
                self._one(db, "SELECT * FROM receipt WHERE id=? AND space=?", (receipt_id, self._space())), "收货单"
            )
            if receipt["status"] != "draft":
                raise ValueError("未过账的收货单才能创建质检单")
            material = self._must(self._one(db, "SELECT * FROM material WHERE id=?", (receipt["material_id"],)), "物料")
            if not material["inspection_required"]:
                raise ValueError("物料不需要质检")
            iid = _id()
            code = self._next(db, "inspection", "QI")
            db.execute(
                "INSERT INTO inspection(id, space, code, receipt_id, material_id, result, defect_qty)"
                " VALUES (?,?,?,?,?, 'pending', 0)",
                (iid, self._space(), code, receipt_id, receipt["material_id"]),
            )
            return self._inspection(db.execute("SELECT * FROM inspection WHERE id=?", (iid,)).fetchone())

    def decide_inspection(self, inspection_id: str, passed: bool, defect_qty: float = 0):
        with self._connect() as db:
            row = self._must(
                self._one(db, "SELECT * FROM inspection WHERE id=? AND space=?", (inspection_id, self._space())),
                "质检单",
            )
            if row["result"] != "pending":
                raise ValueError("只有待判定的质检单可以判定")
            result = "passed" if passed else "failed"
            db.execute("UPDATE inspection SET result=?, defect_qty=? WHERE id=?", (result, defect_qty, inspection_id))
            return self._inspection(db.execute("SELECT * FROM inspection WHERE id=?", (inspection_id,)).fetchone())

    def _inspection(self, r):
        return {
            "id": r["id"],
            "code": r["code"],
            "receiptId": r["receipt_id"],
            "materialId": r["material_id"],
            "result": r["result"],
            "defectQty": r["defect_qty"],
        }
