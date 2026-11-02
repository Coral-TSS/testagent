"""Synthetic procurement and local ledger. No real payment integrations.

Business rules (see README.md):
- suppliers are referenced by purchase orders (PurchaseOrder.supplier_id → Supplier.id, N:1);
- a CNY order of 50,000.00 yuan (5,000,000 fen) or more needs approval (state ``pending``);
  smaller CNY orders are approved automatically (``approved``); an unknown amount or another
  currency cannot be judged (``unknown``) and can never be paid;
- only ``pending`` orders accept a decision (approve → ``approved``, reject → ``rejected``);
- only ``approved`` orders can be paid, at most once; replaying the same callback_id returns
  the original payment (idempotent) and the order becomes ``paid``.

``demo_bugs`` (env PROCUREMENT_DEMO_BUGS, default on) switches on a few deliberate defects
listed in README.md so people can check whether TestAgent finds them.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

DEFAULT_SUPPLIERS = [
    {"name": "East China Office Supplies Co.", "contact": "Manager Zhang 555-0101"},
    {"name": "Galaxy Tech Equipment Co.", "contact": "Engineer Li 555-0102"},
    {"name": "Swift Logistics Services Co.", "contact": "Supervisor Wang 555-0103"},
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, contact TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, title TEXT, supplier_id TEXT REFERENCES suppliers(id),
    amount INTEGER, currency TEXT, approval_required INTEGER, state TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
    callback_id TEXT NOT NULL, amount INTEGER NOT NULL, paid_at TEXT NOT NULL,
    UNIQUE(order_id, callback_id)
);
"""


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ProcurementService:
    def __init__(
        self,
        database: Path,
        threshold_minor: int = 5_000_000,
        *,
        demo_bugs: bool | None = None,
    ):
        self.database = database
        self.threshold = threshold_minor
        self.demo_bugs = env_flag("PROCUREMENT_DEMO_BUGS", True) if demo_bugs is None else demo_bugs
        with self._connect() as db:
            columns = {r["name"] for r in db.execute("PRAGMA table_info(orders)")}
            if columns and "supplier_id" not in columns:  # demo data from from older versions
                db.executescript("DROP TABLE IF EXISTS payments; DROP TABLE IF EXISTS orders;")
            db.executescript(SCHEMA)
            if not db.execute("SELECT 1 FROM suppliers LIMIT 1").fetchone():
                self._seed(db)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _seed(db) -> None:
        for s in DEFAULT_SUPPLIERS:
            db.execute(
                "INSERT INTO suppliers VALUES (?, ?, ?, ?)",
                (str(uuid4()), s["name"], s["contact"], _now()),
            )

    # ------------------------------------------------------------------ suppliers
    def suppliers(self) -> list[dict]:
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM suppliers ORDER BY rowid")]

    def supplier(self, supplier_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        return dict(row) if row else None

    def create_supplier(self, name: str, contact: str | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("Supplier name cannot be empty")
        row = {"id": str(uuid4()), "name": name, "contact": contact, "created_at": _now()}
        try:
            with self._connect() as db:
                db.execute("INSERT INTO suppliers VALUES (:id, :name, :contact, :created_at)", row)
        except sqlite3.IntegrityError as exc:
            raise KeyError("Supplier name already exists") from exc
        return row

    # ------------------------------------------------------------------ orders
    def create_order(
        self,
        amount_minor: int | None,
        currency: str,
        *,
        supplier_id: str | None = None,
        title: str | None = None,
    ) -> dict:
        if amount_minor is not None and (type(amount_minor) is not int or amount_minor < 0):
            raise ValueError("Amount must be a non-negative integer (in cents), or null when unknown")
        if supplier_id is not None and self.supplier(supplier_id) is None:
            raise LookupError("Supplier not found")
        required = None
        state = "unknown"
        if amount_minor is not None and currency == "CNY":
            if self.demo_bugs:  # seeded bug 1 (README)
                required = amount_minor > self.threshold
            else:
                required = amount_minor >= self.threshold
            state = "pending" if required else "approved"
        order_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, title, supplier_id, amount_minor, currency, required, state, _now()),
            )
        return self.order(order_id)

    def order(self, order_id: str) -> dict | None:
        rows = self.orders(order_id=order_id)
        return rows[0] if rows else None

    def orders(
        self,
        *,
        order_id: str | None = None,
        state: str | None = None,
        supplier_id: str | None = None,
    ) -> list[dict]:
        sql = "SELECT o.*, s.name AS supplier_name FROM orders o LEFT JOIN suppliers s ON s.id=o.supplier_id WHERE 1=1"
        args: list = []
        for column, value in (
            ("o.id", order_id),
            ("o.state", state),
            ("o.supplier_id", supplier_id),
        ):
            if value is not None:
                sql += f" AND {column}=?"
                args.append(value)
        with self._connect() as db:
            rows = db.execute(sql + " ORDER BY o.rowid DESC", args).fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "supplier_id": row["supplier_id"],
                "supplier_name": row["supplier_name"],
                "amount_minor": row["amount"],
                "currency": row["currency"],
                "approval_required": (None if row["approval_required"] is None else bool(row["approval_required"])),
                "state": row["state"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def decide(self, order_id: str, *, approved: bool) -> None:
        if type(approved) is not bool:
            raise ValueError("Approval decision must be true or false")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                "UPDATE orders SET state=? WHERE id=? AND state='pending'",
                ("approved" if approved else "rejected", order_id),
            )
            if updated.rowcount != 1:
                raise ValueError("Only purchase orders pending approval can be approved")

    # ------------------------------------------------------------------ payments
    def pay(self, order_id: str, callback_id: str) -> dict:
        if not callback_id:
            raise ValueError("Payment callback id cannot be empty")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            same = db.execute(
                "SELECT * FROM payments WHERE order_id=? AND callback_id=?", (order_id, callback_id)
            ).fetchone()
            if same:
                return dict(same)
            order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if order is None:
                raise LookupError("Purchase order not found")
            # seeded bug 2 (README): auto-approved orders skip the "already paid" check
            lenient = self.demo_bugs and order["approval_required"] == 0
            allowed = ("approved", "paid") if lenient else ("approved",)
            if order["state"] == "paid" and not lenient:
                raise ValueError(
                    "This purchase order is already paid; it cannot be paid again with another callback id"
                )
            if order["state"] not in allowed:
                raise ValueError("The purchase order is not approved and cannot be paid")
            payment = {
                "id": str(uuid4()),
                "order_id": order_id,
                "callback_id": callback_id,
                "amount": order["amount"],
                "paid_at": _now(),
            }
            db.execute(
                "INSERT INTO payments VALUES (:id, :order_id, :callback_id, :amount, :paid_at)",
                payment,
            )
            db.execute("UPDATE orders SET state='paid' WHERE id=?", (order_id,))
            return payment

    def payments(self, order_id: str) -> list[dict]:
        with self._connect() as db:
            return [
                dict(row) for row in db.execute("SELECT * FROM payments WHERE order_id=? ORDER BY rowid", (order_id,))
            ]

    def reset(self, *, reseed: bool = True) -> int:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM payments")
            db.execute("DELETE FROM orders")
            db.execute("DELETE FROM suppliers")
            if reseed:
                self._seed(db)
        return len(DEFAULT_SUPPLIERS) if reseed else 0
