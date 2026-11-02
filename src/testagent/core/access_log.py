"""Readable access log: one line per request with the route template instead of
raw UUIDs, never the query string (it may carry tokens). GETs log at DEBUG, so the console only
shows writes and errors by default; 4xx/5xx log at WARNING.

the objects in the path are named after the line, e.g.
``POST /api/v1/cases/{case_id}/debug → 200 (812 ms) · case “Large purchase order… (TC-001)”``."""

from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("testagent.access")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def route_of(scope: dict) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path or UUID_RE.sub("{id}", scope.get("path", ""))


def line(method: str, route: str, status: int, ms: float) -> str:
    return f"{method} {route} → {status} ({ms:.0f} ms)"


def level(method: str, status: int) -> int:
    if status >= 400:
        return logging.WARNING
    return logging.DEBUG if method in ("GET", "HEAD", "OPTIONS") else logging.INFO


def refs_suffix(scope: dict, path: str) -> str:
    """Names of the objects whose ids appear in the path (best effort, never raises)."""
    ids = UUID_RE.findall(path)
    app = scope.get("app")
    db = getattr(getattr(app, "state", None), "db", None)
    if not ids or db is None:
        return ""
    try:
        from testagent.services.labels import describe, resolve_refs

        text = describe(resolve_refs(db, ids), ids)
    except Exception:  # noqa: BLE001 - logging must never break a request
        return ""
    return f" · {text}" if text else ""


class AccessLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        started = time.monotonic()
        status = {"code": 500}

        async def _send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            method = scope.get("method", "")
            ms = (time.monotonic() - started) * 1000
            lvl = level(method, status["code"])
            if log.isEnabledFor(lvl):
                text = line(method, route_of(scope), status["code"], ms)
                path = scope.get("path", "")
                if UUID_RE.search(path):
                    import anyio

                    text += await anyio.to_thread.run_sync(refs_suffix, scope, path)
                log.log(lvl, text)
