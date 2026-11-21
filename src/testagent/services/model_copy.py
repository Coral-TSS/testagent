"""Give a new version its own model: adopt a provisional model, or copy a source version."""

from __future__ import annotations

from testagent.core.errors import AppError


def bind_new_version(cur, sut_id, version_id, source_version_id=None) -> dict:
    """First version adopts nodes that were saved before any version existed.

    Later versions copy the source (default: the previous version). The copy is independent.
    """
    cur.execute(
        "SELECT id FROM version WHERE sut_id=%s AND id<>%s ORDER BY created_at DESC LIMIT 1",
        (sut_id, version_id),
    )
    previous = cur.fetchone()
    if previous is None:
        for table in ("model_node", "model_edge", "model_link", "model_suggestion"):
            cur.execute(
                f"UPDATE {table} SET version_id=%s WHERE sut_id=%s AND version_id IS NULL",
                (version_id, sut_id),
            )
        return {"adopted": True, "copied_from": None}
    source = source_version_id or previous["id"]
    cur.execute("SELECT id FROM version WHERE id=%s AND sut_id=%s", (source, sut_id))
    if cur.fetchone() is None:
        raise AppError("VALIDATION", "The source version does not belong to this SUT")
    if str(source) == str(version_id):
        raise AppError("VALIDATION", "A version cannot copy its model from itself")
    cur.execute("SELECT copy_version_model(%s, %s)", (source, version_id))
    return {"adopted": False, "copied_from": str(source)}
