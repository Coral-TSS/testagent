"""LangGraph PostgresSaver in its own schema (agent_ckpt; the test schema during tests)."""

from __future__ import annotations

import re

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql
from psycopg.rows import dict_row

CKPT_SCHEMA = "agent_ckpt"
_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def open_checkpointer(dsn: str, schema: str = CKPT_SCHEMA) -> tuple[PostgresSaver, psycopg.Connection]:
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid schema name")
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
    conn = psycopg.connect(
        dsn,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options=f"-c search_path={schema}",
    )
    saver = PostgresSaver(conn)
    saver.setup()
    return saver, conn
