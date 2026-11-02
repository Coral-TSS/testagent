"""Entity fields follow the code entity / API field names.

Database columns usually differ from the API, but the code entity and its API use the same field
names, so the API's response fields are the canonical names of an entity's fields (a different
database column is kept as the field's ``storage_name``). This module compares each entity with
the response fields of the APIs of the actions that act on it and proposes, as pending
suggestions for a person to accept:

- a rename when the entity has a field with a different but matching name (amount → amount_minor,
  status → state); accepting keeps every requirement / case link of the field;
- a new field for every other response field the entity does not have yet."""

from __future__ import annotations

from testagent.services.io_spec import api_io

# pairs of names that mean the same field (lower case, either direction)
SYNONYMS = {
    ("status", "state"),
    ("type", "kind"),
    ("desc", "description"),
    ("amt", "amount"),
    ("qty", "quantity"),
    ("num", "number"),
    ("no", "number"),
}


def rename_match(field_name: str, api_name: str) -> bool:
    """True when an existing entity field is probably the API field under another name."""
    f, a = field_name.lower(), api_name.lower()
    if f == a:
        return False
    if a.startswith(f + "_") or f.startswith(a + "_"):  # amount → amount_minor
        return True
    return (f, a) in SYNONYMS or (a, f) in SYNONYMS


def entity_api_fields(cur, sut_id) -> dict[str, dict]:
    """{entity_id: {"name": entity, "fields": {api_field_name: (param, source)}}} from the
    responses that return the entity itself (with its id) of actions with one object entity."""
    cur.execute(
        "SELECT n.id, n.name, t.id AS owner_id, t.name AS owner_name FROM model_node n"
        " JOIN model_edge e ON e.source_node_id=n.id AND e.role='object' AND e.invalid_at IS NULL"
        " JOIN model_node t ON t.id=e.target_node_id AND t.kind='entity' AND t.deleted_at IS NULL"
        " WHERE n.sut_id=%s AND n.kind='action' AND n.deleted_at IS NULL ORDER BY n.name",
        (sut_id,),
    )
    rows = cur.fetchall()
    owners: dict[str, list] = {}
    for r in rows:
        owners.setdefault(str(r["id"]), []).append(r)
    out: dict[str, dict] = {}
    for action_rows in owners.values():
        if len(action_rows) != 1:
            continue  # several object entities: not clear which one the response describes
        row = action_rows[0]
        cur.execute(
            "SELECT a.* FROM node_api_link l JOIN api_endpoint a ON a.id=l.api_id"
            " WHERE l.node_id=%s AND l.invalid_at IS NULL ORDER BY a.method, a.path",
            (row["id"],),
        )
        for api in cur.fetchall():
            outputs = [p for p in api_io(api)["outputs"] if "." not in p["name"]]
            if not any(p["name"] == "id" for p in outputs):
                continue  # only responses that return the entity itself
            entry = out.setdefault(str(row["owner_id"]), {"name": row["owner_name"], "fields": {}})
            source = f"Action “{row['name']}” is bound to API {api['method']} {api['path']}"
            for p in outputs:
                entry["fields"].setdefault(p["name"], (p, source))
    return out


def field_suggestions(cur, sut_id) -> list[dict]:
    """Rename / new-field suggestions that make entity fields match the API field names."""
    from testagent.services.attributes import AttributeService

    fields = AttributeService(None, None).list_for_sut(sut_id, cur=cur)
    suggestions: list[dict] = []
    for entity_id, entry in entity_api_fields(cur, sut_id).items():
        own = [f for f in fields if str(f["node_id"]) == entity_id]
        have = {f["name"].lower() for f in own}
        api_names = {n.lower() for n in entry["fields"]}
        missing = [n for n in entry["fields"] if n.lower() not in have]
        extra = [f for f in own if f["name"].lower() not in api_names]
        for name in missing:
            param, source = entry["fields"][name]
            cands = [f for f in extra if rename_match(f["name"], name)]
            rival = [n for n in missing if cands and rename_match(cands[0]["name"], n)]
            payload = {
                "kind": "field",
                "node_id": entity_id,
                "name": name,
                "display_name": param.get("display_name"),
                "data_type": param["data_type"],
                "required": bool(param.get("required")),
                "format": param.get("format"),
                "enum_values": param.get("enum_values") or [],
                "description": param.get("description"),
            }
            if len(cands) == 1 and len(rival) == 1:
                old = cands[0]
                extra.remove(old)
                payload["rename_from"] = old["name"]
                payload["reason"] = (
                    f"Entity fields follow the API fields: {source} returns {name}, the entity has {old['name']}, "
                    "Suggest a rename (keeps requirement/case links)"
                )
            else:
                payload["reason"] = f"{source} response field, not registered on the entity"
            suggestions.append(payload)
    return suggestions


def suggest_alignment(db, bus, sut_id) -> list[dict]:
    """Store the alignment suggestions (pending, de-duplicated); returns the created rows."""
    from testagent.services.suggestions import SuggestionService

    with db.tx() as cur:
        items = field_suggestions(cur, sut_id)
        return SuggestionService(db, bus).add_many(cur, sut_id, items)
