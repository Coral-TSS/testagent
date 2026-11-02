"""Shared CRUD helpers for simple tables (single transaction + change log + event)."""

from __future__ import annotations

from typing import Any

from psycopg import sql
from psycopg.errors import ForeignKeyViolation

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change


def _jsonable(row: dict) -> dict:
    return {k: (str(v) if k.endswith("id") and v is not None else v) for k, v in row.items()}


class Crud:
    table: str
    entity: str
    label: str

    def __init__(self, db, bus: EventBus, actor: str = "local-user"):
        self.db = db
        self.bus = bus
        self.actor = actor

    def _missing(self) -> AppError:
        return AppError("NOT_FOUND", f"{self.label} does not exist")

    def create(self, values: dict[str, Any]) -> dict:
        cols = list(values)
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
            sql.Identifier(self.table),
            sql.SQL(", ").join(map(sql.Identifier, cols)),
            sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        )
        with self.db.tx() as cur:
            cur.execute(query, [values[c] for c in cols])
            row = cur.fetchone()
            log_change(cur, self.entity, row["id"], "create", self.actor, _jsonable(values))
        self.bus.publish(f"{self.entity}.created", {"id": str(row["id"])})
        return row

    def get(self, id_) -> dict:
        with self.db.tx() as cur:
            cur.execute(sql.SQL("SELECT * FROM {} WHERE id=%s").format(sql.Identifier(self.table)), (id_,))
            row = cur.fetchone()
        if row is None:
            raise self._missing()
        return row

    def list(self, where: dict[str, Any] | None = None, order: str = "created_at") -> list[dict]:
        where = where or {}
        cond = (
            sql.SQL(" WHERE ") + sql.SQL(" AND ").join(sql.SQL("{}=%s").format(sql.Identifier(k)) for k in where)
            if where
            else sql.SQL("")
        )
        query = sql.SQL("SELECT * FROM {}{} ORDER BY {}").format(
            sql.Identifier(self.table), cond, sql.Identifier(order)
        )
        with self.db.tx() as cur:
            cur.execute(query, list(where.values()))
            return cur.fetchall()

    def update(self, id_, values: dict[str, Any]) -> dict:
        if not values:
            return self.get(id_)
        sets = sql.SQL(", ").join(sql.SQL("{}=%s").format(sql.Identifier(k)) for k in values)
        query = sql.SQL("UPDATE {} SET {} WHERE id=%s RETURNING *").format(sql.Identifier(self.table), sets)
        with self.db.tx() as cur:
            cur.execute(query, [*values.values(), id_])
            row = cur.fetchone()
            if row is None:
                raise self._missing()
            log_change(cur, self.entity, id_, "update", self.actor, _jsonable(values))
        self.bus.publish(f"{self.entity}.updated", {"id": str(id_)})
        return row

    def delete(self, id_) -> None:
        try:
            self._delete(id_)
        except AppError as err:
            if isinstance(err.__cause__, ForeignKeyViolation):
                raise AppError(
                    "CONFLICT", f"{self.label} is still referenced by other data and cannot be deleted"
                ) from err
            raise
        self.bus.publish(f"{self.entity}.deleted", {"id": str(id_)})

    def _delete(self, id_) -> None:
        with self.db.tx() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {} WHERE id=%s RETURNING id").format(sql.Identifier(self.table)),
                (id_,),
            )
            if cur.fetchone() is None:
                raise self._missing()
            log_change(cur, self.entity, id_, "delete", self.actor)
