"""Model-completion suggestions: de-duplicated, accepted or rejected by a person (C01)."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.attributes import AttributeService
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human
from testagent.services.io_spec import merge_params, validate_params
from testagent.services.model import ModelService, find_similar_node, normalize_name


def _norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


def dedup_key(payload: dict) -> str:
    if payload["kind"] == "node":
        return f"node:{payload['node_kind']}:{normalize_name(payload['name'])}"
    if payload["kind"] == "field":
        return f"field:{payload['node_id']}:{_norm(payload['name'])}"
    if payload["kind"] == "io":
        return f"io:{payload['node_id']}"
    if payload["kind"] == "link":
        ends = sorted([str(payload["from_node_id"]), str(payload["to_node_id"])])
        return f"link:{ends[0]}:{ends[1]}:{payload.get('fk_attribute_id') or ''}"
    if payload["kind"] == "rules":
        return f"rules:{payload['node_id']}"
    return f"attr:{payload['node_id']}:{payload['attr']}:{_norm(payload['text'])}"


NODE_NAME_SQL = (
    "(SELECT n.name FROM model_node n WHERE n.id::text = s.payload->>'node_id')"
    " AS payload_node_name,"
    " (SELECT n.name FROM model_node n WHERE n.id = s.resolved_node_id) AS resolved_node_name"
)


def with_node_name(row: dict) -> dict:
    """Older suggestions stored only node_id: fill payload.node_name for display (7b)."""
    name = row.pop("payload_node_name", None)
    payload = dict(row.get("payload") or {})
    if payload.get("node_id") and not payload.get("node_name") and name:
        payload["node_name"] = name
    row["payload"] = payload
    return row


class SuggestionService:
    def __init__(self, db, bus: EventBus, actor: str | None = None):
        self.db = db
        self.bus = bus
        self.actor = actor or current_actor()

    def add_many(self, cur, sut_id, items: list[dict], *, agent_run_id=None) -> list[dict]:
        """Insert suggestions, skipping ones already pending or already present in the model."""
        created = []
        for item in items:
            payload = {k: (str(v) if k.endswith("_id") and v else v) for k, v in item.items()}
            requirement_id = payload.pop("requirement_id", None)
            for key in ("inputs", "outputs"):  # bind Entity.field now; unknown refs become notes
                if payload.get(key):
                    payload[key] = validate_params(cur, sut_id, payload[key], key, strict=False)
                elif key in payload:
                    payload.pop(key)
            if payload["kind"] == "link":
                if not self._link_payload(cur, sut_id, payload):
                    continue
            elif payload["kind"] == "rules":
                if not self._rules_payload(cur, sut_id, payload):
                    continue
            elif payload["kind"] == "io":
                cur.execute(
                    "SELECT name, kind, description, inputs, outputs FROM model_node"
                    " WHERE id=%s AND deleted_at IS NULL",
                    (payload["node_id"],),
                )
                owner = cur.fetchone()
                if owner is None or owner["kind"] != "action":
                    continue
                payload["node_name"] = owner["name"]
                _, new_in = merge_params(owner["inputs"] or [], payload.get("inputs") or [])
                _, new_out = merge_params(owner["outputs"] or [], payload.get("outputs") or [])
                new_purpose = bool(payload.get("description")) and not (owner["description"] or "").strip()
                if not (new_in or new_out or new_purpose):
                    continue  # nothing the action does not already describe
            elif payload["kind"] == "node":
                if find_similar_node(cur, sut_id, payload["node_kind"], payload["name"]):
                    continue  # 7(d): an equivalent node already exists
            elif payload["kind"] == "field":
                cur.execute(
                    "SELECT name FROM model_node WHERE id=%s AND deleted_at IS NULL",
                    (payload["node_id"],),
                )
                owner = cur.fetchone()
                if owner is None:
                    continue
                payload["node_name"] = owner["name"]
                cur.execute(
                    "SELECT 1 FROM entity_attribute WHERE node_id=%s AND deleted_at IS NULL"
                    " AND (lower(name)=%s OR lower(coalesce(display_name,''))=%s)",
                    (payload["node_id"], _norm(payload["name"]), _norm(payload["name"])),
                )
                if cur.fetchone():
                    continue
                if payload.get("rename_from"):  # rename an existing field to the API name
                    cur.execute(
                        "SELECT id, name FROM entity_attribute WHERE node_id=%s"
                        " AND deleted_at IS NULL AND lower(name)=%s",
                        (payload["node_id"], _norm(payload["rename_from"])),
                    )
                    old = cur.fetchone()
                    if old is None:
                        payload.pop("rename_from")
                        payload.pop("rename_attribute_id", None)
                    else:
                        payload["rename_from"] = old["name"]
                        payload["rename_attribute_id"] = str(old["id"])
                else:
                    payload.pop("rename_attribute_id", None)
            else:
                cur.execute("SELECT name FROM model_node WHERE id=%s", (payload["node_id"],))
                owner = cur.fetchone()
                if owner is not None:
                    payload["node_name"] = owner["name"]
                cur.execute(
                    "SELECT 1 FROM model_node WHERE id=%s AND EXISTS (SELECT 1 FROM"
                    " jsonb_array_elements(attributes->%s) i WHERE lower(i->>'text')=%s)",
                    (payload["node_id"], payload["attr"], _norm(payload["text"])),
                )
                if cur.fetchone():
                    continue
            cur.execute(
                "INSERT INTO model_suggestion(sut_id, requirement_id, agent_run_id, payload, kind,"
                " dedup_key) VALUES (%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (sut_id, dedup_key) WHERE status='pending' DO NOTHING RETURNING *",
                (
                    sut_id,
                    requirement_id,
                    agent_run_id,
                    Jsonb(payload),
                    payload["kind"],
                    dedup_key(payload),
                ),
            )
            row = cur.fetchone()
            if row:
                created.append(row)
        return created

    @staticmethod
    def _link_payload(cur, sut_id, payload: dict) -> bool:
        """Fill entity names; False when the ends are not entities or the link exists."""
        cur.execute(
            "SELECT id::text AS id, name FROM model_node WHERE id::text IN (%s,%s)"
            " AND sut_id=%s AND kind='entity' AND deleted_at IS NULL",
            (str(payload["from_node_id"]), str(payload["to_node_id"]), sut_id),
        )
        names = {r["id"]: r["name"] for r in cur.fetchall()}
        if str(payload["from_node_id"]) not in names or str(payload["to_node_id"]) not in names:
            return False
        payload["from_name"] = names[str(payload["from_node_id"])]
        payload["to_name"] = names[str(payload["to_node_id"])]
        payload.setdefault("cardinality", "many_to_one")
        cur.execute(
            "SELECT 1 FROM model_link WHERE sut_id=%s AND deleted_at IS NULL AND ("
            " (from_node_id::text=%s AND to_node_id::text=%s AND forward_name=%s)"
            " OR (%s::text IS NOT NULL AND fk_attribute_id::text=%s))",
            (
                sut_id,
                str(payload["from_node_id"]),
                str(payload["to_node_id"]),
                payload.get("forward_name") or "",
                payload.get("fk_attribute_id"),
                payload.get("fk_attribute_id"),
            ),
        )
        return cur.fetchone() is None

    @staticmethod
    def _rules_payload(cur, sut_id, payload: dict) -> bool:
        """Bind Entity.field, drop invalid items and those the action already has."""
        from testagent.services.action_rules import (
            effect_text,
            precondition_text,
            validate_rules,
        )

        cur.execute(
            "SELECT name, kind, preconditions, effects FROM model_node WHERE id::text=%s"
            " AND sut_id=%s AND deleted_at IS NULL",
            (str(payload["node_id"]), sut_id),
        )
        owner = cur.fetchone()
        if owner is None or owner["kind"] != "action":
            return False
        payload["node_name"] = owner["name"]
        clean = validate_rules(
            cur,
            sut_id,
            {k: payload.get(k) or [] for k in ("preconditions", "effects")},
            strict=False,
        )
        have_pre = {precondition_text(p) for p in owner["preconditions"] or []}
        have_eff = {effect_text(e) for e in owner["effects"] or []}
        payload["preconditions"] = [p for p in clean["preconditions"] if precondition_text(p) not in have_pre]
        payload["effects"] = [e for e in clean["effects"] if effect_text(e) not in have_eff]
        return bool(payload["preconditions"] or payload["effects"])

    def list(self, sut_id, status: str | None = None) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                f"SELECT s.*, r.code AS requirement_code, {NODE_NAME_SQL} FROM model_suggestion s"
                " LEFT JOIN requirement r ON r.id=s.requirement_id"
                " WHERE s.sut_id=%s AND (%s::text IS NULL OR s.status=%s) ORDER BY s.created_at",
                (sut_id, status, status),
            )
            return [with_node_name(r) for r in cur.fetchall()]

    def _pending(self, cur, sugg_id) -> dict:
        cur.execute("SELECT * FROM model_suggestion WHERE id=%s FOR UPDATE", (sugg_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Suggestion not found")
        if row["status"] != "pending":
            raise AppError("CONFLICT", "This suggestion has already been handled")
        return row

    def accept(self, sugg_id, overrides: dict | None = None) -> dict:
        ensure_human(self.actor, "Accept model suggestion")
        overrides = overrides or {}
        model = ModelService(self.db, self.bus, self.actor)
        with self.db.tx() as cur:
            sugg = self._pending(cur, sugg_id)
        payload = sugg["payload"]
        field = None
        link = None
        if sugg["kind"] == "link":
            from testagent.services.links import FIELDS, LinkService

            data = {k: payload.get(k) for k in FIELDS if k in payload}
            data.update(
                {
                    k: overrides[k]
                    for k in (
                        "forward_name",
                        "reverse_name",
                        "forward_api_name",
                        "reverse_api_name",
                        "cardinality",
                        "required",
                        "description",
                    )
                    if k in overrides
                }
            )
            data.setdefault("description", payload.get("reason"))
            link = LinkService(self.db, self.bus, self.actor).create(sugg["sut_id"], data)
            node = model.get_node(payload["from_node_id"])
        elif sugg["kind"] == "rules":
            from testagent.services.action_rules import effect_text, precondition_text

            current = model.get_node(payload["node_id"])
            pre = list(current.get("preconditions") or [])
            eff = list(current.get("effects") or [])
            pre += [
                p
                for p in payload.get("preconditions") or []
                if precondition_text(p) not in {precondition_text(x) for x in pre}
            ]
            eff += [e for e in payload.get("effects") or [] if effect_text(e) not in {effect_text(x) for x in eff}]
            node = model.update_node(payload["node_id"], {"preconditions": pre, "effects": eff})
        elif sugg["kind"] == "node":
            name = overrides.get("name") or payload["name"]
            with self.db.tx() as cur:
                similar = find_similar_node(cur, sugg["sut_id"], payload["node_kind"], name)
            if similar is not None and not overrides.get("name"):
                node = model.get_node(similar["id"])  # 7(d): link instead of duplicating
            else:
                data = {
                    "kind": payload["node_kind"],
                    "name": name,
                    "description": payload.get("description"),
                    "module_id": overrides.get("module_id"),
                    "attributes": payload.get("attributes") or {},
                }
                if payload["node_kind"] == "action":
                    for key in ("inputs", "outputs", "input_format", "output_format"):
                        if payload.get(key):
                            data[key] = payload[key]
                node = model.create_node(sugg["sut_id"], data)
        elif sugg["kind"] == "field" and payload.get("rename_attribute_id"):
            # entity fields follow the API names: rename in place, links are kept
            data = {
                "name": overrides.get("name") or payload["name"],
                "data_type": payload.get("data_type") or "string",
                "required": bool(payload.get("required")),
                "enum_values": payload.get("enum_values") or [],
            }
            for key in ("display_name", "unit", "format", "description"):
                if payload.get(key):
                    data[key] = payload[key]
            field = AttributeService(self.db, self.bus, self.actor).update(payload["rename_attribute_id"], data)
            node = model.get_node(payload["node_id"])
        elif sugg["kind"] == "field":
            field = AttributeService(self.db, self.bus, self.actor).create(
                payload["node_id"],
                {
                    "name": overrides.get("name") or payload["name"],
                    "display_name": payload.get("display_name"),
                    "data_type": payload.get("data_type") or "string",
                    "unit": payload.get("unit"),
                    "required": bool(payload.get("required")),
                    "format": payload.get("format"),
                    "enum_values": payload.get("enum_values") or [],
                    "description": payload.get("description"),
                },
            )
            node = model.get_node(payload["node_id"])
        elif sugg["kind"] == "io":
            current = model.get_node(payload["node_id"])
            inputs, _ = merge_params(current.get("inputs") or [], payload.get("inputs") or [])
            outputs, _ = merge_params(current.get("outputs") or [], payload.get("outputs") or [])
            data = {"inputs": inputs, "outputs": outputs}
            if payload.get("description") and not (current.get("description") or "").strip():
                data["description"] = payload["description"]
            for key in ("input_format", "output_format"):
                if payload.get(key) and not current.get(key):
                    data[key] = payload[key]
            node = model.update_node(payload["node_id"], data)
        else:
            current = model.get_node(payload["node_id"])["attributes"]
            items = list(current.get(payload["attr"], []))
            items.append({k: payload[k] for k in ("text", "expr") if payload.get(k)})
            node = model.update_node(payload["node_id"], {"attributes": {**current, payload["attr"]: items}})
        backfilled = False
        with self.db.tx() as cur:
            self._pending(cur, sugg_id)
            if sugg["requirement_id"] and payload.get("part"):
                backfilled = self._backfill(cur, sugg["requirement_id"], payload, node, field, link)
            if link is not None:
                payload = {**payload, "link_id": str(link["id"])}
            cur.execute(
                "UPDATE model_suggestion SET status='accepted', resolved_node_id=%s, decided_by=%s,"
                " payload=%s WHERE id=%s RETURNING *",
                (node["id"], self.actor, Jsonb(payload), sugg_id),
            )
            row = cur.fetchone()
            log_change(cur, "model_suggestion", sugg_id, "accept", self.actor, {"node_id": node["id"]})
        self.bus.publish("model_suggestion.accepted", {"id": str(sugg_id)})
        return {**row, "backfilled": backfilled}

    @staticmethod
    def _backfill(cur, requirement_id, payload: dict, node: dict, field: dict | None, link=None) -> bool:
        """Link the new node to the requirement part it was missing from (planning only)."""
        cur.execute(
            "SELECT r.id, r.structured, v.status FROM requirement r JOIN version v"
            " ON v.id=r.version_id WHERE r.id=%s FOR UPDATE OF r",
            (requirement_id,),
        )
        req = cur.fetchone()
        if req is None or req["status"] != "planning":
            return False
        part = payload["part"]
        cur.execute(
            "INSERT INTO requirement_node_link(requirement_id, node_id, role) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (requirement_id, node["id"], part),
        )
        structured = req["structured"] or {}
        items = structured.setdefault(part, [])
        wanted = _norm(payload.get("source_text") or payload.get("name") or payload.get("text") or "")
        target = next((i for i in items if i.get("missing") and _norm(i.get("text", "")) == wanted), None) or next(
            (i for i in items if i.get("missing")), None
        )
        if target is None:
            target = {"text": payload.get("name") or payload.get("text")}
            items.append(target)
        target["node_id"] = str(node["id"])
        target["missing"] = False
        if link is not None:
            target["link_id"] = str(link["id"])
            cur.execute(
                "INSERT INTO requirement_link_ref(requirement_id, link_id, role)"
                " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (requirement_id, link["id"], part),
            )
        if field is not None:
            target["attribute_id"] = str(field["id"])
            cur.execute(
                "INSERT INTO requirement_attribute_link(requirement_id, attribute_id, role)"
                " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (requirement_id, field["id"], part),
            )
        cur.execute("UPDATE requirement SET structured=%s WHERE id=%s", (Jsonb(structured), requirement_id))
        return True

    def reject(self, sugg_id, reason: str | None = None) -> dict:
        ensure_human(self.actor, "Reject model suggestion")
        with self.db.tx() as cur:
            self._pending(cur, sugg_id)
            cur.execute(
                "UPDATE model_suggestion SET status='rejected', reason=%s, decided_by=%s WHERE id=%s RETURNING *",
                (reason, self.actor, sugg_id),
            )
            row = cur.fetchone()
            log_change(cur, "model_suggestion", sugg_id, "reject", self.actor, {"reason": reason})
        self.bus.publish("model_suggestion.rejected", {"id": str(sugg_id)})
        return row
