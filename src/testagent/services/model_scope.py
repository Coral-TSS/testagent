"""Which version a model read or write belongs to.

``AUTO`` means the current open version (latest non-closed, else the latest), or no version
yet (``NULL`` — the provisional model created before the first version exists).
"""

from __future__ import annotations

from testagent.core.errors import AppError

AUTO = object()


def current_version_id(cur, sut_id):
    cur.execute(
        "SELECT id FROM version WHERE sut_id=%s ORDER BY (status='closed'), created_at DESC LIMIT 1",
        (sut_id,),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def resolve_version(cur, sut_id, version_id=AUTO):
    """Return the version id to read or write. ``None`` is the provisional (pre-version) model."""
    if version_id is AUTO:
        return current_version_id(cur, sut_id)
    if version_id is None:
        return None
    cur.execute("SELECT id, sut_id FROM version WHERE id=%s", (version_id,))
    row = cur.fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Version not found")
    if sut_id is not None and str(row["sut_id"]) != str(sut_id):
        raise AppError("VALIDATION", "The version does not belong to this SUT")
    return row["id"]


def same_version(left, right) -> bool:
    return (None if left is None else str(left)) == (None if right is None else str(right))
