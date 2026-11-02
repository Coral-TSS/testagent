"""EP-09: cause category → responsible role. Replaceable; environment/unknown attribute nobody."""

from __future__ import annotations

from collections.abc import Mapping

DEFAULT_CAUSE_ROLE: Mapping[str, str | None] = {
    "requirement": "owner",
    "design": "owner",
    "development": "developer",
    "test": "tester",
    "environment": None,
    "unknown": None,
}
PRODUCT_CAUSES = frozenset({"requirement", "design", "development"})


class AttributionRules:
    def __init__(self, cause_role: Mapping[str, str | None] | None = None):
        self.cause_role = dict(cause_role or DEFAULT_CAUSE_ROLE)

    def role_for(self, cause: str | None) -> str | None:
        return self.cause_role.get(cause or "unknown")
