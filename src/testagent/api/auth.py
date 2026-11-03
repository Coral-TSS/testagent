"""/api/v1/auth (sign-in, sign-out, me, password) and /api/v1/users (admin only)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from testagent.core.auth import LOOPBACK, PLAIN_COOKIE, SECURE_COOKIE, require_admin, session_cookie
from testagent.core.errors import AppError
from testagent.services.auth import AuthService

router = APIRouter(prefix="/api/v1")


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(max_length=200)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class UserIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    display_name: str = Field(default="", max_length=100)
    role: str = Field(default="member", pattern="^(admin|member)$")
    password: str = Field(max_length=256, description="initial password; the user must change it on first sign-in")


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, pattern="^(admin|member)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=256, description="reset; user must change it")
    unlock: bool | None = None


def _auth(request: Request, actor: str = "system") -> AuthService:
    base: AuthService = request.app.state.auth
    return AuthService(base.db, base.idle_hours, base.max_days, actor=actor)


def _secure(request: Request) -> bool:
    mode = request.app.state.cookie_secure
    if mode in ("true", "false"):
        return mode == "true"
    return request.url.scheme == "https"


def _set_cookie(request: Request, response: Response, raw: str) -> None:
    secure = _secure(request)
    response.set_cookie(
        SECURE_COOKIE if secure else PLAIN_COOKIE,
        raw,
        max_age=int(request.app.state.auth.max_days * 86400),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(SECURE_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(PLAIN_COOKIE, path="/", httponly=True, samesite="lax")


def _me(user: dict, csrf: str) -> dict:
    keys = ("id", "username", "display_name", "role", "must_change_password")
    return {**{k: user[k] for k in keys}, "csrf_token": csrf}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _start_session(request: Request, response: Response, user: dict) -> dict:
    auth = _auth(request)
    old = auth.resolve(session_cookie(request))
    if old:  # rotate: never keep a session id across a sign-in
        auth.revoke(old["session_id"])
    raw, csrf = auth.create_session(user["id"], _client_ip(request), request.headers.get("user-agent"))
    _set_cookie(request, response, raw)
    return _me(user, csrf)


@router.get("/auth/status")
def auth_status(request: Request):
    """For the sign-in page: is there any account yet?"""
    return {"has_users": _auth(request).count() > 0}


@router.post("/auth/login")
def login(request: Request, response: Response, body: LoginIn):
    request.app.state.login_limiter.hit(_client_ip(request))
    user = _auth(request).authenticate(body.username, body.password)
    return _start_session(request, response, user)


@router.post("/auth/ticket")
def redeem_ticket(request: Request, response: Response, body: TicketIn):
    """Desktop launcher: exchange the one-time ticket from the URL fragment for a session."""
    if (request.url.hostname or "").lower() not in LOOPBACK:
        raise AppError("FORBIDDEN", "Launcher tickets only work on this computer (localhost)")
    request.app.state.login_limiter.hit(_client_ip(request))
    user_id = request.app.state.tickets.redeem(body.ticket)
    if user_id is None:
        raise AppError("LOGIN_FAILED", "The sign-in link has expired: start the launcher again or sign in")
    user = _auth(request).get_user(user_id)
    if not user["is_active"]:
        raise AppError("LOGIN_FAILED", "This account is disabled")
    return _start_session(request, response, user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request):
    response = Response(status_code=204)
    session = request.state.session
    if session:
        _auth(request).revoke(session["session_id"])
    _clear_cookies(response)
    return response


@router.get("/auth/me")
def me(request: Request):
    s = request.state.session
    user = {"id": str(s["user_id"]), **{k: s[k] for k in ("username", "display_name", "role", "must_change_password")}}
    return _me(user, s["csrf_token"])


@router.post("/auth/password")
def change_password(request: Request, body: PasswordIn):
    s = request.state.session
    user = _auth(request, s["username"]).change_password(
        s["user_id"], body.current_password, body.new_password, keep_session_id=s["session_id"]
    )
    return _me(user, s["csrf_token"])


@router.get("/users")
def list_users(request: Request):
    require_admin(request)
    return _auth(request).list_users()


@router.post("/users", status_code=201)
def create_user(request: Request, body: UserIn):
    admin = require_admin(request)
    return _auth(request, admin["username"]).create_user(
        body.username, body.password, role=body.role, display_name=body.display_name, must_change_password=True
    )


@router.patch("/users/{user_id}")
def patch_user(request: Request, user_id: UUID, body: UserPatch):
    admin = require_admin(request)
    patch = body.model_dump(exclude_unset=True)
    if str(user_id) == str(admin["user_id"]) and (patch.get("is_active") is False or patch.get("role") == "member"):
        raise AppError("CONFLICT", "You cannot disable or demote your own account")
    return _auth(request, admin["username"]).update_user(user_id, patch)
