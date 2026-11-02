"""PostgreSQL access: pooled connections, transactions, error mapping, instance lock."""

from __future__ import annotations

import hashlib
import re
from contextlib import contextmanager

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from testagent.core.errors import AppError

_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _map_error(exc: psycopg.Error) -> AppError:
    if isinstance(exc, pg_errors.UniqueViolation):
        return AppError("CONFLICT", "Record already exists (unique constraint violation)")
    if isinstance(exc, pg_errors.ForeignKeyViolation):
        # server messages may be localized; deletes re-map this to CONFLICT (see Crud.delete)
        return AppError("NOT_FOUND", "Referenced record does not exist")
    if isinstance(exc, (pg_errors.CheckViolation, pg_errors.NotNullViolation)):
        return AppError("VALIDATION", "Field value violates a constraint")
    if isinstance(exc, pg_errors.RestrictViolation):
        return AppError("CONFLICT", "This record cannot be modified")
    if isinstance(exc, pg_errors.InvalidTextRepresentation):
        return AppError("VALIDATION", "Invalid field format")
    if isinstance(exc, psycopg.OperationalError):
        return AppError("DB_UNAVAILABLE", "Database unavailable: check the connection settings in .env")
    return AppError("CONFLICT", "Database operation failed")


class Database:
    """Thin wrapper over a psycopg pool; `schema` pins search_path (used for test isolation)."""

    def __init__(self, dsn: str, schema: str | None = None, min_size: int = 1, max_size: int = 10):
        if schema is not None and not _SCHEMA_RE.match(schema):
            raise ValueError("invalid schema name")
        self._dsn = dsn
        self.schema = schema
        kwargs = {"row_factory": dict_row}
        if schema:
            kwargs["options"] = f"-c search_path={schema}"
        self._kwargs = kwargs
        try:
            psycopg.connect(dsn, connect_timeout=10, **kwargs).close()  # fail fast
            self.pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, kwargs=kwargs, open=True, timeout=10)
            self.pool.wait(timeout=10)
        except Exception as exc:  # never echo the DSN
            raise AppError(
                "DB_UNAVAILABLE", "Cannot connect to the database: check the connection settings in .env"
            ) from exc

    @property
    def dsn(self) -> str:
        return self._dsn

    def connect(self, autocommit: bool = False) -> psycopg.Connection:
        """Dedicated (non-pooled) connection, e.g. for advisory locks or LISTEN."""
        try:
            return psycopg.connect(self._dsn, autocommit=autocommit, **self._kwargs)
        except psycopg.OperationalError as exc:
            raise AppError(
                "DB_UNAVAILABLE", "Cannot connect to the database: check the connection settings in .env"
            ) from exc

    @contextmanager
    def tx(self):
        """One transaction; yields a dict-row cursor. Commits on success, rolls back on error."""
        try:
            with self.pool.connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        yield cur
        except psycopg.Error as exc:
            raise _map_error(exc) from exc

    def ping(self) -> bool:
        try:
            with self.tx() as cur:
                cur.execute("SELECT 1 AS ok")
                return cur.fetchone()["ok"] == 1
        except AppError:
            return False

    def server_version(self) -> int:
        with self.tx() as cur:
            cur.execute("SHOW server_version_num")
            return int(cur.fetchone()["server_version_num"])

    def close(self):
        self.pool.close()


def lock_key(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)


class InstanceLock:
    """Session advisory lock held on a dedicated connection: one Worker/scheduler per database."""

    def __init__(self, db: Database, name: str = "testagent-instance"):
        self._db = db
        self._key = lock_key(f"{name}:{db.schema or 'public'}")
        self._conn: psycopg.Connection | None = None

    def acquire(self) -> bool:
        conn = self._db.connect(autocommit=True)
        row = conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (self._key,)).fetchone()
        if row["ok"]:
            self._conn = conn
            return True
        conn.close()
        return False

    def release(self):
        if self._conn is not None:
            try:
                self._conn.execute("SELECT pg_advisory_unlock(%s)", (self._key,))
            finally:
                self._conn.close()
                self._conn = None

    @property
    def held(self) -> bool:
        return self._conn is not None


def assert_test_database(dsn: str) -> str:
    """Tests may only touch a database whose name ends in `_test`."""
    from psycopg.conninfo import conninfo_to_dict

    name = conninfo_to_dict(dsn).get("dbname") or ""
    if not name.endswith("_test"):
        raise AppError("CONFIG_MISSING", "Tests may only connect to a database whose name ends with _test")
    return name
