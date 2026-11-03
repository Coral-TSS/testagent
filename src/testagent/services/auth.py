"""Platform accounts, password sign-in, server-side sessions and launcher tickets (t98u)."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
from collections import deque

from testagent.core.errors import AppError
from testagent.core.passwords import check_rules, hash_password, needs_rehash, verify_password
from testagent.services.changelog import log_change

ROLES = ("admin", "member")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
MAX_FAILURES = 5
LOCK_MINUTES = 15
TOUCH_SECONDS = 300  # last_seen_at is written at most this often
LOGIN_FAILED = "Wrong user name or password"
PUBLIC_COLUMNS = (
    "id, username, display_name, role, is_active, must_change_password, last_login_at, created_at,"
    " (locked_until IS NOT NULL AND locked_until > now()) AS locked, (password_hash IS NOT NULL) AS has_password"
)


def token_hash(raw: str) -> bytes:
    return hashlib.sha256(raw.encode()).digest()


def normalize_username(name: str) -> str:
    value = (name or "").strip().lower()
    if not USERNAME_RE.match(value):
        raise AppError(
            "VALIDATION",
            "User name: 2–32 characters, lowercase letters, digits, '.', '_' or '-', starting with a letter or digit",
        )
    return value


def _public(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    out["id"] = str(out["id"])
    return out


class AuthService:
    def __init__(self, db, idle_hours: float = 12, max_days: float = 7, actor: str = "system"):
        self.db = db
        self.idle_hours = idle_hours
        self.max_days = max_days
        self.actor = actor

    # ---- users
    def count(self, active_admins: bool = False) -> int:
        cond = " WHERE role='admin' AND is_active" if active_admins else ""
        with self.db.tx() as cur:
            cur.execute(f"SELECT count(*) AS n FROM app_user{cond}")
            return cur.fetchone()["n"]

    def list_users(self) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(f"SELECT {PUBLIC_COLUMNS} FROM app_user ORDER BY created_at, username")
            return [_public(r) for r in cur.fetchall()]

    def get_user(self, user_id) -> dict:
        with self.db.tx() as cur:
            cur.execute(f"SELECT {PUBLIC_COLUMNS} FROM app_user WHERE id=%s", (user_id,))
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "User does not exist")
        return _public(row)

    def create_user(
        self,
        username: str,
        password: str | None,
        role: str = "member",
        display_name: str = "",
        must_change_password: bool = False,
    ) -> dict:
        name = normalize_username(username)
        if role not in ROLES:
            raise AppError("VALIDATION", "Role must be admin or member")
        hashed = None
        if password is not None:
            check_rules(password, name)
            hashed = hash_password(password)
        with self.db.tx() as cur:
            cur.execute("SELECT 1 FROM app_user WHERE username=%s", (name,))
            if cur.fetchone():
                raise AppError("CONFLICT", f"User name “{name}” is already taken")
            cur.execute(
                "INSERT INTO app_user (username, display_name, password_hash, role, must_change_password,"
                " password_changed_at) VALUES (%s,%s,%s,%s,%s, CASE WHEN %s THEN now() END) RETURNING id",
                (name, (display_name or "").strip()[:100], hashed, role, must_change_password, hashed is not None),
            )
            user_id = cur.fetchone()["id"]
            log_change(cur, "app_user", user_id, "create", self.actor, {"username": name, "role": role})
        return self.get_user(user_id)

    def update_user(self, user_id, patch: dict) -> dict:
        user = self.get_user(user_id)
        sets, args, revoke = [], [], False
        if "display_name" in patch and patch["display_name"] is not None:
            sets.append("display_name=%s")
            args.append(patch["display_name"].strip()[:100])
        demote = patch.get("role") is not None and patch["role"] != user["role"]
        disable = patch.get("is_active") is False and user["is_active"]
        if patch.get("role") is not None:
            if patch["role"] not in ROLES:
                raise AppError("VALIDATION", "Role must be admin or member")
            sets.append("role=%s")
            args.append(patch["role"])
        if patch.get("is_active") is not None:
            sets.append("is_active=%s")
            args.append(bool(patch["is_active"]))
            revoke = revoke or disable
        if patch.get("password"):
            check_rules(patch["password"], user["username"])
            sets += ["password_hash=%s", "must_change_password=true", "password_changed_at=now()"]
            sets += ["failed_logins=0", "locked_until=NULL"]
            args.append(hash_password(patch["password"]))
            revoke = True
        if patch.get("unlock"):
            sets += ["failed_logins=0", "locked_until=NULL"]
        if user["role"] == "admin" and user["is_active"] and (disable or (demote and patch["role"] != "admin")):
            if self.count(active_admins=True) <= 1:
                raise AppError("CONFLICT", "The last active admin cannot be disabled or demoted")
        if sets:
            with self.db.tx() as cur:
                cur.execute(f"UPDATE app_user SET {', '.join(sets)}, updated_at=now() WHERE id=%s", (*args, user_id))
                audit = {k: v for k, v in patch.items() if k != "password" and v is not None}
                if patch.get("password"):
                    audit["password"] = "reset"
                log_change(cur, "app_user", user_id, "update", self.actor, audit)
        if revoke:
            self.revoke_all(user_id)
        return self.get_user(user_id)

    def set_password(self, username: str, password: str, must_change: bool = False) -> dict:
        """CLI recovery: set a password, unlock, revoke sessions."""
        name = normalize_username(username)
        check_rules(password, name)
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE app_user SET password_hash=%s, must_change_password=%s, password_changed_at=now(),"
                " failed_logins=0, locked_until=NULL, updated_at=now() WHERE username=%s RETURNING id",
                (hash_password(password), must_change, name),
            )
            row = cur.fetchone()
            if row is None:
                raise AppError("NOT_FOUND", f"User “{name}” does not exist")
            log_change(cur, "app_user", row["id"], "update", self.actor, {"password": "set"})
        self.revoke_all(row["id"])
        return self.get_user(row["id"])

    def find(self, username: str) -> dict | None:
        with self.db.tx() as cur:
            cur.execute(f"SELECT {PUBLIC_COLUMNS} FROM app_user WHERE username=%s", ((username or "").lower(),))
            return _public(cur.fetchone())

    # ---- sign-in
    def authenticate(self, username: str, password: str) -> dict:
        """Returns the user or raises LOGIN_FAILED (same message for unknown names, wrong passwords, locks)."""
        name = (username or "").strip().lower()
        with self.db.tx() as cur:
            cur.execute(
                "SELECT id, username, password_hash, is_active,"
                " (locked_until IS NOT NULL AND locked_until > now()) AS locked FROM app_user WHERE username=%s",
                (name,),
            )
            row = cur.fetchone()
        if row is None or not row["is_active"] or row["locked"]:
            verify_password(None, password or "")  # same work as a real check
            if row is not None and row["locked"]:
                raise AppError("LOGIN_FAILED", f"{LOGIN_FAILED}, or too many attempts: try again in a few minutes")
            raise AppError("LOGIN_FAILED", LOGIN_FAILED)
        if not verify_password(row["password_hash"], password or ""):
            with self.db.tx() as cur:
                cur.execute(
                    "UPDATE app_user SET failed_logins = failed_logins + 1 WHERE id=%s RETURNING failed_logins",
                    (row["id"],),
                )
                if cur.fetchone()["failed_logins"] >= MAX_FAILURES:
                    cur.execute(
                        "UPDATE app_user SET failed_logins=0, locked_until=now() + %s * interval '1 minute'"
                        " WHERE id=%s",
                        (LOCK_MINUTES, row["id"]),
                    )
                    log_change(cur, "app_user", row["id"], "lock", "system", {"minutes": LOCK_MINUTES})
            raise AppError("LOGIN_FAILED", LOGIN_FAILED)
        with self.db.tx() as cur:
            extra = ""
            args: tuple = (row["id"],)
            if needs_rehash(row["password_hash"]):
                extra, args = ", password_hash=%s", (hash_password(password), row["id"])
            cur.execute(
                f"UPDATE app_user SET failed_logins=0, locked_until=NULL, last_login_at=now(){extra} WHERE id=%s",
                args,
            )
        return self.get_user(row["id"])

    def change_password(self, user_id, old: str, new: str, keep_session_id=None) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT username, password_hash FROM app_user WHERE id=%s", (user_id,))
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "User does not exist")
        if not verify_password(row["password_hash"], old or ""):
            raise AppError("VALIDATION", "The current password is wrong")
        check_rules(new, row["username"])
        if old == new:
            raise AppError("VALIDATION", "The new password must differ from the current one")
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE app_user SET password_hash=%s, must_change_password=false, password_changed_at=now(),"
                " updated_at=now() WHERE id=%s",
                (hash_password(new), user_id),
            )
            log_change(cur, "app_user", user_id, "update", row["username"], {"password": "changed"})
        self.revoke_all(user_id, except_session=keep_session_id)
        return self.get_user(user_id)

    # ---- sessions
    def create_session(self, user_id, ip: str | None = None, user_agent: str | None = None) -> tuple[str, str]:
        raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.db.tx() as cur:
            cur.execute(
                "INSERT INTO app_session (token_hash, csrf_token, user_id, expires_at, ip, user_agent)"
                " VALUES (%s,%s,%s, now() + %s * interval '1 day', %s, %s)",
                (token_hash(raw), csrf, user_id, self.max_days, ip, (user_agent or "")[:300] or None),
            )
        return raw, csrf

    def resolve(self, raw: str | None) -> dict | None:
        """Session + user for a cookie value, or None (unknown, revoked, idle, expired, user disabled)."""
        if not raw:
            return None
        with self.db.tx() as cur:
            cur.execute(
                "SELECT s.id AS session_id, s.csrf_token, s.user_id,"
                " extract(epoch FROM now() - s.last_seen_at) AS idle_s,"
                " u.username, u.display_name, u.role, u.must_change_password"
                " FROM app_session s JOIN app_user u ON u.id = s.user_id"
                " WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at > now() AND u.is_active"
                " AND s.last_seen_at > now() - %s * interval '1 hour'",
                (token_hash(raw), self.idle_hours),
            )
            row = cur.fetchone()
            if row is not None and row["idle_s"] > TOUCH_SECONDS:
                cur.execute("UPDATE app_session SET last_seen_at=now() WHERE id=%s", (row["session_id"],))
        return row

    def revoke(self, session_id) -> None:
        with self.db.tx() as cur:
            cur.execute("UPDATE app_session SET revoked_at=now() WHERE id=%s AND revoked_at IS NULL", (session_id,))

    def revoke_all(self, user_id, except_session=None) -> None:
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE app_session SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL"
                " AND (%s::uuid IS NULL OR id <> %s::uuid)",
                (user_id, except_session, except_session),
            )

    # ---- bootstrap
    def bootstrap_admin(self, username: str | None, password: str | None) -> dict | None:
        """First admin from the environment, only while there are no users at all."""
        if not username or not password or self.count() > 0:
            return None
        return self.create_user(username, password, role="admin", display_name=username)

    def local_admin(self) -> dict:
        """The admin the desktop launcher signs in: the oldest active admin, else a password-less 'local'."""
        with self.db.tx() as cur:
            cur.execute("SELECT id FROM app_user WHERE role='admin' AND is_active ORDER BY created_at LIMIT 1")
            row = cur.fetchone()
        if row:
            return self.get_user(row["id"])
        existing = self.find("local")
        if existing:
            return self.update_user(existing["id"], {"role": "admin", "is_active": True})
        return self.create_user("local", None, role="admin", display_name="Local user")


class LoginRateLimiter:
    """Sliding windows per client IP (single platform instance, so memory is enough)."""

    def __init__(self, per_minute: int = 10, per_hour: int = 100):
        self.limits = ((60.0, per_minute), (3600.0, per_hour))
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key or "?", deque())
            while hits and now - hits[0] > self.limits[-1][0]:
                hits.popleft()
            for window, limit in self.limits:
                if sum(1 for t in hits if now - t <= window) >= limit:
                    raise AppError("RATE_LIMITED", "Too many sign-in attempts from this address: wait a minute")
            hits.append(now)
            if len(self._hits) > 10_000:  # forget idle addresses
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 3600]:
                    self._hits.pop(k, None)


class LocalTickets:
    """One-time, short-lived sign-in tickets the desktop launcher puts in the URL fragment."""

    def __init__(self, ttl_s: float = 120):
        self.ttl_s = ttl_s
        self._tickets: dict[bytes, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, user_id) -> str:
        raw = secrets.token_urlsafe(32)
        with self._lock:
            self._tickets[token_hash(raw)] = (str(user_id), time.monotonic() + self.ttl_s)
        return raw

    def redeem(self, raw: str) -> str | None:
        with self._lock:
            entry = self._tickets.pop(token_hash(raw or ""), None)
        if entry is None or entry[1] < time.monotonic():
            return None
        return entry[0]
