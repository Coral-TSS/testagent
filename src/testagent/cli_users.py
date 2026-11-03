"""``testagent user ...``: manage accounts from a shell (first admin, forgotten passwords).

    testagent user add <name> [--admin] [--display-name TEXT] [--password-stdin]
    testagent user passwd <name> [--password-stdin]
    testagent user list
    testagent user unlock <name>
    testagent user disable <name>
    testagent user enable <name>

Passwords are typed at a hidden prompt (or read from stdin), never passed as arguments."""

from __future__ import annotations

import argparse
import getpass
import sys


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise SystemExit("[TestAgent] The passwords do not match")
    return first


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="testagent user", description="Manage TestAgent accounts")
    sub = p.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="create an account")
    add.add_argument("name")
    add.add_argument("--admin", action="store_true", help="role admin (default member)")
    add.add_argument("--display-name", default="")
    add.add_argument("--password-stdin", action="store_true")
    pw = sub.add_parser("passwd", help="set a new password (also unlocks, signs out everywhere)")
    pw.add_argument("name")
    pw.add_argument("--password-stdin", action="store_true")
    sub.add_parser("list", help="list accounts")
    for cmd in ("unlock", "disable", "enable"):
        sub.add_parser(cmd).add_argument("name")
    return p


def run(db, argv: list[str], out=print) -> int:
    from testagent.core.errors import AppError
    from testagent.services.auth import AuthService

    args = _parser().parse_args(argv)
    auth = AuthService(db, actor="cli")
    try:
        if args.cmd == "add":
            user = auth.create_user(
                args.name,
                _read_password(args.password_stdin),
                role="admin" if args.admin else "member",
                display_name=args.display_name or args.name,
            )
            out(f"created {user['role']} {user['username']}")
        elif args.cmd == "passwd":
            user = auth.set_password(args.name, _read_password(args.password_stdin))
            out(f"password set for {user['username']} (signed out everywhere, unlocked)")
        elif args.cmd == "list":
            for u in auth.list_users():
                flags = [u["role"]] + (["disabled"] if not u["is_active"] else []) + (["locked"] if u["locked"] else [])
                out(f"{u['username']}\t{', '.join(flags)}\t{u['display_name']}")
        else:
            user = auth.find(args.name)
            if user is None:
                raise AppError("NOT_FOUND", f"User “{args.name}” does not exist")
            patch = {"unlock": {"unlock": True}, "disable": {"is_active": False}, "enable": {"is_active": True}}[
                args.cmd
            ]
            auth.update_user(user["id"], patch)
            out(f"{args.cmd}d {user['username']}" if args.cmd != "unlock" else f"unlocked {user['username']}")
    except AppError as err:
        out(f"[TestAgent] {err.message}")
        return 1
    return 0


def main(argv: list[str]) -> int:
    from testagent.core.config import Settings
    from testagent.core.db import Database
    from testagent.core.errors import AppError
    from testagent.core.migrations import migrate

    try:
        db = Database(Settings().require_database_url())
        migrate(db)
    except AppError as err:
        print(f"[TestAgent] {err.message}", file=sys.stderr)
        return 2
    try:
        return run(db, argv)
    finally:
        db.close()
