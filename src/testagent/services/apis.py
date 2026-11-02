"""API registry: endpoints per SUT and links from action nodes."""

from __future__ import annotations

from psycopg.types.json import Jsonb

from testagent.core.errors import AppError
from testagent.services.base import Crud
from testagent.services.changelog import log_change
from testagent.services.io_spec import (
    api_io,
    apply_request_fields,
    apply_response_fields,
    bind_fields,
    merge_params,
    validate_params,
)

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


SCHEMA_KEYS = ("request_schema", "response_schema")


def _wrap(values: dict) -> dict:
    out = dict(values)
    if any(out.get(k) is not None for k in SCHEMA_KEYS):
        out["schema_source"] = "manual"
        req = out.get("request_schema") or {}
        if req.get("body") and not out.get("request_content_type"):
            out["request_content_type"] = "application/json"
        if out.get("response_schema") and not out.get("response_content_type"):
            out["response_content_type"] = "application/json"
    for k in SCHEMA_KEYS:
        if out.get(k) is not None:
            out[k] = Jsonb(out[k])
    return out


def with_io(row: dict) -> dict:
    """Readable inputs/outputs (parameters, body fields, response fields) next to the schema."""
    return {**row, "io": api_io(row)}


class ApiService(Crud):
    table, entity, label = "api_endpoint", "api_endpoint", "API"

    def create(self, values: dict) -> dict:
        values = self._fields_to_schema(None, values)
        return with_io(super().create(_wrap(values)))

    def update(self, id_, values: dict) -> dict:
        if "request_fields" in values or "response_fields" in values:
            values = self._fields_to_schema(self.get(id_), values)
        return with_io(super().update(id_, _wrap(values)))

    def get(self, id_) -> dict:
        return with_io(super().get(id_))

    def _fields_to_schema(self, current: dict | None, values: dict) -> dict:
        """Edited field tables (request_fields / response_fields) are written back into the
        stored JSON schema; keys the tables do not show (limits, titles...) are kept."""
        values = dict(values)
        req_fields = values.pop("request_fields", None)
        resp_fields = values.pop("response_fields", None)
        if req_fields is None and resp_fields is None:
            return values

        def plain(items):  # API fields describe the wire format; no entity binding here
            return [{k: v for k, v in dict(i).items() if k not in ("field", "attribute_id")} for i in items]

        with self.db.tx() as cur:
            if req_fields is not None:
                params = validate_params(cur, None, plain(req_fields), "request_fields")
                base = values.get("request_schema", (current or {}).get("request_schema"))
                values["request_schema"] = apply_request_fields(base, params)
            if resp_fields is not None:
                params = validate_params(cur, None, plain(resp_fields), "response_fields")
                base = values.get("response_schema", (current or {}).get("response_schema"))
                values["response_schema"] = apply_response_fields(base, params)
        return values

    def list_for_sut(self, sut_id) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute("SELECT 1 FROM sut WHERE id=%s", (sut_id,))
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "SUT not found")
            cur.execute(
                "SELECT a.*, coalesce(array_agg(n.name ORDER BY n.name)"
                " FILTER (WHERE n.id IS NOT NULL), '{}') AS node_names"
                " FROM api_endpoint a"
                " LEFT JOIN node_api_link l ON l.api_id=a.id AND l.invalid_at IS NULL"
                " LEFT JOIN model_node n ON n.id=l.node_id AND n.deleted_at IS NULL"
                " WHERE a.sut_id=%s GROUP BY a.id ORDER BY a.path, a.method",
                (sut_id,),
            )
            return [with_io(r) for r in cur.fetchall()]

    def set_node_apis(self, node_id, api_ids: list) -> list[dict]:
        """Replace the API links of an action node (only action nodes may link APIs)."""
        unique = list(dict.fromkeys(str(a) for a in api_ids))
        with self.db.tx() as cur:
            cur.execute(
                "SELECT id, sut_id, kind FROM model_node WHERE id=%s AND deleted_at IS NULL FOR UPDATE",
                (node_id,),
            )
            node = cur.fetchone()
            if node is None:
                raise AppError("NOT_FOUND", "Node not found")
            if node["kind"] != "action" and unique:
                raise AppError("VALIDATION", "Only action nodes can be linked to APIs")
            if unique:
                cur.execute("SELECT id, sut_id FROM api_endpoint WHERE id = ANY(%s::uuid[])", (unique,))
                found = {str(r["id"]): r for r in cur.fetchall()}
                missing = [a for a in unique if a not in found]
                if missing:
                    raise AppError("NOT_FOUND", "API not found", related=missing)
                if any(str(r["sut_id"]) != str(node["sut_id"]) for r in found.values()):
                    raise AppError("VALIDATION", "The API and the node belong to different SUTs")
            cur.execute("DELETE FROM node_api_link WHERE node_id=%s", (node_id,))
            for api_id in unique:
                cur.execute("INSERT INTO node_api_link(node_id, api_id) VALUES (%s,%s)", (node_id, api_id))
            log_change(cur, "model_node", node_id, "set_apis", self.actor, {"api_ids": unique})
            inherited = None
            if unique:  # an action without inputs/outputs inherits them from its APIs
                cur.execute("SELECT inputs, outputs FROM model_node WHERE id=%s", (node_id,))
                io = cur.fetchone()
                if not io["inputs"] and not io["outputs"]:
                    inherited = self._inherit(cur, node_id, replace=False)
            cur.execute(
                "SELECT a.* FROM node_api_link l JOIN api_endpoint a ON a.id=l.api_id"
                " WHERE l.node_id=%s ORDER BY a.path, a.method",
                (node_id,),
            )
            rows = cur.fetchall()
        self.bus.publish("model_node.apis_changed", {"id": str(node_id)})
        if inherited and (inherited["inputs_added"] or inherited["outputs_added"]):
            self.bus.publish("model_node.updated", {"id": str(node_id)})
        return rows

    # ------------------------------------------------------------ action I/O from its APIs
    def _inherit(self, cur, node_id, *, replace: bool) -> dict:
        from testagent.services.attributes import AttributeService

        cur.execute(
            "SELECT id, sut_id, kind, description, inputs, outputs, input_format, output_format"
            " FROM model_node WHERE id=%s AND deleted_at IS NULL FOR UPDATE",
            (node_id,),
        )
        node = cur.fetchone()
        if node is None:
            raise AppError("NOT_FOUND", "Node not found")
        if node["kind"] != "action":
            raise AppError("VALIDATION", "Only action nodes have inputs/outputs")
        cur.execute(
            "SELECT a.* FROM node_api_link l JOIN api_endpoint a ON a.id=l.api_id"
            " WHERE l.node_id=%s AND l.invalid_at IS NULL ORDER BY a.path, a.method",
            (node_id,),
        )
        apis = cur.fetchall()
        if not apis:
            raise AppError("VALIDATION", "This action has no bound API yet")
        fields = AttributeService(self.db, self.bus).list_for_sut(node["sut_id"], cur=cur)
        cur.execute(
            "SELECT e.target_node_id FROM model_edge e JOIN model_node t ON t.id=e.target_node_id"
            " WHERE e.source_node_id=%s AND e.role='object' AND e.invalid_at IS NULL"
            " AND t.kind='entity' AND t.deleted_at IS NULL",
            (node_id,),
        )
        owners = [r["target_node_id"] for r in cur.fetchall()]
        inputs = [] if replace else list(node["inputs"] or [])
        outputs = [] if replace else list(node["outputs"] or [])
        added_in = added_out = 0
        formats_in, formats_out, purposes = [], [], []
        for api in apis:
            io = api_io(api)
            inputs, n = merge_params(inputs, bind_fields(io["inputs"], fields, owners))
            added_in += n
            outputs, n = merge_params(outputs, bind_fields(io["outputs"], fields, owners))
            added_out += n
            ref = f"{api['method']} {api['path']}"
            many = len(apis) > 1
            if io["input_format"]:
                formats_in.append(f"{ref}: {io['input_format']}" if many else io["input_format"])
            if io["output_format"]:
                formats_out.append(f"{ref}: {io['output_format']}" if many else io["output_format"])
            if api.get("description") or api.get("name"):
                purposes.append(api.get("description") or api.get("name"))
        updates = {"inputs": Jsonb(inputs), "outputs": Jsonb(outputs)}
        if replace or not node["input_format"]:
            updates["input_format"] = "; ".join(formats_in)[:500] or None
        if replace or not node["output_format"]:
            updates["output_format"] = "; ".join(formats_out)[:500] or None
        filled_purpose = False
        if not (node["description"] or "").strip() and purposes:
            updates["description"] = "; ".join(dict.fromkeys(purposes))
            filled_purpose = True
        sets = ", ".join(f"{k}=%s" for k in updates)
        cur.execute(f"UPDATE model_node SET {sets} WHERE id=%s", (*updates.values(), node_id))
        summary = {
            "inputs_added": added_in,
            "outputs_added": added_out,
            "purpose_filled": filled_purpose,
            "apis": [f"{a['method']} {a['path']}" for a in apis],
            "replace": replace,
        }
        log_change(cur, "model_node", node_id, "io_from_apis", self.actor, summary)
        return summary

    def inherit_io(self, node_id, *, replace: bool = False) -> dict:
        with self.db.tx() as cur:
            summary = self._inherit(cur, node_id, replace=replace)
        self.bus.publish("model_node.updated", {"id": str(node_id)})
        return summary
