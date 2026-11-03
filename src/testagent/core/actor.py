"""Who is acting: the signed-in user for API requests, "system" for background work.

The auth middleware sets the user name for the duration of a request; services that are built
without an explicit ``actor`` pick it up from here. Worker / scheduler threads never see a
request context, so they fall back to ``SYSTEM``."""

from __future__ import annotations

from contextvars import ContextVar

SYSTEM = "system"
_current: ContextVar[str] = ContextVar("testagent_actor", default=SYSTEM)


def current_actor() -> str:
    return _current.get()


def set_actor(name: str):
    """Returns a token for ``reset_actor``."""
    return _current.set(name)


def reset_actor(token) -> None:
    _current.reset(token)
