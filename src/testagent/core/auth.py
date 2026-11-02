"""Launcher token auth + loopback Host / same-Origin checks."""

from __future__ import annotations

import secrets

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from testagent.core.errors import AppError

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PUBLIC_PATHS = {"/api/v1/health"}


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _error(err: AppError) -> JSONResponse:
    return JSONResponse(status_code=err.status, content=err.body())


class LocalAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str, allowed_hosts: list[str] | tuple[str, ...] = ()):
        super().__init__(app)
        self._token = token
        self._hosts = LOOPBACK | {h.lower() for h in allowed_hosts}

    async def dispatch(self, request, call_next):
        if (request.url.hostname or "").lower() not in self._hosts:
            return _error(AppError("FORBIDDEN_ORIGIN", "The platform only accepts local connections"))
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return _error(AppError("FORBIDDEN_ORIGIN", "Request origin does not match the platform address"))
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC_PATHS:
            header = request.headers.get("authorization", "")
            scheme, _, supplied = header.partition(" ")
            if scheme.lower() != "bearer" or not secrets.compare_digest(supplied.encode(), self._token.encode()):
                return _error(
                    AppError(
                        "AUTH_REQUIRED",
                        "Sign-in required: reopen the platform from the launcher (or use the access token)",
                    )
                )
        return await call_next(request)
