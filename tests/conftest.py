"""Shared fixtures. DB tests use a throw-away schema inside the *_test database."""

from __future__ import annotations

import os
import secrets

import psycopg
import pytest

from testagent.core.config import Settings
from testagent.core.db import Database, assert_test_database
from testagent.core.migrations import migrate

# The procurement demo ships seeded bugs (on by default for people trying TestAgent);
# platform tests run it with the bugs off unless a test turns them on explicitly.
os.environ["PROCUREMENT_DEMO_BUGS"] = "0"

TEST_USER = "tester"  # the signed-in admin of the `client` fixture (actor of what it changes)
TEST_PASSWORD = "tester-password-1"  # test-only credential
KEEP_TABLES = {"schema_migrations", "severity_weight"}


@pytest.fixture(scope="session")
def test_dsn() -> str:
    secret = Settings().test_database_url
    if secret is None or not secret.get_secret_value():
        pytest.skip("TESTAGENT_TEST_DATABASE_URL is not set; skipping database tests")
    dsn = secret.get_secret_value()
    assert_test_database(dsn)
    return dsn


def new_schema_name() -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "w0")
    return f"t_{worker}_{secrets.token_hex(4)}"


def create_schema(dsn: str, name: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{name}"')


def drop_schema(dsn: str, name: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


@pytest.fixture(scope="session")
def session_db(test_dsn):
    name = new_schema_name()
    create_schema(test_dsn, name)
    db = Database(test_dsn, schema=name, max_size=5)
    try:
        migrate(db)
        with db.tx() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (name,))
            db.test_tables = [r["tablename"] for r in cur.fetchall() if r["tablename"] not in KEEP_TABLES]
        yield db
    finally:
        db.close()
        drop_schema(test_dsn, name)


@pytest.fixture
def db(session_db):
    tables = ", ".join(f'"{t}"' for t in session_db.test_tables)
    with session_db.tx() as cur:
        cur.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    return session_db


@pytest.fixture
def client(db, tmp_path):
    from fastapi.testclient import TestClient

    from testagent.api.app import create_app
    from testagent.core.secrets import SecretStore

    app = create_app(  # a non-UTC default zone exercises local-time scheduling
        db,
        secrets=SecretStore(tmp_path / "secrets.json"),
        runtime_dir=tmp_path / "rt",
        timezone="Asia/Shanghai",
    )
    with TestClient(app, base_url="http://127.0.0.1") as c:
        sign_in(c, db, TEST_USER, role="admin")
        yield c


def sign_in(c, db, username: str, role: str = "member", password: str = TEST_PASSWORD) -> dict:
    """Create the account if needed, sign the client in and send the CSRF header on writes."""
    from testagent.services.auth import AuthService

    auth = AuthService(db)
    if auth.find(username) is None:
        auth.create_user(username, password, role=role)
    resp = c.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    me = resp.json()
    c.headers["X-CSRF-Token"] = me["csrf_token"]
    return me


def pytest_configure(config):
    config.addinivalue_line("markers", "preflight: use the real environment reachability check")


@pytest.fixture(autouse=True)
def _environments_reachable(request, monkeypatch):
    """Fake executors use placeholder URLs: treat environments as reachable unless a test
    opts into the real check with @pytest.mark.preflight."""
    if request.node.get_closest_marker("preflight") is None:
        from testagent.services import environments

        monkeypatch.setattr(environments, "probe", lambda *a, **k: (True, "ok"))
