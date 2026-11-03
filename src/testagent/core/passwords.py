"""Password hashing (argon2id) and the password rules."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from testagent.core.errors import AppError

MIN_LENGTH = 10
MAX_LENGTH = 128
_hasher = PasswordHasher()  # argon2id with the library defaults
# verified against unknown user names so the response time does not reveal which names exist
_DUMMY_HASH = _hasher.hash("testagent-dummy-password")


def check_rules(password: str, username: str = "") -> None:
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        raise AppError("VALIDATION", f"The password needs at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise AppError("VALIDATION", f"The password can have at most {MAX_LENGTH} characters")
    if username and password.strip().lower() == username.lower():
        raise AppError("VALIDATION", "The password must not be the user name")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    """Constant-ish time: a missing hash still runs one verification."""
    try:
        return _hasher.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored)
    except InvalidHashError:
        return False
