"""Guards against committing the database password or real connection strings."""

import re
import subprocess
from pathlib import Path

from testagent.core.config import REPO_ROOT, Settings

DSN_WITH_PASSWORD = re.compile(r"postgres(?:ql)?://[^:/@\s]+:([^@\s]+)@")
PLACEHOLDERS = {"***", "<password>", "password", "PASSWORD", "${PASSWORD}", "${POSTGRES_PASSWORD}", "change-me", "xxx"}


def _repo_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / line for line in out.splitlines() if line]


def _passwords() -> set[str]:
    settings = Settings()
    found = set()
    for secret in (settings.database_url, settings.test_database_url):
        if secret is not None:
            match = DSN_WITH_PASSWORD.search(secret.get_secret_value())
            if match:
                found.add(match.group(1))
    return found


def test_no_credentials_in_repo():
    files = _repo_files()
    assert ".env" not in {f.name for f in files}, ".env must be git-ignored"
    passwords = _passwords()
    offenders = []
    for path in files:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in DSN_WITH_PASSWORD.finditer(text):
            if match.group(1) not in PLACEHOLDERS and "test_no_credentials" not in path.name:
                offenders.append(f"{path.name}: connection string with password")
        if any(p and p in text for p in passwords):
            offenders.append(f"{path.name}: contains the configured database password")
    assert not offenders, offenders
