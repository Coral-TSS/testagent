"""ReAct agent runtime on LangGraph with a guarded tool loop.

Each entry declares its tool whitelist and output schema. The model must finish by calling
`submit_result`; the payload is validated with Pydantic (max 2 retries). Cancellation, timeout
and the step limit are checked between steps and before every tool call. Every step is appended
to agent_run.steps; the business write happens later in the service layer (BR-03)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

from testagent.agent.config import ModelFactory
from testagent.agent.prompts import assemble
from testagent.agent.tools import ToolRegistry
from testagent.core.errors import AppError

SUBMIT = "submit_result"
MAX_SUBMIT_RETRIES = 2


@dataclass(frozen=True)
class Entry:
    name: str
    output_schema: type[BaseModel]
    tools: tuple[str, ...] = ()
    template: str = "system"
    instructions: str = ""
    max_steps: int | None = None
    timeout_s: float | None = None
    validate: Callable[[BaseModel, dict], list[str]] | None = None
    """Semantic checks (e.g. node IDs exist) run after schema validation; errors go back to the
    model just like schema errors."""


class RunState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    steps: int
    attempts: int
    result: dict | None
    outcome: str | None
    error_code: str | None


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _short(value: Any, limit: int = 500) -> str:
    text = value if isinstance(value, str) else _dumps(value)
    return text if len(text) <= limit else text[:limit] + "…"


class AgentRuntime:
    def __init__(
        self,
        db,
        registry: ToolRegistry,
        models: ModelFactory,
        entries: dict[str, Entry] | None = None,
        checkpointer=None,
    ):
        self.db = db
        self.registry = registry
        self.models = models
        self.entries: dict[str, Entry] = dict(entries or {})
        self.checkpointer = checkpointer or InMemorySaver()
        self._resources: dict[str, dict] = {}
        """Per-run live objects (e.g. a browser session) handed to context-aware tools."""

    def register_entry(self, entry: Entry) -> None:
        self.registry.subset(entry.tools)  # fail early on unknown tools
        self.entries[entry.name] = entry

    # ------------------------------------------------------------ bookkeeping
    def _append_step(self, run_id, step: dict) -> None:
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE agent_run SET steps = steps || %s WHERE id=%s",
                (Jsonb([step], dumps=_dumps), run_id),
            )

    def _cancel_requested(self, run_id) -> bool:
        with self.db.tx() as cur:
            cur.execute("SELECT cancel_requested FROM agent_run WHERE id=%s", (run_id,))
            row = cur.fetchone()
        return bool(row and row["cancel_requested"])

    def cancel(self, run_id) -> None:
        with self.db.tx() as cur:
            cur.execute("UPDATE agent_run SET cancel_requested=true WHERE id=%s RETURNING status", (run_id,))
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "Agent run not found")

    def get_run(self, run_id) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM agent_run WHERE id=%s", (run_id,))
            row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Agent run not found")
        return row

    def list_runs(self, limit: int = 50, purpose: str | None = None) -> list[dict]:
        """Newest runs without their (possibly large) step lists, for the trace viewer index."""
        with self.db.tx() as cur:
            cur.execute(
                "SELECT id, purpose, status, error_code, error, cancel_requested, started_at,"
                " ended_at, created_at, jsonb_array_length(steps) AS step_count, sut_id,"
                " (SELECT jsonb_object_agg(k, v) FROM jsonb_each(input_refs->'inputs') e(k, v)"
                "   WHERE k LIKE '%%\\_id' AND jsonb_typeof(v)='string') AS refs,"
                " input_refs#>>'{inputs,report,scope,task_run_id}' AS report_run_id,"
                " input_refs#>>'{inputs,case,code}' AS case_code FROM agent_run"
                " WHERE (%s::text IS NULL OR purpose=%s) ORDER BY created_at DESC LIMIT %s",
                (purpose, purpose, limit),
            )
            return cur.fetchall()

    # ------------------------------------------------------------ graph
    def _build(self, run_id, entry: Entry, model, deadline: float, max_steps: int, ctx: dict):
        allowed = self.registry.subset(entry.tools)
        lc_tools = [ToolRegistry.as_langchain(s) for s in allowed.values()]
        submit_tool = StructuredTool.from_function(
            func=lambda **kw: "ok",
            name=SUBMIT,
            description="Submit the final structured result. Call exactly once at the end.",
            args_schema=entry.output_schema,
        )
        bound = model.bind_tools([*lc_tools, submit_tool])

        def guard(state: RunState, *, counting_steps: bool) -> str | None:
            if self._cancel_requested(run_id):
                return "CANCELLED"
            if time.monotonic() > deadline:
                return "TIMEOUT"
            if counting_steps and state.get("steps", 0) >= max_steps:
                return "MAX_STEPS"
            return None

        def agent_node(state: RunState) -> dict:
            stop = guard(state, counting_steps=True)
            if stop:
                return {"outcome": "stopped", "error_code": stop}
            started = time.monotonic()
            reply: AIMessage = bound.invoke(state["messages"])
            seq = state.get("steps", 0) + 1
            self._append_step(
                run_id,
                {
                    "seq": seq,
                    "type": "model",
                    "content": _short(reply.content),
                    "tool_calls": [{"name": c["name"], "args": c["args"]} for c in reply.tool_calls],
                    "ms": int((time.monotonic() - started) * 1000),
                    "tokens": getattr(reply, "usage_metadata", None),
                },
            )
            return {"messages": [reply], "steps": seq}

        def nudge_node(state: RunState) -> dict:
            attempts = state.get("attempts", 0) + 1
            if attempts > MAX_SUBMIT_RETRIES:
                return {"attempts": attempts, "outcome": "failed", "error_code": "NO_RESULT"}
            msg = HumanMessage(content=f"You must finish by calling {SUBMIT} with the result.")
            return {"attempts": attempts, "messages": [msg]}

        def tools_node(state: RunState) -> dict:
            last: AIMessage = state["messages"][-1]
            out: list[ToolMessage] = []
            attempts = state.get("attempts", 0)
            for call in last.tool_calls:
                stop = guard(state, counting_steps=False)
                if stop:
                    return {"messages": out, "outcome": "stopped", "error_code": stop}
                name, args, call_id = call["name"], call.get("args") or {}, call["id"]
                started = time.monotonic()
                if name == SUBMIT:
                    errors: list[dict] = []
                    try:
                        parsed = entry.output_schema.model_validate(args)
                        result = parsed.model_dump(mode="json")
                        if entry.validate is not None:
                            errors = [{"loc": "", "msg": m} for m in entry.validate(parsed, ctx)]
                    except ValidationError as exc:
                        errors = [{"loc": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
                    if errors:
                        attempts += 1
                        self._append_step(
                            run_id,
                            {"type": "submit_invalid", "errors": errors, "attempt": attempts},
                        )
                        if attempts > MAX_SUBMIT_RETRIES:
                            return {
                                "messages": out,
                                "attempts": attempts,
                                "outcome": "failed",
                                "error_code": "VALIDATION",
                            }
                        out.append(
                            ToolMessage(
                                content="Validation failed, fix and call submit_result again: " + _dumps(errors),
                                tool_call_id=call_id,
                                name=SUBMIT,
                            )
                        )
                        continue
                    self._append_step(run_id, {"type": "submit", "result": result})
                    out.append(ToolMessage(content="accepted", tool_call_id=call_id, name=SUBMIT))
                    return {
                        "messages": out,
                        "attempts": attempts,
                        "result": result,
                        "outcome": "succeeded",
                    }
                resolved = args
                if name not in allowed:
                    content = f"Error: tool '{name}' is not available for this task."
                    status = "refused"
                else:
                    try:
                        spec = allowed[name]
                        resolved = self.registry.resolve(name, args, ctx)
                        value = spec.func(ctx=ctx, **resolved) if spec.needs_ctx else spec.func(**resolved)
                        content = _short(value, 20000)
                        status = "ok"
                    except AppError as exc:
                        content, status = f"Error: {exc.code} {exc.message}", "error"
                    except Exception as exc:  # tool failures go back to the model
                        content, status = f"Error: {type(exc).__name__}: {exc}", "error"
                self._append_step(
                    run_id,
                    {
                        "type": "tool",
                        "tool": name,
                        "args": args,
                        **({"resolved_args": resolved} if resolved != args else {}),
                        "status": status,
                        "result": _short(content),
                        "ms": int((time.monotonic() - started) * 1000),
                    },
                )
                out.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
            return {"messages": out, "attempts": attempts}

        def after_agent(state: RunState) -> str:
            if state.get("outcome"):
                return END
            last = state["messages"][-1]
            return "tools" if getattr(last, "tool_calls", None) else "nudge"

        def after_step(state: RunState) -> str:
            return END if state.get("outcome") else "agent"

        graph = StateGraph(RunState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tools_node)
        graph.add_node("nudge", nudge_node)
        graph.set_entry_point("agent")
        graph.add_conditional_edges("agent", after_agent, ["tools", "nudge", END])
        graph.add_conditional_edges("tools", after_step, ["agent", END])
        graph.add_conditional_edges("nudge", after_step, ["agent", END])
        return graph.compile(checkpointer=self.checkpointer)

    # ------------------------------------------------------------ public API
    def start(self, entry_name: str, inputs: dict, *, sut_id=None, context: dict | None = None):
        """Create the agent_run (queued). Raises MODEL_UNAVAILABLE before anything is stored."""
        if entry_name not in self.entries:
            raise AppError("VALIDATION", f"Unknown agent entry: {entry_name}")
        self.models.create()  # fail fast when the model is not configured
        entry = self.entries[entry_name]
        system, injected = assemble(self.db, entry, sut_id, context)
        with self.db.tx() as cur:
            cur.execute(
                "INSERT INTO agent_run(purpose, input_refs, sut_id, injected) VALUES (%s,%s,%s,%s) RETURNING id",
                (
                    entry_name,
                    Jsonb({"inputs": inputs, "system": system}, dumps=_dumps),
                    sut_id,
                    Jsonb(injected),
                ),
            )
            run_id = cur.fetchone()["id"]
            cur.execute("UPDATE agent_run SET thread_id=%s WHERE id=%s", (str(run_id), run_id))
        return run_id

    def execute(self, run_id, *, resume: bool = False) -> dict:
        run = self.get_run(run_id)
        entry = self.entries[run["purpose"]]
        cfg = self.models.config.load()
        max_steps = entry.max_steps or cfg.max_steps
        timeout = entry.timeout_s or cfg.timeout_s
        model = self.models.create()
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE agent_run SET status='running', started_at=coalesce(started_at, now()),"
                " error=NULL, error_code=NULL WHERE id=%s",
                (run_id,),
            )
        ctx = {
            "run_id": str(run_id),
            "sut_id": run["sut_id"],
            "inputs": run["input_refs"]["inputs"],
            "resources": self._resources.get(str(run_id), {}),
        }
        graph = self._build(run_id, entry, model, time.monotonic() + timeout, max_steps, ctx)
        config = {
            "configurable": {"thread_id": run["thread_id"]},
            "recursion_limit": 4 * max_steps + 10,
        }
        if resume:
            payload = None
        else:
            stored = run["input_refs"]
            payload = {
                "messages": [
                    SystemMessage(content=stored["system"]),
                    HumanMessage(content=_dumps(stored["inputs"])),
                ],
                "steps": 0,
                "attempts": 0,
            }
        try:
            final = graph.invoke(payload, config, durability="sync")
        except AppError as exc:
            final = {"outcome": "stopped", "error_code": exc.code, "error": exc.message}
        except Exception as exc:
            final = {"outcome": "stopped", "error_code": "MODEL_ERROR", "error": type(exc).__name__}
        status = {
            "succeeded": "succeeded",
            "failed": "failed",
        }.get(final.get("outcome"), "error")
        if final.get("error_code") == "CANCELLED":
            status = "cancelled"
        with self.db.tx() as cur:
            cur.execute(
                "UPDATE agent_run SET status=%s, result=%s, error_code=%s, error=%s, ended_at=now()"
                " WHERE id=%s RETURNING *",
                (
                    status,
                    Jsonb(final.get("result")) if final.get("result") is not None else None,
                    final.get("error_code"),
                    final.get("error"),
                    run_id,
                ),
            )
            return cur.fetchone()

    def run(self, entry_name: str, inputs: dict, *, sut_id=None, context=None, resources=None) -> dict:
        run_id = self.start(entry_name, inputs, sut_id=sut_id, context=context)
        if resources:
            self._resources[str(run_id)] = resources
        try:
            return self.execute(run_id)
        finally:
            self._resources.pop(str(run_id), None)
