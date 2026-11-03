"""Accounts, sessions, CSRF, lockout, admin-only endpoints and actor attribution (t98u)."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from tests.conftest import TEST_PASSWORD, sign_in

from testagent.core.errors import AppError
from testagent.core.secrets import SecretStore
from testagent.services.auth import MAX_FAILURES, AuthService

V1 = "/api/v1"
NEW_PASSWORD = "brand-new-pass-2"


@pytest.fixture
def make_client(db, tmp_path):
    from testagent.api.app import create_app

    opened = []

    def make(base_url="http://127.0.0.1", **kwargs):
        app = create_app(db, secrets=SecretStore(tmp_path / "s.json"), runtime_dir=tmp_path / "rt", **kwargs)
        c = TestClient(app, base_url=base_url)
        c.__enter__()
        opened.append(c)
        return c

    yield make
    for c in opened:
        c.__exit__(None, None, None)


def _change_log(db, entity: str) -> list[dict]:
    with db.tx() as cur:
        cur.execute("SELECT action, actor FROM change_log WHERE entity=%s ORDER BY id", (entity,))
        return cur.fetchall()


def test_status_login_cookie_and_me(make_client, db):
    c = make_client()
    assert c.get(f"{V1}/auth/status").json() == {"has_users": False}
    AuthService(db).create_user("alice", TEST_PASSWORD, role="member", display_name="Alice")
    assert c.get(f"{V1}/auth/status").json() == {"has_users": True}
    resp = c.post(f"{V1}/auth/login", json={"username": "Alice", "password": TEST_PASSWORD})
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("ta_session=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie  # plain http on localhost
    me = resp.json()
    assert me["username"] == "alice" and me["role"] == "member" and len(me["csrf_token"]) > 20
    assert "password_hash" not in me and TEST_PASSWORD not in str(me)
    assert c.get(f"{V1}/auth/me").json()["csrf_token"] == me["csrf_token"]
    assert c.get(f"{V1}/suts").status_code == 200


def test_https_uses_host_prefixed_secure_cookie(make_client, db):
    c = make_client(base_url="https://203.0.113.10", allowed_hosts=["203.0.113.10"])
    AuthService(db).create_user("alice", TEST_PASSWORD)
    resp = c.post(f"{V1}/auth/login", json={"username": "alice", "password": TEST_PASSWORD})
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("__Host-ta_session=") and "Secure" in cookie and "HttpOnly" in cookie
    assert "Domain" not in cookie and "Path=/" in cookie
    assert c.get(f"{V1}/auth/me").json()["username"] == "alice"


def test_wrong_password_and_unknown_user_look_the_same(make_client, db):
    c = make_client()
    AuthService(db).create_user("alice", TEST_PASSWORD)
    wrong = c.post(f"{V1}/auth/login", json={"username": "alice", "password": "not-the-password"})
    unknown = c.post(f"{V1}/auth/login", json={"username": "nobody", "password": "not-the-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() and wrong.json()["code"] == "LOGIN_FAILED"
    assert "set-cookie" not in wrong.headers


def test_lockout_after_repeated_failures_and_admin_unlock(make_client, db):
    c = make_client(login_per_minute=100)
    user = AuthService(db).create_user("alice", TEST_PASSWORD)
    for _ in range(MAX_FAILURES):
        c.post(f"{V1}/auth/login", json={"username": "alice", "password": "not-the-password"})
    locked = c.post(f"{V1}/auth/login", json={"username": "alice", "password": TEST_PASSWORD})
    assert locked.status_code == 401 and "try again" in locked.json()["message"]
    admin = make_client()
    sign_in(admin, db, "boss", role="admin")
    assert any(u["locked"] for u in admin.get(f"{V1}/users").json() if u["username"] == "alice")
    assert admin.patch(f"{V1}/users/{user['id']}", json={"unlock": True}).json()["locked"] is False
    assert c.post(f"{V1}/auth/login", json={"username": "alice", "password": TEST_PASSWORD}).status_code == 200


def test_rate_limit_per_address(make_client, db):
    c = make_client(login_per_minute=3)
    for _ in range(3):
        c.post(f"{V1}/auth/login", json={"username": "x", "password": "y-y-y-y-y-y"})
    resp = c.post(f"{V1}/auth/login", json={"username": "x", "password": "y-y-y-y-y-y"})
    assert resp.status_code == 429 and resp.json()["code"] == "RATE_LIMITED"


def test_logout_revokes_the_session(make_client, db):
    c = make_client()
    sign_in(c, db, "alice")
    raw = c.cookies.get("ta_session")
    assert c.post(f"{V1}/auth/logout").status_code == 204
    c.cookies.set("ta_session", raw)  # replaying the old cookie does not work
    assert c.get(f"{V1}/suts").status_code == 401


def test_writes_need_the_csrf_header(make_client, db):
    c = make_client()
    me = sign_in(c, db, "alice")
    del c.headers["X-CSRF-Token"]
    body = {"code": "shop", "name": "Shop"}
    missing = c.post(f"{V1}/suts", json=body)
    assert missing.status_code == 403 and missing.json()["code"] == "CSRF_FAILED"
    assert c.post(f"{V1}/suts", json=body, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert c.get(f"{V1}/suts").status_code == 200  # reads do not need it
    assert c.post(f"{V1}/suts", json=body, headers={"X-CSRF-Token": me["csrf_token"]}).status_code == 201


def test_change_password_keeps_this_session_and_ends_others(make_client, db):
    a, b = make_client(), make_client()
    sign_in(a, db, "alice")
    sign_in(b, db, "alice")
    bad = a.post(f"{V1}/auth/password", json={"current_password": "wrong-one-123", "new_password": NEW_PASSWORD})
    assert bad.status_code == 422
    weak = a.post(f"{V1}/auth/password", json={"current_password": TEST_PASSWORD, "new_password": "short"})
    assert weak.status_code == 422
    ok = a.post(f"{V1}/auth/password", json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD})
    assert ok.status_code == 200
    assert a.get(f"{V1}/suts").status_code == 200
    assert b.get(f"{V1}/suts").status_code == 401
    c = make_client()
    assert c.post(f"{V1}/auth/login", json={"username": "alice", "password": NEW_PASSWORD}).status_code == 200


def test_admin_created_user_must_change_initial_password(make_client, db):
    admin = make_client()
    sign_in(admin, db, "boss", role="admin")
    created = admin.post(f"{V1}/users", json={"username": "Carol", "password": "initial-pass-1", "role": "member"})
    assert created.status_code == 201 and created.json()["must_change_password"] is True
    assert admin.post(f"{V1}/users", json={"username": "carol", "password": "initial-pass-1"}).status_code == 409
    c = make_client()
    me = c.post(f"{V1}/auth/login", json={"username": "carol", "password": "initial-pass-1"}).json()
    assert me["must_change_password"] is True
    c.headers["X-CSRF-Token"] = me["csrf_token"]
    blocked = c.get(f"{V1}/suts")
    assert blocked.status_code == 403 and blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    c.post(f"{V1}/auth/password", json={"current_password": "initial-pass-1", "new_password": NEW_PASSWORD})
    assert c.get(f"{V1}/suts").status_code == 200


def test_admin_only_endpoints(make_client, db):
    member = make_client()
    sign_in(member, db, "alice", role="member")
    admin = make_client()
    sign_in(admin, db, "boss", role="admin")
    sut = member.post(f"{V1}/suts", json={"code": "shop", "name": "Shop"}).json()
    env = {"name": "local", "base_url": "http://127.0.0.1:9"}
    assert member.get(f"{V1}/users").status_code == 403
    assert member.post(f"{V1}/users", json={"username": "x1", "password": "initial-pass-1"}).status_code == 403
    assert member.put(f"{V1}/agent/config", json={"model": "m"}).json()["code"] == "FORBIDDEN"
    assert member.post(f"{V1}/agent/config/test").status_code == 403
    assert member.get(f"{V1}/agent/config").status_code == 200  # reading (no key shown) is fine
    with_cmd = {**env, "start_command": "echo hi"}
    assert member.post(f"{V1}/suts/{sut['id']}/environments", json=with_cmd).status_code == 403
    plain = member.post(f"{V1}/suts/{sut['id']}/environments", json=env)
    assert plain.status_code == 201
    env_id = plain.json()["id"]
    assert member.patch(f"{V1}/environments/{env_id}", json={"start_command": "rm -rf /"}).status_code == 403
    assert member.patch(f"{V1}/environments/{env_id}", json={"name": "renamed"}).status_code == 200
    assert admin.patch(f"{V1}/environments/{env_id}", json={"start_command": "echo ok"}).status_code == 200
    # the edit form sends every field: an unchanged start command is fine for members
    same = member.patch(f"{V1}/environments/{env_id}", json={"name": "again", "start_command": "echo ok"})
    assert same.status_code == 200
    assert admin.put(f"{V1}/agent/config", json={"model": "m"}).status_code == 200


def test_disable_user_ends_sessions_and_last_admin_is_protected(make_client, db):
    admin = make_client()
    boss = sign_in(admin, db, "boss", role="admin")
    member = make_client()
    sign_in(member, db, "alice")
    alice = AuthService(db).find("alice")
    assert admin.patch(f"{V1}/users/{alice['id']}", json={"is_active": False}).status_code == 200
    assert member.get(f"{V1}/suts").status_code == 401
    again = make_client()
    assert again.post(f"{V1}/auth/login", json={"username": "alice", "password": TEST_PASSWORD}).status_code == 401
    assert admin.patch(f"{V1}/users/{boss['id']}", json={"is_active": False}).status_code == 409  # yourself
    other = AuthService(db).create_user("admin2", TEST_PASSWORD, role="admin")
    AuthService(db).update_user(other["id"], {"role": "member"})  # boss is still an admin
    with pytest.raises(AppError) as err:
        AuthService(db).update_user(boss["id"], {"role": "member"})  # would leave no active admin
    assert err.value.code == "CONFLICT"


def test_reset_password_by_admin_ends_sessions(make_client, db):
    admin = make_client()
    sign_in(admin, db, "boss", role="admin")
    member = make_client()
    sign_in(member, db, "alice")
    alice = AuthService(db).find("alice")
    reset = admin.patch(f"{V1}/users/{alice['id']}", json={"password": "reset-pass-123"})
    assert reset.status_code == 200 and reset.json()["must_change_password"] is True
    assert member.get(f"{V1}/suts").status_code == 401


def test_idle_and_absolute_expiry(make_client, db):
    c = make_client()
    sign_in(c, db, "alice")
    with db.tx() as cur:
        cur.execute("UPDATE app_session SET last_seen_at = now() - interval '13 hours'")
    assert c.get(f"{V1}/suts").status_code == 401
    sign_in(c, db, "alice")
    with db.tx() as cur:
        cur.execute("UPDATE app_session SET expires_at = now() - interval '1 second' WHERE revoked_at IS NULL")
    assert c.get(f"{V1}/suts").status_code == 401


def test_login_rotates_the_session(make_client, db):
    c = make_client()
    sign_in(c, db, "alice")
    first = c.cookies.get("ta_session")
    sign_in(c, db, "alice")
    assert c.cookies.get("ta_session") != first
    with db.tx() as cur:
        cur.execute("SELECT count(*) AS n FROM app_session WHERE revoked_at IS NULL")
        assert cur.fetchone()["n"] == 1


def test_actor_is_the_signed_in_user(make_client, db):
    alice = make_client()
    sign_in(alice, db, "alice")
    bob = make_client()
    sign_in(bob, db, "bob")
    sut = alice.post(f"{V1}/suts", json={"code": "shop", "name": "Shop"}).json()
    bob.patch(f"{V1}/suts/{sut['id']}", json={"name": "Shop 2"})
    assert [(r["action"], r["actor"]) for r in _change_log(db, "sut")] == [("create", "alice"), ("update", "bob")]
    # outside a request (worker, scheduler) the actor is "system"
    from testagent.services.registry import SutService

    assert SutService(db, alice.app.state.bus).actor == "system"


def test_launcher_ticket_is_single_use_and_local_only(make_client, db):
    c = make_client()
    user = c.app.state.auth.local_admin()
    assert user["username"] == "local" and user["role"] == "admin" and user["has_password"] is False
    ticket = c.app.state.tickets.issue(user["id"])
    me = c.post(f"{V1}/auth/ticket", json={"ticket": ticket})
    assert me.status_code == 200 and me.json()["username"] == "local"
    assert c.post(f"{V1}/auth/ticket", json={"ticket": ticket}).status_code == 401
    # a password-less account cannot sign in with a password
    assert c.post(f"{V1}/auth/login", json={"username": "local", "password": "anything-123"}).status_code == 401
    remote = make_client(base_url="https://203.0.113.10", allowed_hosts=["203.0.113.10"])
    other = remote.app.state.tickets.issue(user["id"])
    assert remote.post(f"{V1}/auth/ticket", json={"ticket": other}).status_code == 403


def test_bootstrap_admin_only_while_empty(db, caplog):
    from testagent.core.config import Settings
    from testagent.launch import bootstrap_accounts

    auth = AuthService(db)
    settings = Settings(_env_file=None, admin_user="Boss", admin_password="first-admin-pass")
    with caplog.at_level("INFO"):
        bootstrap_accounts(auth, settings)
    assert auth.find("boss")["role"] == "admin"
    assert "first-admin-pass" not in caplog.text
    changed = Settings(_env_file=None, admin_user="other", admin_password="another-admin-pass")
    with caplog.at_level("INFO"):
        bootstrap_accounts(auth, changed)
    assert auth.find("other") is None and "ignored" in caplog.text
    legacy = Settings(_env_file=None, access_token="legacy-token-1")
    with caplog.at_level("WARNING"):
        bootstrap_accounts(auth, legacy)
    assert "no longer used" in caplog.text and "legacy-token-1" not in caplog.text


def test_user_cli(db, monkeypatch):
    from testagent.cli_users import run

    out: list[str] = []
    monkeypatch.setattr("sys.stdin", io.StringIO("cli-password-1\n"))
    assert run(db, ["add", "Root", "--admin", "--password-stdin"], out.append) == 0
    assert run(db, ["list"], out.append) == 0
    assert out[-1].startswith("root\tadmin")
    monkeypatch.setattr("sys.stdin", io.StringIO("cli-password-2\n"))
    assert run(db, ["passwd", "root", "--password-stdin"], out.append) == 0
    assert AuthService(db).authenticate("root", "cli-password-2")["username"] == "root"
    assert run(db, ["unlock", "root"], out.append) == 0
    assert run(db, ["disable", "nobody"], out.append) == 1
    assert run(db, ["disable", "root"], out.append) == 1  # last admin
    assert all("cli-password" not in line for line in out)


def test_unauthenticated_event_stream_is_refused(make_client):
    c = make_client()
    resp = c.get(f"{V1}/runs/00000000-0000-0000-0000-000000000000/events")
    assert resp.status_code == 401
