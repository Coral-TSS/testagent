"""A sealed version keeps its model and requirements as a read-only baseline.

Creating another version from it is still allowed: the copy is a new, unsealed version.
"""

from __future__ import annotations

from testagent.core.errors import AppError

SEALED_MODEL = "该版本已封板，模型不可修改。可以基于它新建版本。"
SEALED_REQUIREMENTS = "该版本已封板，需求不可修改。可以基于它新建版本。"


def ensure_unsealed(cur, version_id, message: str = SEALED_MODEL) -> None:
    if version_id is None:
        return
    cur.execute("SELECT sealed FROM version WHERE id=%s", (version_id,))
    row = cur.fetchone()
    if row and row["sealed"]:
        raise AppError("CONFLICT", message)


def ensure_node_unsealed(cur, node_id, message: str = SEALED_MODEL) -> None:
    cur.execute("SELECT version_id FROM model_node WHERE id=%s", (node_id,))
    row = cur.fetchone()
    if row is not None:
        ensure_unsealed(cur, row["version_id"], message)
