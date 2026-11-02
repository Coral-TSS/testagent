"""The agent writes user-facing text in a configurable language (English by default)."""

from testagent.agent.prompts import assemble
from testagent.agent.runtime import Entry
from testagent.core.config import Settings

ENTRY = Entry(name="demo", output_schema=None, tools=(), instructions="Do it.")


def test_default_output_language_is_english(db, monkeypatch):
    monkeypatch.delenv("TESTAGENT_AGENT_LANGUAGE", raising=False)
    assert Settings(_env_file=None).agent_language == "English"
    prompt, _ = assemble(db, ENTRY)
    assert "Write all user-facing text in English." in prompt
    assert "Chinese" not in prompt


def test_output_language_is_configurable(db, monkeypatch):
    monkeypatch.setenv("TESTAGENT_AGENT_LANGUAGE", "Simplified Chinese")
    prompt, _ = assemble(db, ENTRY)
    assert "Write all user-facing text in Simplified Chinese." in prompt
