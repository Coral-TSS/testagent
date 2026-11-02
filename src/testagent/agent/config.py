"""OpenAI-compatible model configuration. The API key lives in the local secret store only."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from testagent.core.errors import AppError
from testagent.core.secrets import SecretStore
from testagent.services.changelog import log_change

KEY_NAME = "llm_api_key"
FIELDS = (
    "base_url",
    "model",
    "temperature",
    "max_tokens",
    "timeout_s",
    "max_steps",
    "max_self_checks",
    "auto_automate",
)


@dataclass(frozen=True)
class LlmConfig:
    base_url: str | None
    model: str | None
    temperature: float
    max_tokens: int | None
    timeout_s: int
    max_steps: int
    api_key: str | None
    max_self_checks: int = 5
    auto_automate: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)


class AgentConfigService:
    def __init__(self, db, secrets: SecretStore, actor: str = "local-user"):
        self.db = db
        self.secrets = secrets
        self.actor = actor

    def _row(self, cur) -> dict:
        cur.execute("INSERT INTO agent_config(id) VALUES ('default') ON CONFLICT DO NOTHING")
        cur.execute("SELECT * FROM agent_config WHERE id='default'")
        return cur.fetchone()

    def load(self) -> LlmConfig:
        with self.db.tx() as cur:
            row = self._row(cur)
        key = self.secrets.get(row["api_key_ref"]) if row["api_key_ref"] else None
        return LlmConfig(
            base_url=row["base_url"],
            model=row["model"],
            temperature=float(row["temperature"]),
            max_tokens=row["max_tokens"],
            timeout_s=row["timeout_s"],
            max_steps=row["max_steps"],
            api_key=key,
            max_self_checks=row.get("max_self_checks") or 5,
            auto_automate=bool(row.get("auto_automate", True)),
        )

    def public(self) -> dict:
        cfg = self.load()
        return {
            **{f: getattr(cfg, f) for f in FIELDS},
            "api_key_masked": SecretStore.mask(cfg.api_key),
            "configured": cfg.configured,
        }

    def update(self, values: dict[str, Any]) -> dict:
        values = dict(values)
        api_key = values.pop("api_key", None)
        with self.db.tx() as cur:
            self._row(cur)
            changes = {k: v for k, v in values.items() if k in FIELDS}
            if api_key is not None:
                if api_key == "":
                    self.secrets.delete(KEY_NAME)
                    changes["api_key_ref"] = None
                else:
                    self.secrets.set(KEY_NAME, api_key)
                    changes["api_key_ref"] = KEY_NAME
            if changes:
                sets = ", ".join(f"{k}=%s" for k in changes)
                cur.execute(
                    f"UPDATE agent_config SET {sets}, updated_at=now() WHERE id='default'",
                    list(changes.values()),
                )
            audit = {k: v for k, v in changes.items() if k != "api_key_ref"}
            if api_key is not None:
                audit["api_key"] = "(changed)" if api_key else "(removed)"
            log_change(cur, "agent_config", "default", "update", self.actor, audit)
        return self.public()


ModelBuilder = Callable[[LlmConfig], Any]


def build_openai_model(cfg: LlmConfig):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout=cfg.timeout_s,
        max_retries=1,
    )


class ModelFactory:
    """Creates the chat model for a run. Tests inject a builder that returns a FakeChatModel."""

    def __init__(self, config: AgentConfigService, builder: ModelBuilder | None = None):
        self.config = config
        self.builder = builder

    def create(self):
        cfg = self.config.load()
        if self.builder is not None:
            return self.builder(cfg)
        if not cfg.configured:
            raise AppError("MODEL_UNAVAILABLE", "No model configured yet (base_url, model, API key)")
        return build_openai_model(cfg)

    def test_connection(self) -> dict:
        from langchain_core.messages import HumanMessage

        model = self.create()
        try:
            reply = model.invoke([HumanMessage(content="Reply with the single word: ok")])
        except Exception as exc:
            raise AppError("MODEL_UNAVAILABLE", f"Model connection failed: {type(exc).__name__}") from exc
        return {"ok": True, "reply": str(reply.content)[:200]}
