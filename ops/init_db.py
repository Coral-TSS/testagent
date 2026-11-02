"""Create the testagent / testagent_test databases if missing (URLs from .env, never printed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from testagent.core.config import Settings  # noqa: E402
from testagent.core.redact import describe_dsn  # noqa: E402


def ensure_database(dsn: str) -> str:
    target = conninfo_to_dict(dsn).get("dbname")
    if not target:
        raise SystemExit("The connection string has no database name")
    admin = make_conninfo(dsn, dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        version = int(conn.execute("SHOW server_version_num").fetchone()[0])
        if version < 170000:
            print(f"Warning: PostgreSQL version {version} is lower than 17")
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (target,)).fetchone()
        if exists:
            return "exists"
        conn.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(target)))
        return "created"


def main() -> int:
    settings = Settings()
    urls = [
        ("TESTAGENT_DATABASE_URL", settings.database_url),
        ("TESTAGENT_TEST_DATABASE_URL", settings.test_database_url),
    ]
    for key, secret in urls:
        if secret is None:
            print(f"{key}: not configured, skipped")
            continue
        dsn = secret.get_secret_value()
        try:
            state = ensure_database(dsn)
        except psycopg.Error as exc:
            print(f"{key}: failed ({type(exc).__name__}) {describe_dsn(dsn)}")
            return 1
        print(f"{key}: {describe_dsn(dsn)} -> {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
