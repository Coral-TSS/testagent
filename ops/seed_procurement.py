"""Seed the procurement demo SUT into the database from .env (idempotent)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from testagent.core.config import Settings  # noqa: E402
from testagent.core.db import Database  # noqa: E402
from testagent.core.migrations import migrate  # noqa: E402
from testagent.seed import seed_procurement  # noqa: E402


def main() -> int:
    db = Database(Settings().require_database_url())
    try:
        migrate(db)
        settings = Settings()
        print(seed_procurement(db, demo_url=settings.demo_url))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
