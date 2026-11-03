"""Sign-in for every /api/ request: Host / Origin checks, session cookie, CSRF header (t98u).

Browsers sign in with a user name and password (or, on the desktop, with a one-time launcher
ticket) and get an HttpOnly session cookie. Writes also need the session's CSRF token in the
``X-CSRF-Token`` header. The signed-in user name becomes the actor of everything the request
changes (``testagent.core.actor``)."""

from __future__ import annotations

import secrets

from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from testagent.core.actor import reset_actor, set_actor
from testagent.core.errors import AppError

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PUBLIC_PATHS = {"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/ticket", "/api/v1/auth/status"}
# reachable while the user still has to replace an initial password
PASSWORD_CHANGE_PATHS = {"/api/v1/auth/me", "/api/v1/auth/password", "/api/v1/auth/logout"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SECURE_COOKIE = "__Host-ta_session"  # https: Secure, Path=/, no Domain
PLAIN_COOKIE = "ta_session"  # plain http on localhost (desktop launcher, SSH tunnel)
CSRF_HEADER = "x-csrf-token"


def session_cookie(request) -> str | None:
    return request.cookies.get(SECURE_COOKIE) or request.cookies.get(PLAIN_COOKIE)


def _error(err: AppError) -> JSONResponse:
    return JSONResponse(status_code=err.status, content=err.body())


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth, allowed_hosts: list[str] | tuple[str, ...] = ()):
        super().__init__(app)
        self._auth = auth  # AuthService
        self._hosts = LOOPBACK | {h.lower() for h in allowed_hosts}

    async def dispatch(self, request, call_next):
        if (request.url.hostname or "").lower() not in self._hosts:
            return _error(AppError("FORBIDDEN_ORIGIN", "This address is not configured for the platform"))
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return _error(AppError("FORBIDDEN_ORIGIN", "Request origin does not match the platform address"))
        path = request.url.path
        request.state.session = None
        if not path.startswith("/api/") or path in PUBLIC_PATHS:
            return await call_next(request)
        session = await run_in_threadpool(self._auth.resolve, session_cookie(request))
        if session is None:
            return _error(AppError("AUTH_REQUIRED", "Sign-in required"))
        if request.method not in SAFE_METHODS:
            supplied = request.headers.get(CSRF_HEADER, "")
            if not secrets.compare_digest(supplied.encode(), session["csrf_token"].encode()):
                return _error(AppError("CSRF_FAILED", "Missing or wrong CSRF token: reload the page"))
        if session["must_change_password"] and path not in PASSWORD_CHANGE_PATHS:
            return _error(AppError("PASSWORD_CHANGE_REQUIRED", "Change your initial password first"))
        request.state.session = session
        token = set_actor(session["username"])
        try:
            return await call_next(request)
        finally:
            reset_actor(token)


def require_admin(request) -> dict:
    session = getattr(request.state, "session", None)
    if not session or session["role"] != "admin":
        raise AppError("FORBIDDEN", "Only an admin can do this")
    return session
