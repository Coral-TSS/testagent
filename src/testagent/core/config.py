"""Settings from environment / git-ignored .env (never logged)."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from testagent.core.errors import AppError

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TIMEZONE = "UTC"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TESTAGENT_", env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: SecretStr | None = None
    test_database_url: SecretStr | None = None
    runtime_dir: Path = REPO_ROOT / "runtime"
    host: str = "127.0.0.1"
    port: int = 8765
    access_token: SecretStr | None = None  # removed in 0.2 (accounts); only read to warn when still set
    dev_token: SecretStr | None = None  # older name of access_token, same
    admin_user: str | None = None  # first admin, created only while there are no accounts
    admin_password: SecretStr | None = None
    cookie_secure: str = "auto"  # auto = Secure cookie on https; "true" / "false" to force
    session_idle_hours: float = 12
    session_max_days: float = 7
    trusted_proxies: str = "127.0.0.1"  # whose X-Forwarded-* headers count (Docker behind Caddy: "*")
    allowed_hosts: str = ""  # extra Host names besides loopback, comma separated (LAN / Docker)
    demo_url: str | None = None  # where the procurement demo runs when it is not local (Docker)
    artifact_max_bytes: int = 50 * 1024 * 1024
    browser_headless: bool = True
    pytest_timeout_s: float = 300
    timezone: str = DEFAULT_TIMEZONE  # cron schedules are evaluated in this zone by default
    agent_language: str = "English"  # language of the text the agent writes for people

    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    def require_database_url(self) -> str:
        if self.database_url is None or not self.database_url.get_secret_value():
            raise AppError("CONFIG_MISSING", "TESTAGENT_DATABASE_URL is not set (set it in .env or the environment)")
        return self.database_url.get_secret_value()

    def require_test_database_url(self) -> str:
        if self.test_database_url is None or not self.test_database_url.get_secret_value():
            raise AppError(
                "CONFIG_MISSING", "TESTAGENT_TEST_DATABASE_URL is not set (set it in .env or the environment)"
            )
        return self.test_database_url.get_secret_value()
