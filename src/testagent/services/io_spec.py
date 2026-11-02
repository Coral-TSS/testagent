"""Inputs / outputs of actions and APIs.

An action node lists what it takes and what it gives back as typed parameters (name, display
name, type, required, format/example, enum values, description), each optionally bound to an
entity field ("PurchaseOrder.amount_minor"). API schemas (JSON Schema, usually imported from OpenAPI) are
flattened into the same parameter shape so the UI can show readable tables and an action linked
to an API can inherit its inputs and outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from testagent.core.errors import AppError

DATA_TYPES = (
    "string",
    "integer",
    "number",
    "decimal",
    "money",
    "boolean",
    "date",
    "datetime",
    "enum",
    "reference",
    "object",
    "array",
)
DataType = Literal[
    "string",
    "integer",
    "number",
    "decimal",
    "money",
    "boolean",
    "date",
    "datetime",
    "enum",
    "reference",
    "object",
    "array",
]
Location = Literal["path", "query", "header", "body", "form", "response", "ui"]
LOCATION_LABEL = {
    "path": "Path parameters",
    "query": "Query parameters",
    "header": "Headers",
    "body": "Request body",
    "form": "Form",
    "response": "Response",
    "ui": "Page",
}
MAX_PARAMS = 100


class IoParam(BaseModel):
    """One input or output of an action."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, description="machine name, e.g. amount_minor")
    display_name: str | None = Field(default=None, max_length=100, description="e.g. amount")
    data_type: DataType = Field(description="type; enum needs enum_values")
    required: bool = False
    location: Location | None = Field(default=None, description="path/query/header/body/form/...")
    format: str | None = Field(default=None, max_length=200, description="e.g. uuid, YYYY-MM-DD, integer in cents")
    example: str | None = Field(default=None, max_length=500)
    enum_values: list[str] = Field(default_factory=list, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    field: str | None = Field(default=None, max_length=300, description='entity field, "Entity.field" or its id')
    attribute_id: str | None = None


def _errors(exc: ValidationError, prefix: str) -> list[dict]:
    return [{"field": prefix + "." + ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]


def validate_params(cur, sut_id, raw: Any, prefix: str, *, strict: bool = True) -> list[dict]:
    """Validate a parameter list and bind `field` to an entity attribute of the same system.

    strict=False (AI suggestions): an unknown field reference is kept as text in the
    description instead of failing."""
    from testagent.services.attributes import AttributeService, label

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AppError("VALIDATION", "Inputs/outputs must be a list", field_errors=[{"field": prefix}])
    if len(raw) > MAX_PARAMS:
        raise AppError("VALIDATION", f"At most {MAX_PARAMS} parameters", field_errors=[{"field": prefix}])
    out, names = [], set()
    attrs = AttributeService(None, None)
    for i, item in enumerate(raw):
        try:
            param = IoParam.model_validate(item)
        except ValidationError as exc:
            raise AppError(
                "VALIDATION", "Invalid input/output parameter format", field_errors=_errors(exc, f"{prefix}.{i}")
            ) from exc
        data = param.model_dump(exclude_none=True)
        data["name"] = data["name"].strip()
        key = (data.get("location"), data["name"].lower())
        if key in names:
            raise AppError(
                "VALIDATION",
                f"Parameter {data['name']} is duplicated",
                field_errors=[{"field": f"{prefix}.{i}.name"}],
            )
        names.add(key)
        if data["data_type"] == "enum" and not data.get("enum_values"):
            if strict:
                raise AppError(
                    "VALIDATION",
                    f"Parameter {data['name']} is an enum and needs values",
                    field_errors=[{"field": f"{prefix}.{i}.enum_values"}],
                )
            data["data_type"] = "string"
        ref = data.pop("attribute_id", None) or data.get("field")
        data.pop("field", None)
        if ref:
            attr = attrs.resolve(cur, sut_id, ref)
            if attr is not None:
                data["attribute_id"] = str(attr["id"])
                data["field"] = label(attr).split(" (")[0]
            elif strict:
                raise AppError(
                    "VALIDATION",
                    f"Referenced field does not exist: {ref}",
                    field_errors=[{"field": f"{prefix}.{i}.field"}],
                )
            else:
                note = f" (maps to field {ref}, not in the model yet)"
                data["description"] = (data.get("description") or "") + note
        if not data.get("enum_values"):
            data.pop("enum_values", None)
        out.append(data)
    return out


# ------------------------------------------------------------------ JSON schema → parameters
def _non_null(schema: dict) -> tuple[dict, bool]:
    """anyOf [X, null] → (X, nullable)."""
    options = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(options, list):
        real = [o for o in options if isinstance(o, dict) and o.get("type") != "null"]
        if len(real) == 1:
            merged = {**{k: v for k, v in schema.items() if k not in ("anyOf", "oneOf")}, **real[0]}
            return merged, len(real) < len(options)
    if isinstance(schema.get("type"), list):
        types = [t for t in schema["type"] if t != "null"]
        if len(types) == 1:
            return {**schema, "type": types[0]}, len(types) < len(schema["type"])
    return schema, False


def _type(schema: dict) -> str:
    if schema.get("enum"):
        return "enum"
    t = schema.get("type")
    fmt = schema.get("format")
    if t == "string" and fmt == "date":
        return "date"
    if t == "string" and fmt in ("date-time", "datetime"):
        return "datetime"
    if t in ("integer", "number", "boolean", "object", "array", "string"):
        return t
    if schema.get("properties"):
        return "object"
    return "string"


def _limits(schema: dict) -> list[str]:
    out = []
    for key, text in (
        ("minimum", "≥"),
        ("exclusiveMinimum", ">"),
        ("maximum", "≤"),
        ("exclusiveMaximum", "<"),
    ):
        if isinstance(schema.get(key), int | float) and not isinstance(schema.get(key), bool):
            value = schema[key]
            out.append(f"{text} {int(value) if float(value).is_integer() else value}")
    if schema.get("minLength") is not None:
        out.append(f"length ≥ {schema['minLength']}")
    if schema.get("maxLength") is not None:
        out.append(f"length ≤ {schema['maxLength']}")
    if schema.get("pattern"):
        out.append(f"format {schema['pattern']}")
    return out


def _param(name: str, schema: dict, required: bool, location: str | None) -> dict:
    schema, nullable = _non_null(schema if isinstance(schema, dict) else {})
    data_type = _type(schema)
    fmt = [schema["format"]] if isinstance(schema.get("format"), str) else []
    fmt += _limits(schema)
    if nullable:
        fmt.append("nullable")
    if data_type == "array" and isinstance(schema.get("items"), dict):
        item, _ = _non_null(schema["items"])
        fmt.insert(0, f"{_type(item)}[]")
    if schema.get("x-data-type") in DATA_TYPES:
        data_type = schema["x-data-type"]
    if isinstance(schema.get("x-format"), str):  # edited in the UI: the text is authoritative
        fmt = [schema["x-format"]]
    param: dict = {"name": name, "data_type": data_type, "required": bool(required)}
    if isinstance(schema.get("x-display-name"), str):
        param["display_name"] = schema["x-display-name"][:100]
    if location:
        param["location"] = location
    if fmt:
        param["format"] = ", ".join(fmt)[:200]
    title = str(schema.get("title") or "")
    same = title.replace(" ", "_").lower() == name.split(".")[-1].lower()
    desc = schema.get("description") or (title if title and not same else None)
    if desc:
        param["description"] = str(desc)[:2000]
    if schema.get("examples") and isinstance(schema["examples"], list):
        param["example"] = str(schema["examples"][0])[:500]
    elif schema.get("example") is not None:
        param["example"] = str(schema["example"])[:500]
    if schema.get("enum"):
        param["enum_values"] = [str(v) for v in schema["enum"]][:100]
    return param


def keep_order(node: Any) -> Any:
    """jsonb does not keep object key order: remember property order in "x-order"."""
    if isinstance(node, dict):
        out = {k: keep_order(v) for k, v in node.items()}
        if isinstance(node.get("properties"), dict):
            out["x-order"] = list(node["properties"])
        return out
    if isinstance(node, list):
        return [keep_order(v) for v in node]
    return node


def ordered(schema: dict) -> list[tuple[str, Any]]:
    props = schema.get("properties") or {}
    order = [k for k in schema.get("x-order") or [] if k in props]
    return [(k, props[k]) for k in order] + [(k, v) for k, v in props.items() if k not in order]


def schema_params(schema: dict | None, location: str | None, prefix: str = "") -> list[dict]:
    """Top-level properties of an object schema (and one nested level as parent.child)."""
    if not isinstance(schema, dict):
        return []
    schema, _ = _non_null(schema)
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        schema, _ = _non_null(schema["items"])
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    required = set(schema.get("required") or [])
    out = []
    for name, prop in ordered(schema):
        full = f"{prefix}{name}"
        out.append(_param(full, prop, name in required, location))
        nested, _ = _non_null(prop if isinstance(prop, dict) else {})
        if not prefix and isinstance(nested.get("properties"), dict):
            out += schema_params(nested, location, prefix=f"{full}.")
    return out


def _success(responses: dict | None) -> tuple[str | None, dict | None]:
    for code in sorted((responses or {}).keys()):
        if str(code).startswith("2"):
            body = responses[code] or {}
            return str(code), body.get("schema") if isinstance(body, dict) else None
    return None, None


def request_params(request_schema: dict | None, content_type: str | None = None) -> list[dict]:
    req = request_schema or {}
    out = []
    for p in req.get("parameters") or []:
        if isinstance(p, dict) and p.get("name"):
            param = _param(p["name"], p.get("schema") or {}, bool(p.get("required")), p.get("in"))
            if p.get("description"):
                param["description"] = str(p["description"])[:2000]
            out.append(param)
    location = "form" if content_type and "form" in content_type else "body"
    out += schema_params(req.get("body"), location)
    return out


def response_params(response_schema: dict | None) -> list[dict]:
    _, schema = _success(response_schema)
    return [{**p, "location": "response"} for p in schema_params(schema, None)]


def format_text(content_type: str | None, schema: dict | None) -> str:
    """'JSON object (application/json)', 'JSON array (...)', 'Form (application/x-www-form-...)'."""
    if not content_type and not schema:
        return ""
    ct = content_type or "application/json"
    kind = "JSON" if "json" in ct else ("Form" if "form" in ct else ct)
    shape = ""
    if isinstance(schema, dict):
        s, _ = _non_null(schema)
        shape = " array" if s.get("type") == "array" else (" object" if s.get("properties") else "")
    return f"{kind}{shape} ({ct})" if kind != ct else ct


def api_io(api: dict) -> dict:
    """Readable inputs/outputs of a registered API (used for UI tables, agents and inheritance)."""
    req = api.get("request_schema") or {}
    code, resp = _success(api.get("response_schema"))
    in_parts = []
    params = [p for p in req.get("parameters") or [] if isinstance(p, dict)]
    if params:
        kinds = sorted({LOCATION_LABEL.get(p.get("in"), "Parameter") for p in params})
        in_parts.append("Parameters: " + ", ".join(kinds))
    if req.get("body"):
        in_parts.append("Request body " + format_text(api.get("request_content_type"), req.get("body")))
    out_format = format_text(api.get("response_content_type"), resp)
    return {
        "inputs": request_params(req, api.get("request_content_type")),
        "outputs": response_params(api.get("response_schema")),
        "input_format": "; ".join(in_parts) or None,
        "output_format": (f"HTTP {code}, {out_format}" if code and out_format else None)
        or (f"HTTP {code}" if code else None),
    }


def merge_params(current: list[dict], extra: list[dict]) -> tuple[list[dict], int]:
    """Keep every existing parameter; append the new ones by (location, name)."""
    have = {(p.get("location"), p["name"].lower()) for p in current}
    have_names = {p["name"].lower() for p in current}
    added = []
    for p in extra:
        if (p.get("location"), p["name"].lower()) in have or p["name"].lower() in have_names:
            continue
        added.append(p)
        have.add((p.get("location"), p["name"].lower()))
        have_names.add(p["name"].lower())
    return [*current, *added], len(added)


def bind_fields(params: list[dict], fields: list[dict], owners: list | None = None) -> list[dict]:
    """Bind unbound parameters to entity fields with the same name. When the action has object
    entities (`owners`), only their fields are candidates; otherwise a name must be unique."""
    from testagent.services.attributes import label

    owner_ids = {str(o) for o in owners or []}
    pool = [f for f in fields if str(f["node_id"]) in owner_ids] if owner_ids else fields
    by_name: dict[str, list[dict]] = {}
    for f in pool:
        by_name.setdefault(f["name"].lower(), []).append(f)
    out = []
    for p in params:
        if not p.get("attribute_id"):
            cands = by_name.get(p["name"].split(".")[-1].lower(), [])
            if len(cands) == 1:
                field = label(cands[0]).split(" (")[0]
                p = {**p, "attribute_id": str(cands[0]["id"]), "field": field}
        out.append(p)
    return out


def refresh_action_fields(cur, sut_id, fields: list[dict]) -> int:
    """After a field is added or renamed: refresh the "Entity.field" labels of bound action
    parameters and bind unbound parameters with the same name. Returns changed actions."""
    from testagent.services.attributes import label

    by_id = {str(f["id"]): f for f in fields}
    cur.execute(
        "SELECT n.id, n.inputs, n.outputs, coalesce(array_agg(e.target_node_id)"
        " FILTER (WHERE e.id IS NOT NULL), '{}') AS owners FROM model_node n"
        " LEFT JOIN model_edge e ON e.source_node_id=n.id AND e.role='object'"
        " AND e.invalid_at IS NULL WHERE n.sut_id=%s AND n.kind='action'"
        " AND n.deleted_at IS NULL GROUP BY n.id",
        (sut_id,),
    )
    changed = 0
    for action in cur.fetchall():
        updates = {}
        for key in ("inputs", "outputs"):
            params = []
            for p in action[key] or []:
                f = by_id.get(str(p.get("attribute_id") or ""))
                if f is not None:
                    p = {**p, "field": label(f).split(" (")[0]}
                params.append(p)
            params = bind_fields(params, fields, action["owners"] or None)
            if params != (action[key] or []):
                updates[key] = params
        if updates:
            from psycopg.types.json import Jsonb

            sets = ", ".join(f"{k}=%s" for k in updates)
            cur.execute(
                f"UPDATE model_node SET {sets} WHERE id=%s",
                (*[Jsonb(v) for v in updates.values()], action["id"]),
            )
            changed += 1
    from testagent.services.action_rules import refresh_rule_labels

    refresh_rule_labels(cur, sut_id)  # preconditions / effects show Entity.field too
    return changed


# ------------------------------------------------------------------ parameters → JSON schema
_JSON_TYPE = {
    "string": {"type": "string"},
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "decimal": {"type": "number"},
    "money": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
    "enum": {"type": "string"},
    "reference": {"type": "string"},
    "object": {"type": "object"},
    "array": {"type": "array"},
}


def _apply(prop: dict, param: dict) -> dict:
    """Update one property schema from an edited parameter; unknown keys are preserved and
    texts that merely repeat what the schema already says are not copied into it."""
    prop = prop or {}
    derived = _param(param["name"], prop, False, None) if prop else {}
    base, nullable = _non_null(prop)
    base = dict(base)
    if _type(base) != param["data_type"]:
        for key in ("type", "format", "items", "properties", "anyOf", "oneOf", "enum"):
            base.pop(key, None)
        base.update(_JSON_TYPE[param["data_type"]])
    for key in ("x-format", "x-display-name", "x-data-type", "examples", "enum"):
        base.pop(key, None)
    if param.get("description") != derived.get("description"):
        base.pop("description", None)
        if param.get("description"):
            base["description"] = param["description"]
    if param.get("display_name"):
        base["x-display-name"] = param["display_name"]
    if param["data_type"] in ("money", "decimal", "reference"):
        base["x-data-type"] = param["data_type"]
    if param.get("format") and param.get("format") != derived.get("format"):
        base["x-format"] = param["format"]
    if param.get("example"):
        base["examples"] = [param["example"]]
    if param.get("enum_values"):
        base["enum"] = list(param["enum_values"])
    return {"anyOf": [base, {"type": "null"}]} if nullable else base


def _apply_object(schema: dict | None, params: list[dict]) -> dict:
    obj = dict(schema or {})
    target = obj
    if obj.get("type") == "array" and isinstance(obj.get("items"), dict):
        target = obj["items"] = dict(obj["items"])
    target.setdefault("type", "object")
    props = dict(target.get("properties") or {})
    top = [p for p in params if "." not in p["name"]]
    keep = {p["name"] for p in top}
    props = {k: v for k, v in props.items() if k in keep}
    required = []
    for p in top:
        props[p["name"]] = _apply(props.get(p["name"], {}), p)
        if p.get("required"):
            required.append(p["name"])
    for p in params:  # nested rows (parent.child) update an existing child only
        if "." in p["name"]:
            parent, child = p["name"].split(".", 1)
            holder, _ = _non_null(props.get(parent) or {})
            if isinstance(holder.get("properties"), dict) and child in holder["properties"]:
                holder["properties"][child] = _apply(holder["properties"][child], p)
    target["properties"] = props
    target["x-order"] = [p["name"] for p in top]
    if required:
        target["required"] = required
    else:
        target.pop("required", None)
    return obj


def apply_request_fields(request_schema: dict | None, params: list[dict]) -> dict:
    req = dict(request_schema or {})
    in_params = [p for p in params if p.get("location") in ("path", "query", "header")]
    body = [p for p in params if p.get("location") not in ("path", "query", "header")]
    old = {(p.get("in"), p.get("name")): p for p in req.get("parameters") or []}
    if in_params:
        req["parameters"] = [
            {
                **old.get((p["location"], p["name"]), {}),
                "name": p["name"],
                "in": p["location"],
                "required": bool(p.get("required")) or p["location"] == "path",
                "schema": _apply((old.get((p["location"], p["name"])) or {}).get("schema") or {}, p),
                **({"description": p["description"]} if p.get("description") else {}),
            }
            for p in in_params
        ]
    else:
        req.pop("parameters", None)
    if body:
        req["body"] = _apply_object(req.get("body"), body)
    else:
        req.pop("body", None)
    return req


def apply_response_fields(response_schema: dict | None, params: list[dict]) -> dict:
    responses = dict(response_schema or {})
    code, schema = _success(responses)
    code = code or "200"
    entry = dict(responses.get(code) or {"description": "OK"})
    entry["schema"] = _apply_object(schema, params)
    responses[code] = entry
    return responses
