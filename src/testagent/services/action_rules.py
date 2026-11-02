"""Action preconditions and effects (Palantir action types: submission criteria and rules).

Stored on the action node as two JSON lists:

- precondition: ``{"field": "PurchaseOrder.state", "attribute_id": …, "op": "eq", "value": "pending",
  "message": "Only purchase orders pending approval can be approved"}`` — a structured condition on an entity field;
  ``text`` alone is allowed for conditions that are not about a field (e.g. "The approver is not the submitter").
- effect: ``{"kind": "set_field", "field": "PurchaseOrder.state", "attribute_id": …,
  "values": ["approved", "rejected"], "when": "approved=true → approved"}``; other kinds create or
  delete an object of an entity (``node_id``) or create/delete a link (``link_id``).

Field references are bound by id (``attribute_id``); the "Entity.field" label is refreshed when a
field is renamed (see ``refresh_rule_labels``)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from testagent.core.errors import AppError

Op = Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "is_null", "not_null"]
EffectKind = Literal["set_field", "create_object", "delete_object", "create_link", "delete_link"]
OP_TEXT = {
    "eq": "==",
    "ne": "!=",
    "in": "∈",
    "not_in": "∉",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "is_null": "is empty",
    "not_null": "is not empty",
}
EFFECT_TEXT = {
    "set_field": "Set field",
    "create_object": "Create object",
    "delete_object": "Delete object",
    "create_link": "Create link",
    "delete_link": "Remove link",
}
Scalar = str | int | float | bool
Short = Annotated[str, Field(max_length=500)]


class Precondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str | None = Field(default=None, max_length=200, description="Entity.field")
    attribute_id: str | None = None
    op: Op | None = None
    value: Scalar | list[Scalar] | None = None
    text: Short | None = Field(default=None, description="free text when not about a field")
    message: Short | None = Field(default=None, description="why the action is refused")

    @model_validator(mode="after")
    def _shape(self):
        if not (self.field or self.attribute_id):
            if not self.text:
                raise ValueError("a precondition needs a field (Entity.field) or a text")
            return self
        if self.op is None:
            self.op = "eq"
        if self.op in ("in", "not_in"):
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"op {self.op} needs a non-empty list value")
        elif self.op in ("is_null", "not_null"):
            self.value = None
        elif self.value is None or isinstance(self.value, list):
            raise ValueError(f"op {self.op} needs a single value")
        return self


class Effect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: EffectKind = "set_field"
    field: str | None = Field(default=None, max_length=200, description="Entity.field (set_field)")
    attribute_id: str | None = None
    values: list[Scalar] = Field(default_factory=list, description="possible new values")
    node_id: str | None = Field(default=None, description="entity (create/delete object)")
    entity: str | None = Field(default=None, max_length=100, description="entity name")
    link_id: str | None = Field(default=None, description="link (create/delete link)")
    when: Short | None = Field(default=None, description="when this effect applies")
    text: Short | None = None

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "set_field" and not (self.field or self.attribute_id):
            raise ValueError("set_field needs a field (Entity.field)")
        if self.kind in ("create_object", "delete_object") and not (self.node_id or self.entity):
            raise ValueError(f"{self.kind} needs an entity")
        if self.kind in ("create_link", "delete_link") and not self.link_id:
            raise ValueError(f"{self.kind} needs link_id")
        return self


def _errors(exc: ValidationError, key: str, index: int) -> list[dict]:
    return [{"field": f"{key}[{index}]" + "".join(f".{p}" for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]


def _field_label(attr: dict) -> str:
    return f"{attr['node_name']}.{attr['name']}"


def _check_value(attr: dict, value, label: str) -> str | None:
    allowed = [str(v) for v in attr.get("enum_values") or []]
    if not allowed or value is None:
        return None
    for v in value if isinstance(value, list) else [value]:
        if str(v) not in allowed:
            return f"{label} value {v} is not in the enum {allowed} "
    return None


def validate_rules(cur, sut_id, data: dict, *, strict: bool = True) -> dict:
    """Validate ``preconditions`` / ``effects`` present in ``data``; binds Entity.field to ids.

    strict=False (AI suggestions) drops items that do not resolve instead of failing."""
    from testagent.services.attributes import AttributeService

    attrs = AttributeService(None, None)
    out: dict[str, list] = {}
    field_errors: list[dict] = []

    def bind(item: dict, key: str, i: int) -> dict | None:
        ref = item.get("attribute_id") or item.get("field")
        if not ref:
            return None
        attr = attrs.resolve(cur, sut_id, ref)
        if attr is None and item.get("attribute_id") and item.get("field"):
            attr = attrs.resolve(cur, sut_id, item["field"])
        if attr is None:
            field_errors.append({"field": f"{key}[{i}].field", "msg": f"Field {ref} does not exist"})
            return None
        item["attribute_id"] = str(attr["id"])
        item["field"] = _field_label(attr)
        return attr

    for key, model in (("preconditions", Precondition), ("effects", Effect)):
        if key not in data:
            continue
        items = []
        for i, raw in enumerate(data[key] or []):
            before = len(field_errors)
            try:
                item = model.model_validate(raw).model_dump(exclude_none=True)
            except ValidationError as exc:
                field_errors += _errors(exc, key, i)
                continue
            if key == "preconditions" or item["kind"] == "set_field":
                attr = bind(item, key, i)
                value = item.get("value") if key == "preconditions" else item.get("values")
                if attr is not None:
                    msg = _check_value(attr, value, item["field"])
                    if msg:
                        field_errors.append({"field": f"{key}[{i}].value", "msg": msg})
            elif item["kind"] in ("create_object", "delete_object"):
                cur.execute(
                    "SELECT id, name FROM model_node WHERE sut_id=%s AND kind='entity'"
                    " AND deleted_at IS NULL AND (id::text=%s OR name=%s)",
                    (sut_id, str(item.get("node_id") or ""), item.get("entity") or ""),
                )
                row = cur.fetchone()
                if row is None:
                    field_errors.append({"field": f"{key}[{i}].node_id", "msg": "Entity not found"})
                else:
                    item["node_id"], item["entity"] = str(row["id"]), row["name"]
            else:
                cur.execute(
                    "SELECT id FROM model_link WHERE id::text=%s AND sut_id=%s AND deleted_at IS NULL",
                    (str(item["link_id"]), sut_id),
                )
                if cur.fetchone() is None:
                    field_errors.append({"field": f"{key}[{i}].link_id", "msg": "Link not found"})
            if len(field_errors) == before:
                items.append(item)
        out[key] = items
    if field_errors and strict:
        raise AppError("VALIDATION", "Invalid precondition/effect format", field_errors=field_errors)
    return out


def precondition_text(p: dict) -> str:
    if not p.get("field"):
        return p.get("text") or ""
    op = p.get("op") or "eq"
    if op in ("is_null", "not_null"):
        return f"{p['field']} {OP_TEXT[op]}"
    value = p.get("value")
    shown = " | ".join(map(str, value)) if isinstance(value, list) else str(value)
    return f"{p['field']} {OP_TEXT[op]} {shown}"


def effect_text(e: dict, links: dict[str, str] | None = None) -> str:
    kind = e.get("kind") or "set_field"
    if kind == "set_field":
        text = f"{e.get('field')} → {' | '.join(map(str, e.get('values') or [])) or '?'}"
    elif kind in ("create_object", "delete_object"):
        text = f"{EFFECT_TEXT[kind]} {e.get('entity') or e.get('node_id')}"
    else:
        text = f"{EFFECT_TEXT[kind]} {(links or {}).get(str(e.get('link_id')), e.get('link_id'))}"
    if e.get("when"):
        text += f" ({e['when']})"
    return text


def refresh_rule_labels(cur, sut_id) -> int:
    """After a field rename: refresh the Entity.field labels stored in preconditions/effects."""
    from psycopg.types.json import Jsonb

    cur.execute(
        "SELECT a.id::text AS id, a.name, n.name AS node_name FROM entity_attribute a"
        " JOIN model_node n ON n.id=a.node_id WHERE a.sut_id=%s",
        (sut_id,),
    )
    labels = {r["id"]: _field_label(r) for r in cur.fetchall()}
    cur.execute(
        "SELECT id, preconditions, effects FROM model_node WHERE sut_id=%s AND kind='action'"
        " AND deleted_at IS NULL AND (preconditions <> '[]'::jsonb OR effects <> '[]'::jsonb)",
        (sut_id,),
    )
    changed = 0
    for row in cur.fetchall():
        updates: dict[str, Any] = {}
        for key in ("preconditions", "effects"):
            items = []
            for item in row[key] or []:
                label = labels.get(str(item.get("attribute_id") or ""))
                items.append({**item, "field": label} if label else item)
            if items != (row[key] or []):
                updates[key] = items
        if updates:
            sets = ", ".join(f"{k}=%s" for k in updates)
            cur.execute(
                f"UPDATE model_node SET {sets} WHERE id=%s",
                (*[Jsonb(v) for v in updates.values()], row["id"]),
            )
            changed += 1
    return changed
