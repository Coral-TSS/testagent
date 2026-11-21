"""Clear and rebuild the supply-chain demo in TestAgent, and optionally the example app.

Dry run by default. ``--apply`` wipes that SUT's platform data (keeps the system row and its
environments), then rebuilds versions, the model and the fixed requirements. ``--demo-url``
also POSTs the example app's reset.

    uv run python ops/restore_supply_chain.py
    uv run python ops/restore_supply_chain.py --apply --keep-repo
    uv run python ops/restore_supply_chain.py --apply --demo-url http://127.0.0.1:8766 --keep-repo
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from testagent.core.config import Settings  # noqa: E402
from testagent.core.db import Database  # noqa: E402
from testagent.core.errors import AppError  # noqa: E402
from testagent.core.migrations import migrate  # noqa: E402
from testagent.seed import SUT_CODE, seed_supply_chain  # noqa: E402


def _reset():
    path = Path(__file__).resolve().parent / "reset_sut_data.py"
    spec = importlib.util.spec_from_file_location("reset_sut_data", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore the supply-chain demo")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--demo-url", default=None)
    parser.add_argument("--keep-repo", action="store_true")
    parser.add_argument("--repo-archive", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.apply and not args.keep_repo and args.repo_archive is None:
        parser.error("--apply needs --repo-archive or --keep-repo")
    reset = _reset()
    db = Database(Settings().require_database_url())
    try:
        migrate(db)
        try:
            plan = reset.reset_sut(db, SUT_CODE, apply=args.apply)
        except AppError as err:
            if err.code != "NOT_FOUND":
                raise
            plan = {"missing": True, "applied": False}
        seeded = None
        demo = None
        if args.apply:
            if args.repo_archive and plan.get("sut"):
                reset.reset_repo(
                    Settings().runtime_dir / "repos",
                    SUT_CODE,
                    plan["sut"]["id"],
                    args.repo_archive,
                    apply=True,
                )
            seeded = seed_supply_chain(db, demo_url=args.demo_url or Settings().demo_url)
            if args.demo_url:
                req = urllib.request.Request(args.demo_url.rstrip("/") + "/sample/reset", method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    demo = json.loads(resp.read().decode())
        print(json.dumps({"plan": plan, "seeded": seeded, "demo": demo}, ensure_ascii=False, default=str))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
