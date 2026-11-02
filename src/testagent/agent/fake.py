"""Deterministic chat model for tests: replays scripted AI messages, records what it saw."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field


def call(name: str, args: dict | None = None, call_id: str | None = None) -> AIMessage:
    """AI message that requests one tool call."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id or f"c-{name}"}])


class FakeChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    script: list[Any] = Field(default_factory=list)
    """AIMessage items, or callables (messages) -> AIMessage."""
    delay_s: float = 0.0
    seen: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[str] = Field(default_factory=list)
    position: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-chat"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any):
        self.bound_tools = [getattr(t, "name", None) or t["name"] for t in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen.append(list(messages))
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.position >= len(self.script):
            message: AIMessage = AIMessage(content="(script exhausted)")
        else:
            item = self.script[self.position]
            message = item(messages) if callable(item) else item
            message = message.model_copy(deep=True, update={"id": None})  # fresh id
        self.position += 1
        return ChatResult(generations=[ChatGeneration(message=message)])
