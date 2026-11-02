"""System prompt assembly: active template + entry instructions + injected memories + context."""

from __future__ import annotations

import json

from testagent.core.config import Settings

DEFAULT_SYSTEM = (
    "You are TestAgent, an assistant for functional software testing. Use the provided tools to "
    "read facts; never invent IDs. When done, call submit_result exactly once with the final "
    "structured output. Keep answers objective."
)
MAX_MEMORIES = 20
MAX_MEMORY_CHARS = 8000  # roughly 2k tokens


def output_language() -> str:
    """TESTAGENT_AGENT_LANGUAGE (default English): the language of text written for people."""
    return (Settings().agent_language or "English").strip() or "English"


def assemble(db, entry, sut_id=None, context: dict | None = None) -> tuple[str, dict]:
    with db.tx() as cur:
        cur.execute(
            "SELECT id, name, version, content FROM prompt_template WHERE name=%s AND active",
            (entry.template,),
        )
        template = cur.fetchone()
        entry_template = None
        if entry.name != entry.template:  # per-entry guidance (prompt patches can target it)
            cur.execute(
                "SELECT id, name, version, content FROM prompt_template WHERE name=%s AND active",
                (entry.name,),
            )
            entry_template = cur.fetchone()
        cur.execute(
            "SELECT id, content FROM agent_memory WHERE enabled"
            " AND (scope='global' OR (scope='sut' AND sut_id=%s))"
            " AND (tags = '[]'::jsonb OR tags ? %s)"
            " ORDER BY scope DESC, created_at DESC",
            (sut_id, entry.name),
        )
        memories = cur.fetchall()
        sut = None
        if sut_id is not None:
            cur.execute("SELECT code, name FROM sut WHERE id=%s", (sut_id,))
            sut = cur.fetchone()
    chosen, used = [], 0
    for memory in memories:
        if len(chosen) >= MAX_MEMORIES or used + len(memory["content"]) > MAX_MEMORY_CHARS:
            break
        chosen.append(memory)
        used += len(memory["content"])
    parts = [template["content"] if template else DEFAULT_SYSTEM]
    if entry.instructions:
        parts.append("## Task\n" + entry.instructions)
    parts.append(f"## Language\nWrite all user-facing text in {output_language()}.")
    if sut:
        parts.append(
            f"## Scope\nCurrent system under test: {sut['name']} (code {sut['code']}). "
            "Tools work inside this system: omit sut_id / version_id to use the current ones. "
            "Wherever an ID is asked for you may also pass a code (REQ-001, TC-001) or an exact "
            "node name."
        )
    if entry_template and entry_template["content"].strip():
        parts.append("## Additional guidance\n" + entry_template["content"].strip())
    if chosen:
        parts.append("## Lessons from past corrections\n" + "\n".join(f"- {m['content']}" for m in chosen))
    if context:
        parts.append("## Context\n" + json.dumps(context, ensure_ascii=False, default=str))

    def ref(t):
        return {"id": str(t["id"]), "name": t["name"], "version": t["version"]} if t else None

    injected = {
        "template": ref(template),
        "entry_template": ref(entry_template),
        "memory_ids": [str(m["id"]) for m in chosen],
    }
    return "\n\n".join(parts), injected
