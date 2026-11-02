"""Entity attributes ("Field "): typed fields of an entity node, e.g. PurchaseOrder.amount.

Requirement items and test cases can reference an attribute (entity.attribute); attributes are
part of the model snapshot taken when a version is frozen."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.io_spec import (  # shared with action inputs/outputs
    DATA_TYPES,
    refresh_action_fields,
)

COLUMNS = (
    "a.id, a.sut_id, a.node_id, a.name, a.display_name, a.data_type, a.unit, a.constraints,"
    " a.description, a.position, a.required, a.format, a.example, a.enum_values, a.ref_node_id,"
    " a.storage_name,"
    " (SELECT r.name FROM model_node r WHERE r.id=a.ref_node_id) AS ref_node_name,"
    " a.created_at, a.updated_at"
)


class Constraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    expr: str | None = Field(default=None, max_length=2000)


def _constraints(raw: Any) -> list[dict]:
    try:
        return [Constraint.model_validate(c).model_dump(exclude_none=True) for c in raw or []]
    except ValidationError as exc:
        raise AppError("VALIDATION", "Invalid field constraints", field_errors=[{"field": "constraints"}]) from exc


def label(attr: dict) -> str:
    """PurchaseOrder.amount (amount)"""
    text = f"{attr.get('node_name') or '?'}.{attr['name']}"
    return f"{text} ({attr['display_name']})" if attr.get("display_name") else text


class AttributeService:
    def __init__(self, db, bus: EventBus, actor: str = "local-user"):
        self.db = db
        self.bus = bus
        self.actor = actor

    # ------------------------------------------------------------ queries
    def list_for_sut(self, sut_id, cur=None) -> list[dict]:
        query = (
            f"SELECT {COLUMNS}, n.name AS node_name FROM entity_attribute a"
            " JOIN model_node n ON n.id=a.node_id"
            " WHERE a.sut_id=%s AND a.deleted_at IS NULL AND n.deleted_at IS NULL"
            " ORDER BY n.name, a.position, a.name"
        )
        if cur is not None:
            cur.execute(query, (sut_id,))
            return cur.fetchall()
        with self.db.tx() as c:
            c.execute(query, (sut_id,))
            return c.fetchall()

    def list_for_node(self, node_id, cur=None) -> list[dict]:
        query = (
            f"SELECT {COLUMNS}, n.name AS node_name FROM entity_attribute a"
            " JOIN model_node n ON n.id=a.node_id"
            " WHERE a.node_id=%s AND a.deleted_at IS NULL ORDER BY a.position, a.name"
        )
        if cur is not None:
            cur.execute(query, (node_id,))
            return cur.fetchall()
        with self.db.tx() as c:
            c.execute(query, (node_id,))
            return c.fetchall()

    @staticmethod
    def _get(cur, attr_id, lock: bool = False) -> dict:
        cur.execute(
            f"SELECT {COLUMNS}, n.name AS node_name FROM entity_attribute a"
            " JOIN model_node n ON n.id=a.node_id WHERE a.id=%s AND a.deleted_at IS NULL"
            + (" FOR UPDATE OF a" if lock else ""),
            (attr_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Field not found")
        return row

    def get(self, attr_id) -> dict:
        with self.db.tx() as cur:
            row = self._get(cur, attr_id)
            row["references"] = self._references(cur, attr_id)
            return row

    @staticmethod
    def _references(cur, attr_id) -> list[dict]:
        cur.execute(
            "SELECT DISTINCT 'requirement' AS type, r.id, r.code, r.title FROM"
            " requirement_attribute_link l JOIN requirement r ON r.id=l.requirement_id"
            " WHERE l.attribute_id=%s"
            " UNION ALL SELECT 'case', c.id, c.code, c.title FROM case_attribute_link l"
            " JOIN test_case c ON c.id=l.case_id WHERE l.attribute_id=%s"
            " UNION ALL SELECT 'link', k.id, f.name || ' ' || k.forward_name || ' ' || t.name,"
            " 'foreign-key field' FROM model_link k JOIN model_node f ON f.id=k.from_node_id"
            " JOIN model_node t ON t.id=k.to_node_id WHERE k.deleted_at IS NULL"
            " AND %s IN (k.fk_attribute_id, k.via_from_attribute_id, k.via_to_attribute_id)"
            " UNION ALL SELECT 'action', n.id, n.name, 'preconditions/effects' FROM model_node n"
            " WHERE n.deleted_at IS NULL AND n.kind='action' AND EXISTS (SELECT 1 FROM"
            " jsonb_array_elements(n.preconditions || n.effects) i"
            " WHERE i->>'attribute_id' = %s::text)",
            (attr_id, attr_id, attr_id, str(attr_id)),
        )
        return cur.fetchall()

    def resolve(self, cur, sut_id, ref: str) -> dict | None:
        """Find an attribute by id or by "Entity.field" / "entity.field" (names or display names)."""
        ref = str(ref).strip()
        cur.execute(
            f"SELECT {COLUMNS}, n.name AS node_name FROM entity_attribute a"
            " JOIN model_node n ON n.id=a.node_id WHERE a.sut_id=%s AND a.deleted_at IS NULL"
            " AND n.deleted_at IS NULL AND (a.id::text=%s"
            " OR lower(n.name || '.' || a.name)=lower(%s)"
            " OR lower(n.name || '.' || coalesce(a.display_name, ''))=lower(%s))",
            (sut_id, ref, ref, ref),
        )
        return cur.fetchone()

    # ------------------------------------------------------------ writes
    def _values(self, data: dict) -> dict:
        values = {}
        for key in (
            "name",
            "display_name",
            "data_type",
            "unit",
            "description",
            "position",
            "required",
            "format",
            "example",
            "ref_node_id",
            "storage_name",
        ):
            if key in data:
                values[key] = data[key]
        if "name" in values:
            values["name"] = str(values["name"]).strip()
            if not values["name"]:
                raise AppError("VALIDATION", "Field name is required", field_errors=[{"field": "name"}])
        if "data_type" in values and values["data_type"] not in DATA_TYPES:
            raise AppError("VALIDATION", "Unknown field type", field_errors=[{"field": "data_type"}])
        if "storage_name" in values:
            values["storage_name"] = str(values["storage_name"] or "").strip() or None
        if "constraints" in data:
            values["constraints"] = Jsonb(_constraints(data["constraints"]))
        if "enum_values" in data:
            items = [str(v).strip() for v in data["enum_values"] or [] if str(v).strip()]
            values["enum_values"] = Jsonb(list(dict.fromkeys(items)))
        return values

    @staticmethod
    def _check_type(cur, sut_id, merged: dict) -> None:
        """enum needs values; reference needs a target entity of the same system."""
        data_type = merged.get("data_type")
        enum_values = merged.get("enum_values")
        if isinstance(enum_values, Jsonb):
            enum_values = enum_values.obj
        if data_type == "enum" and not enum_values:
            raise AppError("VALIDATION", "An enum field needs its values", field_errors=[{"field": "enum_values"}])
        ref = merged.get("ref_node_id")
        if data_type == "reference":
            if not ref:
                raise AppError(
                    "VALIDATION",
                    "A reference field needs a target entity",
                    field_errors=[{"field": "ref_node_id"}],
                )
            cur.execute(
                "SELECT 1 FROM model_node WHERE id=%s AND sut_id=%s AND kind='entity' AND deleted_at IS NULL",
                (ref, sut_id),
            )
            if cur.fetchone() is None:
                raise AppError(
                    "VALIDATION",
                    "The referenced entity does not exist or belongs to another SUT",
                    field_errors=[{"field": "ref_node_id"}],
                )

    def create(self, node_id, data: dict) -> dict:
        if not data.get("data_type"):
            raise AppError("VALIDATION", "Field type is required", field_errors=[{"field": "data_type"}])
        values = self._values(data)
        with self.db.tx() as cur:
            cur.execute(
                "SELECT id, sut_id, kind FROM model_node WHERE id=%s AND deleted_at IS NULL FOR UPDATE",
                (node_id,),
            )
            node = cur.fetchone()
            if node is None:
                raise AppError("NOT_FOUND", "Node not found")
            if node["kind"] != "entity":
                raise AppError("VALIDATION", "Only entity nodes can have fields")
            self._check_type(cur, node["sut_id"], values)
            cur.execute(
                "SELECT 1 FROM entity_attribute WHERE node_id=%s AND lower(name)=lower(%s) AND deleted_at IS NULL",
                (node_id, values["name"]),
            )
            if cur.fetchone():
                raise AppError("CONFLICT", f"This entity already has the field {values['name']}")
            if "position" not in values:
                cur.execute(
                    "SELECT coalesce(max(position), 0) + 1 AS p FROM entity_attribute WHERE node_id=%s",
                    (node_id,),
                )
                values["position"] = cur.fetchone()["p"]
            cols = ["sut_id", "node_id", *values]
            cur.execute(
                f"INSERT INTO entity_attribute({', '.join(cols)})"
                f" VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
                (node["sut_id"], node_id, *values.values()),
            )
            attr_id = cur.fetchone()["id"]
            log_change(cur, "entity_attribute", attr_id, "create", self.actor, data)
            refresh_action_fields(cur, node["sut_id"], self.list_for_sut(node["sut_id"], cur=cur))
            row = self._get(cur, attr_id)
        self.bus.publish("entity_attribute.created", {"id": str(attr_id)})
        row["link_suggestions"] = self._suggest_links(row)
        return row

    def _suggest_links(self, row: dict) -> int:
        """A reference field (or <resource>_id) implies a link: propose it."""
        if self.db is None or not (row.get("data_type") == "reference" or str(row.get("name", "")).endswith("_id")):
            return 0
        from testagent.services.links import suggest_links

        return len(suggest_links(self.db, self.bus, row["sut_id"]))

    def update(self, attr_id, data: dict) -> dict:
        values = self._values(data)
        with self.db.tx() as cur:
            current = self._get(cur, attr_id, lock=True)
            if values.get("data_type", "") is None:
                raise AppError("VALIDATION", "Field type is required", field_errors=[{"field": "data_type"}])
            self._check_type(cur, current["sut_id"], {**current, **values})
            if "name" in values:
                cur.execute(
                    "SELECT 1 FROM entity_attribute WHERE node_id=%s AND lower(name)=lower(%s)"
                    " AND deleted_at IS NULL AND id<>%s",
                    (current["node_id"], values["name"], attr_id),
                )
                if cur.fetchone():
                    raise AppError("CONFLICT", f"This entity already has the field {values['name']}")
            if values:
                sets = ", ".join(f"{k}=%s" for k in values)
                cur.execute(f"UPDATE entity_attribute SET {sets} WHERE id=%s", (*values.values(), attr_id))
            log_change(cur, "entity_attribute", attr_id, "update", self.actor, data)
            if "name" in values and values["name"] != current["name"]:
                sut_id = current["sut_id"]
                refresh_action_fields(cur, sut_id, self.list_for_sut(sut_id, cur=cur))
            row = self._get(cur, attr_id)
        self.bus.publish("entity_attribute.updated", {"id": str(attr_id)})
        if any(k in values for k in ("data_type", "ref_node_id", "name")):
            row["link_suggestions"] = self._suggest_links(row)
        return row

    def delete(self, attr_id, *, confirm: bool = False) -> dict:
        """Soft delete; a referenced field needs confirm=true (references are kept)."""
        with self.db.tx() as cur:
            self._get(cur, attr_id, lock=True)
            refs = self._references(cur, attr_id)
            if refs and not confirm:
                raise AppError(
                    "CONFLICT",
                    f"This field is still referenced by {len(refs)} item(s); confirm to delete",
                    related=[f"{r['type']}:{r['code']}" for r in refs],
                )
            cur.execute("UPDATE entity_attribute SET deleted_at=now() WHERE id=%s", (attr_id,))
            for col in ("fk_attribute_id", "via_from_attribute_id", "via_to_attribute_id"):
                cur.execute(
                    f"UPDATE model_link SET {col}=NULL WHERE {col}=%s AND deleted_at IS NULL",
                    (attr_id,),
                )
            log_change(cur, "entity_attribute", attr_id, "soft_delete", self.actor, {"refs": len(refs)})
        self.bus.publish("entity_attribute.deleted", {"id": str(attr_id)})
        return {"deleted": True, "references": refs}
