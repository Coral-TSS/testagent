"""Launcher: check DB, migrate, take the instance lock, open the browser with a one-off token."""

from __future__ import annotations

import logging
import sys
import webbrowser

from testagent.core.auth import new_token
from testagent.core.redact import RedactingFilter, describe_dsn

log = logging.getLogger("testagent")


def build_url(host: str, port: int, token: str) -> str:
    """Token travels in the URL fragment so it never reaches server logs or Referer headers."""
    return f"http://{host}:{port}/#t={token}"


def display_host(host: str) -> str:
    """A wildcard bind address (Docker) is opened through localhost."""
    return "localhost" if host in ("0.0.0.0", "::", "") else host


def sign_in_url(host: str, port: int, token: str) -> str:
    return build_url(display_host(host), port, token)


def access_token(settings) -> tuple[str, bool]:
    """(token, fixed): TESTAGENT_ACCESS_TOKEN (or the older TESTAGENT_DEV_TOKEN), else random."""
    for value in (settings.access_token, settings.dev_token):
        if value is not None and value.get_secret_value():
            return value.get_secret_value(), True
    return new_token(), False


def main(argv: list[str] | None = None) -> int:
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
    token, fixed = access_token(settings)
    url = sign_in_url(settings.host, settings.port, token)
    app = create_app(
        db,
        token,
        secrets=SecretStore(settings.runtime_dir / "secrets.json"),
        checkpointer=checkpointer,
        runtime_dir=settings.runtime_dir,
        browser_headless=settings.browser_headless,
        pytest_timeout_s=settings.pytest_timeout_s,
        background=True,
        instance_lock=lock,
        timezone=settings.timezone,
        allowed_hosts=settings.allowed_host_list(),
    )
    args = argv if argv is not None else sys.argv[1:]
    if "--no-env-start" not in args:  # e.g. the procurement demo on 127.0.0.1:8766
        from testagent.services.environments import autostart

        for name in autostart(db, app.state.env_processes):
            print(f"[TestAgent] Started SUT environment: {name}")
    base = f"http://{display_host(settings.host)}:{settings.port}/"
    if "--no-browser" not in args:
        webbrowser.open(url)
        print(f"[TestAgent] Platform URL: {base} (opened in the browser with the token)")
    elif fixed:
        print(f"[TestAgent] Platform URL: {base} (sign in with TESTAGENT_ACCESS_TOKEN: {base}#t=<token>)")
    else:  # headless (Docker): the one-off sign-in link is the only way in, so print it once
        print(f"[TestAgent] Platform URL: {base}")
        print(f"[TestAgent] Sign in: {url}", flush=True)
    try:
        # uvicorn's own access log prints raw paths with UUIDs; testagent.access is readable
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", access_log=False)
    finally:
        app.state.env_processes.stop_all()
        ckpt_conn.close()
        lock.release()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
