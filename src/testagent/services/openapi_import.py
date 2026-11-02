"""Import the SUT's OpenAPI document into the API registry (method, path, name, schemas).

Existing endpoints (same method+path) keep their name/code_ref/node links; only empty names and
the schemas are filled in. $refs are inlined (depth-limited) so agents see self-contained
schemas."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from psycopg.types.json import Jsonb

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.io_spec import keep_order

METHODS = ("get", "post", "put", "patch", "delete")
MAX_DEPTH = 8


def fetch_openapi(url: str, timeout_s: float = 10) -> dict:
    if not url.startswith(("http://", "https://")):
        raise AppError("VALIDATION", "The OpenAPI address must be an http(s) URL")
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310 (http only)
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise AppError("UPSTREAM", f"Failed to read OpenAPI: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        raise AppError("VALIDATION", "Not a valid OpenAPI document (no paths)")
    return data


def inline_refs(spec: dict, node: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return {"description": "(nested schema truncated)"}
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            target: Any = spec
            for part in node["$ref"].lstrip("#/").split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            rest = {k: v for k, v in node.items() if k != "$ref"}
            return {**inline_refs(spec, target, depth + 1), **inline_refs(spec, rest, depth + 1)}
        return {k: inline_refs(spec, v, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [inline_refs(spec, v, depth + 1) for v in node]
    return node


def _json_schema(spec: dict, content: dict | None) -> dict | None:
    for media, body in (content or {}).items():
        if ("json" in media or "form" in media) and isinstance(body, dict) and body.get("schema"):
            return keep_order(inline_refs(spec, body["schema"]))
    return None


def _media(content: dict | None) -> str | None:
    """Preferred content type: JSON first, then forms, else the first one listed."""
    types = list((content or {}).keys())
    for want in ("json", "form"):
        for media in types:
            if want in media:
                return media
    return types[0] if types else None


def is_default_summary(name: str | None, operation_id: str | None) -> bool:
    """FastAPI's fallback summary ("Create Order" for create_order) is not a real name."""
    if not name or not operation_id:
        return not name
    return operation_id.lower().startswith(name.strip().replace(" ", "_").lower())


def parse_operations(spec: dict) -> list[dict]:
    out = []
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") or []
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            params = [keep_order(inline_refs(spec, p)) for p in [*shared, *(op.get("parameters") or [])]]
            request: dict[str, Any] = {}
            body = _json_schema(spec, (op.get("requestBody") or {}).get("content"))
            if body is not None:
                request["body"] = body
                request["body_required"] = bool((op.get("requestBody") or {}).get("required"))
            if params:
                request["parameters"] = [
                    {k: p.get(k) for k in ("name", "in", "required", "schema", "description") if p.get(k) is not None}
                    for p in params
                    if isinstance(p, dict)
                ]
            responses = {}
            response_media = None
            for code, resp in (op.get("responses") or {}).items():
                if isinstance(resp, dict):
                    schema = _json_schema(spec, resp.get("content"))
                    responses[str(code)] = {
                        "description": resp.get("description"),
                        **({"schema": schema} if schema is not None else {}),
                    }
                    if str(code).startswith("2") and response_media is None:
                        response_media = _media(resp.get("content"))
            out.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "name": op.get("summary") or op.get("operationId"),
                    "description": op.get("description") or None,
                    "request_content_type": _media((op.get("requestBody") or {}).get("content")),
                    "response_content_type": response_media,
                    "operation_id": op.get("operationId"),
                    "request_schema": request or None,
                    "response_schema": responses or None,
                }
            )
    return out


class OpenApiImportService:
    def __init__(self, db, bus: EventBus, actor: str = "local-user"):
        self.db = db
        self.bus = bus
        self.actor = actor

    def source_url(self, sut_id, environment_id=None, url: str | None = None) -> str:
        if url:
            return url
        with self.db.tx() as cur:
            cur.execute(
                "SELECT base_url FROM environment WHERE sut_id=%s"
                " AND (%s::uuid IS NULL OR id=%s) ORDER BY created_at LIMIT 1",
                (sut_id, environment_id, environment_id),
            )
            row = cur.fetchone()
        if row is None:
            raise AppError(
                "VALIDATION", "Register an execution environment first, or enter the OpenAPI address directly"
            )
        return row["base_url"].rstrip("/") + "/openapi.json"

    def import_spec(self, sut_id, spec: dict, source: str = "openapi") -> dict:
        ops = parse_operations(spec)
        created = updated = 0
        with self.db.tx() as cur:
            cur.execute("SELECT 1 FROM sut WHERE id=%s", (sut_id,))
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "SUT not found")
            for op in ops:
                cur.execute(
                    "SELECT id, name, description, operation_id FROM api_endpoint"
                    " WHERE sut_id=%s AND method=%s AND path=%s",
                    (sut_id, op["method"], op["path"]),
                )
                row = cur.fetchone()
                req = Jsonb(op["request_schema"]) if op["request_schema"] else None
                resp = Jsonb(op["response_schema"]) if op["response_schema"] else None
                if row is None:
                    cur.execute(
                        "INSERT INTO api_endpoint(sut_id, method, path, name, description,"
                        " operation_id, request_schema, response_schema, schema_source,"
                        " request_content_type, response_content_type)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'openapi',%s,%s)",
                        (
                            sut_id,
                            op["method"],
                            op["path"],
                            op["name"],
                            op["description"],
                            op["operation_id"],
                            req,
                            resp,
                            op["request_content_type"],
                            op["response_content_type"],
                        ),
                    )
                    created += 1
                else:
                    # a name / purpose typed by a person wins; FastAPI's fallback summary and
                    # empty descriptions are replaced by what the document says
                    name = row["name"]
                    if is_default_summary(name, row["operation_id"] or op["operation_id"]):
                        name = op["name"] or name
                    cur.execute(
                        "UPDATE api_endpoint SET name=%s,"
                        " description=coalesce(nullif(btrim(description), ''), %s),"
                        " operation_id=%s, request_schema=%s, response_schema=%s,"
                        " schema_source='openapi', request_content_type=%s,"
                        " response_content_type=%s WHERE id=%s",
                        (
                            name,
                            op["description"],
                            op["operation_id"],
                            req,
                            resp,
                            op["request_content_type"],
                            op["response_content_type"],
                            row["id"],
                        ),
                    )
                    updated += 1
            log_change(
                cur,
                "sut",
                sut_id,
                "import_openapi",
                self.actor,
                {"source": source, "created": created, "updated": updated},
            )
        self.bus.publish("api_endpoint.imported", {"sut_id": str(sut_id)})
        return {"created": created, "updated": updated, "total": len(ops), "source": source}

    def import_from(self, sut_id, environment_id=None, url: str | None = None) -> dict:
        src = self.source_url(sut_id, environment_id, url)
        return self.import_spec(sut_id, fetch_openapi(src), source=src)
