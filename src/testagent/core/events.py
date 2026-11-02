"""In-process event bus (EP-02). Subscriber failures are isolated and logged."""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable

log = logging.getLogger("testagent.events")
Handler = Callable[[str, dict], None]


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event: str, handler: Handler) -> Callable[[], None]:
        """`event` may be an exact name or '*' for all events. Returns an unsubscribe function."""
        with self._lock:
            self._subs[event].append(handler)

        def unsubscribe():
            with self._lock:
                if handler in self._subs[event]:
                    self._subs[event].remove(handler)

        return unsubscribe

    def publish(self, event: str, payload: dict | None = None) -> list[Exception]:
        payload = payload or {}
        with self._lock:
            handlers = list(self._subs.get(event, ())) + list(self._subs.get("*", ()))
        errors: list[Exception] = []
        for handler in handlers:
            try:
                handler(event, payload)
            except Exception as exc:  # isolate subscribers from publishers
                log.exception("event subscriber failed for %s", event)
                errors.append(exc)
        return errors
