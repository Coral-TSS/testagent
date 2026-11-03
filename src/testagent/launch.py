"""Launcher: check DB, migrate, take the instance lock, serve the platform.

``testagent``            start the platform (desktop: opens the browser already signed in)
``testagent user ...``   manage accounts from the command line (first admin, forgotten passwords)
"""

from __future__ import annotations

import logging
import sys
import webbrowser

from testagent.core.redact import RedactingFilter, describe_dsn

log = logging.getLogger("testagent")


def display_host(host: str) -> str:
    """A wildcard bind address (Docker) is opened through localhost."""
    return "localhost" if host in ("0.0.0.0", "::", "") else host


def ticket_url(host: str, port: int, ticket: str) -> str:
    """One-time sign-in ticket in the URL fragment: never reaches server logs or Referer headers."""
    return f"http://{display_host(host)}:{port}/#ticket={ticket}"


def legacy_token_set(settings) -> bool:
    return any(v is not None and v.get_secret_value() for v in (settings.access_token, settings.dev_token))


def bootstrap_accounts(auth, settings) -> None:
    """First admin from TESTAGENT_ADMIN_USER / TESTAGENT_ADMIN_PASSWORD while there are no accounts."""
    password = settings.admin_password.get_secret_value() if settings.admin_password else None
    if legacy_token_set(settings):
        log.warning("TESTAGENT_ACCESS_TOKEN / TESTAGENT_DEV_TOKEN are no longer used: sign in with an account")
    try:
        created = auth.bootstrap_admin(settings.admin_user, password)
    except Exception as err:  # e.g. a password that breaks the rules: say so, keep starting
        log.error("could not create the first admin from TESTAGENT_ADMIN_USER: %s", getattr(err, "message", err))
        created = None
    if created:
        log.info("created the first admin account %r from TESTAGENT_ADMIN_USER", created["username"])
    elif password and auth.count() > 0:
        log.info("accounts exist, TESTAGENT_ADMIN_PASSWORD is ignored (you can remove it from .env)")
    if auth.count() == 0:
        log.warning(
            "no account yet: set TESTAGENT_ADMIN_USER and TESTAGENT_ADMIN_PASSWORD, "
            "or run: testagent user add <name> --admin"
        )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args[:1] == ["user"]:
        from testagent.cli_users import main as user_main

        return user_main(args[1:])
    import uvicorn

    from testagent.api.app import create_app
    from testagent.core.config import Settings
    from testagent.core.db import Database, InstanceLock
    from testagent.core.errors import AppError
    from testagent.core.migrations import migrate
    from testagent.core.secrets import SecretStore

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactingFilter())
    settings = Settings()
    try:
        dsn = settings.require_database_url()
        db = Database(dsn)
        log.info("database %s", describe_dsn(dsn))
        if db.server_version() < 170000:
            log.warning("PostgreSQL < 17 detected; 17 is the supported version")
        applied = migrate(db)
        if applied:
            log.info("applied migrations: %s", ", ".join(applied))
    except AppError as err:
        print(f"[TestAgent] {err.message}", file=sys.stderr)
        return 2
    lock = InstanceLock(db)
    if not lock.acquire():
        print(
            "[TestAgent] Another platform instance is already running (only one instance per database is allowed)",
            file=sys.stderr,
        )
        return 3
    from testagent.agent.checkpoint import open_checkpointer
    from testagent.core.jobs import mark_interrupted

    recovered = {k: v for k, v in mark_interrupted(db).items() if v}
    if recovered:
        log.info("marked interrupted after restart: %s", recovered)
    checkpointer, ckpt_conn = open_checkpointer(dsn)
    from testagent.services.auth import AuthService

    bootstrap_accounts(AuthService(db), settings)
    app = create_app(
        db,
        secrets=SecretStore(settings.runtime_dir / "secrets.json"),
        checkpointer=checkpointer,
        runtime_dir=settings.runtime_dir,
        browser_headless=settings.browser_headless,
        pytest_timeout_s=settings.pytest_timeout_s,
        background=True,
        instance_lock=lock,
        timezone=settings.timezone,
        allowed_hosts=settings.allowed_host_list(),
        cookie_secure=settings.cookie_secure,
        session_idle_hours=settings.session_idle_hours,
        session_max_days=settings.session_max_days,
    )
    if "--no-env-start" not in args:  # e.g. the procurement demo on 127.0.0.1:8766
        from testagent.services.environments import autostart

        for name in autostart(db, app.state.env_processes):
            print(f"[TestAgent] Started SUT environment: {name}")
    base = f"http://{display_host(settings.host)}:{settings.port}/"
    if "--no-browser" not in args:
        user = app.state.auth.local_admin()
        webbrowser.open(ticket_url(settings.host, settings.port, app.state.tickets.issue(user["id"])))
        print(f"[TestAgent] Platform URL: {base} (opened in the browser, signed in as {user['username']})")
    else:  # headless (Docker): people sign in with their accounts
        print(f"[TestAgent] Platform URL: {base} (sign in with your account)", flush=True)
    try:
        # uvicorn's own access log prints raw paths with UUIDs; testagent.access is readable
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_level="info",
            access_log=False,
            proxy_headers=True,  # behind Caddy: https scheme and the client address
            forwarded_allow_ips=settings.trusted_proxies,
        )
    finally:
        app.state.env_processes.stop_all()
        ckpt_conn.close()
        lock.release()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
