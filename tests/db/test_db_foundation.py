import shutil
import threading
import time

import psycopg
import pytest

from conftest import create_schema, drop_schema, new_schema_name
from testagent.core.db import Database, InstanceLock
from testagent.core.errors import AppError
from testagent.core.migrations import discover, migrate


@pytest.fixture
def fresh_schema(test_dsn):
    name = new_schema_name()
    create_schema(test_dsn, name)
    yield name
    drop_schema(test_dsn, name)


def test_migrate_idempotent(test_dsn, fresh_schema):
    db = Database(test_dsn, schema=fresh_schema)
    try:
        first = migrate(db)
        assert first == [name for _, name, _, _ in discover()]
        assert migrate(db) == []
        with db.tx() as cur:
            cur.execute("SELECT count(*) AS n FROM schema_migrations")
            assert cur.fetchone()["n"] == len(first)
    finally:
        db.close()


def test_changed_applied_migration_refused(test_dsn, fresh_schema, tmp_path):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id int);", encoding="utf-8")
    db = Database(test_dsn, schema=fresh_schema)
    try:
        assert migrate(db, tmp_path) == ["0001_a.sql"]
        (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id bigint);", encoding="utf-8")
        with pytest.raises(AppError) as exc:
            migrate(db, tmp_path)
        assert exc.value.code == "MIGRATION_MISMATCH"
    finally:
        db.close()


def test_failed_migration_rolls_back(test_dsn, fresh_schema, tmp_path):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id int); SELECT broken(;", encoding="utf-8")
    db = Database(test_dsn, schema=fresh_schema)
    try:
        with pytest.raises(psycopg.Error):
            migrate(db, tmp_path)
        with db.tx() as cur:
            cur.execute("SELECT to_regclass('a') AS t")
            assert cur.fetchone()["t"] is None
            cur.execute("SELECT count(*) AS n FROM schema_migrations")
            assert cur.fetchone()["n"] == 0
    finally:
        db.close()


def test_concurrent_migrate_serialized(test_dsn, fresh_schema, tmp_path):
    (tmp_path / "0001_slow.sql").write_text("SELECT pg_sleep(0.5); CREATE TABLE slow (id int);", encoding="utf-8")
    results, errors = [], []

    def run():
        db = Database(test_dsn, schema=fresh_schema)
        try:
            results.append(migrate(db, tmp_path))
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(results, key=len) == [[], ["0001_slow.sql"]]


def test_isolation_between_tests_a(db):
    with db.tx() as cur:
        cur.execute("INSERT INTO person(name) VALUES ('isolation-probe')")


def test_isolation_between_tests_b(db):
    with db.tx() as cur:
        cur.execute("SELECT count(*) AS n FROM person")
        assert cur.fetchone()["n"] == 0


def test_session_uses_private_schema(db):
    assert db.schema.startswith("t_")
    with db.tx() as cur:
        cur.execute("SELECT current_schema() AS s")
        assert cur.fetchone()["s"] == db.schema


def test_severity_weight_seeded(db):
    with db.tx() as cur:
        cur.execute("SELECT severity, weight FROM severity_weight ORDER BY weight DESC")
        rows = {r["severity"]: float(r["weight"]) for r in cur.fetchall()}
    assert rows == {"critical": 10.0, "major": 3.0, "minor": 1.0, "trivial": 0.1}


def _weights(db):
    with db.tx() as cur:
        cur.execute("SELECT severity, weight FROM severity_weight")
        return {r["severity"]: float(r["weight"]) for r in cur.fetchall()}


@pytest.mark.parametrize("customised", [False, True])
def test_weight_migration_keeps_custom_values(test_dsn, fresh_schema, tmp_path, customised):
    """0013 swaps the old untouched defaults (5/3/1/0.5) for 10/3/1/0.1 but keeps user edits."""
    from testagent.core.migrations import MIGRATIONS_DIR

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for f in files:
        if f.name < "0013":
            shutil.copy(f, tmp_path / f.name)
    db = Database(test_dsn, schema=fresh_schema)
    try:
        migrate(db, tmp_path)
        assert _weights(db) == {"critical": 5.0, "major": 3.0, "minor": 1.0, "trivial": 0.5}
        if customised:
            with db.tx() as cur:
                cur.execute("UPDATE severity_weight SET weight = 8 WHERE severity = 'critical'")
        shutil.copy(MIGRATIONS_DIR / "0013_severity_weights_v2.sql", tmp_path)
        assert migrate(db, tmp_path) == ["0013_severity_weights_v2.sql"]
        expected = (
            {"critical": 8.0, "major": 3.0, "minor": 1.0, "trivial": 0.5}
            if customised
            else {"critical": 10.0, "major": 3.0, "minor": 1.0, "trivial": 0.1}
        )
        assert _weights(db) == expected
    finally:
        db.close()


def test_updated_at_trigger(db):
    with db.tx() as cur:
        cur.execute("INSERT INTO person(name) VALUES ('a') RETURNING id, updated_at")
        row = cur.fetchone()
    time.sleep(0.02)
    with db.tx() as cur:
        cur.execute("UPDATE person SET title='x' WHERE id=%s RETURNING updated_at", (row["id"],))
        assert cur.fetchone()["updated_at"] > row["updated_at"]


def test_snapshot_and_report_immutable(db):
    with db.tx() as cur:
        cur.execute("INSERT INTO sut(code, name) VALUES ('S1','s') RETURNING id")
        sut_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO model_snapshot(sut_id, content, digest) VALUES (%s,'{}','d') RETURNING id",
            (sut_id,),
        )
        snap = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO report(scope_type, scope_id, content, weights_used)"
            " VALUES ('version', gen_random_uuid(), '{}', '{}') RETURNING id"
        )
        report = cur.fetchone()["id"]
    for stmt, arg in [
        ("UPDATE model_snapshot SET digest='x' WHERE id=%s", snap),
        ("DELETE FROM model_snapshot WHERE id=%s", snap),
        ("UPDATE report SET ai_summary='x' WHERE id=%s", report),
        ("DELETE FROM report WHERE id=%s", report),
    ]:
        with pytest.raises(AppError) as exc:
            with db.tx() as cur:
                cur.execute(stmt, (arg,))
        assert exc.value.code == "CONFLICT"


def test_constraint_errors_are_mapped(db):
    with pytest.raises(AppError) as exc:
        with db.tx() as cur:
            cur.execute("INSERT INTO sut(code, name) VALUES ('1bad','x')")
    assert exc.value.code == "VALIDATION"
    with db.tx() as cur:
        cur.execute("INSERT INTO sut(code, name) VALUES ('OK','x')")
    with pytest.raises(AppError) as exc:
        with db.tx() as cur:
            cur.execute("INSERT INTO sut(code, name) VALUES ('OK','y')")
    assert exc.value.code == "CONFLICT"
    with pytest.raises(AppError) as exc:
        with db.tx() as cur:
            cur.execute("INSERT INTO environment(sut_id, name, base_url) VALUES (gen_random_uuid(), 'e', 'http://x')")
    assert exc.value.code == "NOT_FOUND"


def test_requirement_person_roles_constrained(db):
    with db.tx() as cur:
        cur.execute("INSERT INTO sut(code, name) VALUES ('S','s') RETURNING id")
        sut = cur.fetchone()["id"]
        cur.execute("INSERT INTO version(sut_id, name) VALUES (%s,'v1') RETURNING id", (sut,))
        ver = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO requirement(version_id, code, title) VALUES (%s,'R1','t') RETURNING id",
            (ver,),
        )
        req = cur.fetchone()["id"]
        cur.execute("INSERT INTO person(name) VALUES ('p') RETURNING id")
        person = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO requirement_person(requirement_id, person_id, role) VALUES (%s,%s,'owner')",
            (req, person),
        )
    with pytest.raises(AppError) as exc:
        with db.tx() as cur:
            cur.execute(
                "INSERT INTO requirement_person(requirement_id, person_id, role) VALUES (%s,%s,'boss')",
                (req, person),
            )
    assert exc.value.code == "VALIDATION"


def test_second_instance_cannot_take_worker_lock(session_db):
    first, second = InstanceLock(session_db), InstanceLock(session_db)
    assert first.acquire()
    try:
        assert not second.acquire()
    finally:
        first.release()
    assert second.acquire()
    second.release()


def test_db_unavailable_is_clear(test_dsn):
    from psycopg.conninfo import make_conninfo

    bad = make_conninfo(test_dsn, port="1", connect_timeout="2")
    with pytest.raises(AppError) as exc:
        Database(bad)
    assert exc.value.code == "DB_UNAVAILABLE"
    assert "@" not in exc.value.message and "postgres" not in exc.value.message.lower()
