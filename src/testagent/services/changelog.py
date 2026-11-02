"""Audit trail written in the same transaction as the change."""

from __future__ import annotations

import json

from psycopg.types.json import Jsonb


def _dumps(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)


def log_change(cur, entity: str, entity_id, action: str, actor: str, diff: dict | None = None):
    cur.execute(
        "INSERT INTO change_log(entity, entity_id, action, actor, diff) VALUES (%s,%s,%s,%s,%s)",
        (entity, str(entity_id), action, actor, Jsonb(diff, dumps=_dumps) if diff else None),
    )
