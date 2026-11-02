"""Versioned plain-SQL migrations with checksums, serialized by an advisory lock."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from testagent.core.db import Database, lock_key
from testagent.core.errors import AppError

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def discover(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, str, str, str]]:
    found = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if not match:
            continue
        sql = path.read_text(encoding="utf-8").replace("\r\n", "\n")  # checksum independent of EOL
        found.append((int(match.group(1)), path.name, sql, hashlib.sha256(sql.encode()).hexdigest()))
    versions = [v for v, *_ in found]
    if len(set(versions)) != len(versions):
        raise AppError("MIGRATION_MISMATCH", "Duplicate migration version")
    return found


def migrate(db: Database, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations. Returns names applied in this call."""
    applied_now: list[str] = []
    migrations = discover(directory)
    with db.connect(autocommit=True) as conn:
        key = lock_key(f"testagent-migrate:{db.schema or 'public'}")
        conn.execute("SELECT pg_advisory_lock(%s)", (key,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL,"
                " applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {r["version"]: r for r in conn.execute("SELECT * FROM schema_migrations").fetchall()}
            known = {v for v, *_ in migrations}
            if any(v not in known for v in done):
                raise AppError(
                    "MIGRATION_MISMATCH", "The database contains an unknown migration version; refusing to start"
                )
            for version, name, sql, checksum in migrations:
                if version in done:
                    if done[version]["checksum"] != checksum:
                        raise AppError(
                            "MIGRATION_MISMATCH", f"Applied migration {name} was modified; refusing to start"
                        )
                    continue
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, name, checksum) VALUES (%s,%s,%s)",
                        (version, name, checksum),
                    )
                applied_now.append(name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
    return applied_now
