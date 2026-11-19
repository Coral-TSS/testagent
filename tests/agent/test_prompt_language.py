"""The agent writes user-facing text in a configurable language (Simplified Chinese by default)."""

from testagent.agent.prompts import assemble
from testagent.agent.runtime import Entry
from testagent.core.config import Settings

ENTRY = Entry(name="demo", output_schema=None, tools=(), instructions="Do it.")


def test_default_output_language_is_simplified_chinese(db, monkeypatch):
    monkeypatch.delenv("TESTAGENT_AGENT_LANGUAGE", raising=False)
    assert Settings(_env_file=None).agent_language == "Simplified Chinese"
    prompt, _ = assemble(db, ENTRY)
    assert "Write all user-facing text in Simplified Chinese." in prompt


def test_output_language_is_configurable(db, monkeypatch):
    monkeypatch.setenv("TESTAGENT_AGENT_LANGUAGE", "Simplified Chinese")
    prompt, _ = assemble(db, ENTRY)
    assert "Write all user-facing text in Simplified Chinese." in prompt
