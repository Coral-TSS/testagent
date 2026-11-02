"""Wires config, model factory, tool registry and runtime for one app instance."""

from __future__ import annotations

from dataclasses import dataclass

from testagent.agent.config import AgentConfigService, ModelBuilder, ModelFactory
from testagent.agent.runtime import AgentRuntime
from testagent.agent.tools import ToolRegistry, register_read_tools
from testagent.core.events import EventBus
from testagent.core.secrets import SecretStore


@dataclass
class AgentContainer:
    config: AgentConfigService
    models: ModelFactory
    registry: ToolRegistry
    runtime: AgentRuntime


def build_agent(
    db,
    bus: EventBus,
    secrets: SecretStore,
    model_builder: ModelBuilder | None = None,
    checkpointer=None,
) -> AgentContainer:
    config = AgentConfigService(db, secrets)
    models = ModelFactory(config, model_builder)
    registry = register_read_tools(ToolRegistry(), db, bus)
    from testagent.integrations.browser import register_browser_tools
    from testagent.integrations.http_api import register_api_tools
    from testagent.services.automation import automate_entry, register_automation_tools

    register_browser_tools(registry)
    register_api_tools(registry)
    register_automation_tools(registry)
    runtime = AgentRuntime(db, registry, models, checkpointer=checkpointer)
    from testagent.services.ai_tasks import build_entries  # services depend on the runtime
    from testagent.services.case_complete import complete_entry
    from testagent.services.case_gen import cases_entry
    from testagent.services.executions import api_entry, browser_entry
    from testagent.services.failure_analysis import analysis_entry
    from testagent.services.learning import digest_entry
    from testagent.services.reports import summary_entry
    from testagent.services.strategy import strategy_entry

    for entry in [*build_entries(db), strategy_entry(db), cases_entry(db), complete_entry(db)]:
        runtime.register_entry(entry)
    for entry in (
        browser_entry(),
        api_entry(),
        automate_entry(),
        analysis_entry(),
        summary_entry(),
        digest_entry(),
    ):
        runtime.register_entry(entry)
    return AgentContainer(config, models, registry, runtime)
