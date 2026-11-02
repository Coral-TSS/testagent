"""M1-04 model config, tool whitelist and the ReAct runtime, driven by a fake model."""

import threading

import pytest
from pydantic import BaseModel, Field

from testagent.agent.config import AgentConfigService, ModelFactory
from testagent.agent.fake import FakeChatModel, call
from testagent.agent.runtime import AgentRuntime, Entry
from testagent.agent.tools import ToolRegistry, ToolSpec, register_read_tools
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.core.secrets import SecretStore

KEY = "sk-test-" + "k" * 24


class Answer(BaseModel):
    summary: str = Field(min_length=3)
    count: int


ENTRY = Entry(name="demo", output_schema=Answer, tools=("list_nodes",), instructions="Count nodes.")


@pytest.fixture
def secrets(tmp_path):
    return SecretStore(tmp_path / "secrets.json")


def make_runtime(db, secrets, model, entry=ENTRY, checkpointer=None):
    config = AgentConfigService(db, secrets)
    registry = register_read_tools(ToolRegistry(), db, EventBus())
    runtime = AgentRuntime(db, registry, ModelFactory(config, lambda cfg: model), checkpointer=checkpointer)
    runtime.register_entry(entry)
    return runtime


@pytest.fixture
def sut_id(db):
    with db.tx() as cur:
        cur.execute("INSERT INTO sut(code, name) VALUES ('S','s') RETURNING id")
        sut = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO model_node(sut_id, kind, name) VALUES (%s,'entity','Order'), (%s,'action','Place order')",
            (sut, sut),
        )
    return str(sut)


# ------------------------------------------------------------------ config
def test_config_masks_key(client):
    assert client.get("/api/v1/agent/config").json()["configured"] is False
    resp = client.put(
        "/api/v1/agent/config",
        json={"base_url": "https://llm.example/v1", "model": "m1", "api_key": KEY},
    )
    body = resp.json()
    assert body["configured"] is True
    assert body["api_key_masked"] == "****" + KEY[-4:]
    assert KEY not in resp.text
    assert KEY not in client.get("/api/v1/agent/config").text
    removed = client.put("/api/v1/agent/config", json={"api_key": ""}).json()
    assert removed["configured"] is False and removed["api_key_masked"] is None


def test_key_not_in_db(client, db):
    client.put(
        "/api/v1/agent/config",
        json={"base_url": "https://llm.example/v1", "model": "m1", "api_key": KEY},
    )
    with db.tx() as cur:
        cur.execute("SELECT row_to_json(c)::text AS t FROM agent_config c")
        assert KEY not in cur.fetchone()["t"]
        cur.execute("SELECT coalesce(string_agg(diff::text, ''), '') AS t FROM change_log")
        assert KEY not in cur.fetchone()["t"]


def test_unconfigured_returns_model_unavailable(client, db, secrets):
    resp = client.post("/api/v1/agent/config/test")
    assert resp.status_code == 503 and resp.json()["code"] == "MODEL_UNAVAILABLE"
    runtime = AgentRuntime(db, ToolRegistry(), ModelFactory(AgentConfigService(db, secrets)), {"demo": ENTRY})
    with pytest.raises(AppError) as exc:
        runtime.run("demo", {})
    assert exc.value.code == "MODEL_UNAVAILABLE"
    with db.tx() as cur:
        cur.execute("SELECT count(*) AS n FROM agent_run")
        assert cur.fetchone()["n"] == 0


def test_config_test_uses_model(client):
    from langchain_core.messages import AIMessage

    fake = FakeChatModel(script=[AIMessage(content="ok")])
    client.app.state.agent.models.builder = lambda cfg: fake
    assert client.post("/api/v1/agent/config/test").json() == {"ok": True, "reply": "ok"}


# ------------------------------------------------------------------ runtime
def test_run_trace_recorded(db, secrets, sut_id):
    model = FakeChatModel(
        script=[
            call("list_nodes", {"sut_id": sut_id}),
            call("submit_result", {"summary": "two nodes", "count": 2}),
        ]
    )
    run = make_runtime(db, secrets, model).run("demo", {"sut_id": sut_id}, sut_id=sut_id)
    assert run["status"] == "succeeded"
    assert run["result"] == {"summary": "two nodes", "count": 2}
    kinds = [s["type"] for s in run["steps"]]
    assert kinds == ["model", "tool", "model", "submit"]
    tool_step = run["steps"][1]
    assert tool_step["tool"] == "list_nodes" and "Order" in tool_step["result"]
    assert model.bound_tools == ["list_nodes", "submit_result"]
    assert run["started_at"] and run["ended_at"]


def test_entry_cannot_call_unlisted_tool(db, secrets, sut_id):
    model = FakeChatModel(
        script=[
            call("get_requirement_people", {"requirement_id": sut_id}),
            call("submit_result", {"summary": "done", "count": 0}),
        ]
    )
    run = make_runtime(db, secrets, model).run("demo", {})
    refused = run["steps"][1]
    assert refused["status"] == "refused" and refused["tool"] == "get_requirement_people"
    assert "not available" in model.seen[1][-1].content
    assert run["status"] == "succeeded"


def test_submit_result_validation_retry(db, secrets):
    model = FakeChatModel(
        script=[
            call("submit_result", {"summary": "x", "count": "many"}),
            call("submit_result", {"summary": "fixed", "count": 1}),
        ]
    )
    run = make_runtime(db, secrets, model).run("demo", {})
    assert run["status"] == "succeeded" and run["result"]["count"] == 1
    assert "Validation failed" in model.seen[1][-1].content

    always_bad = FakeChatModel(script=[call("submit_result", {"summary": "x"})] * 5)
    failed = make_runtime(db, secrets, always_bad).run("demo", {})
    assert failed["status"] == "failed" and failed["error_code"] == "VALIDATION"
    assert len(always_bad.seen) == 3  # first try + 2 retries


def test_model_must_submit(db, secrets):
    from langchain_core.messages import AIMessage

    model = FakeChatModel(script=[AIMessage(content="I think it's fine")] * 5)
    run = make_runtime(db, secrets, model).run("demo", {})
    assert run["status"] == "failed" and run["error_code"] == "NO_RESULT"


def test_max_steps_stops_run(db, secrets, sut_id):
    entry = Entry(name="demo", output_schema=Answer, tools=("list_nodes",), max_steps=3)
    model = FakeChatModel(script=[call("list_nodes", {"sut_id": sut_id})] * 10)
    run = make_runtime(db, secrets, model, entry).run("demo", {})
    assert run["status"] == "error" and run["error_code"] == "MAX_STEPS"
    assert len(model.seen) == 3


def test_timeout(db, secrets, sut_id):
    entry = Entry(name="demo", output_schema=Answer, tools=("list_nodes",), timeout_s=0.3)
    model = FakeChatModel(script=[call("list_nodes", {"sut_id": sut_id})] * 20, delay_s=0.2)
    run = make_runtime(db, secrets, model, entry).run("demo", {})
    assert run["status"] == "error" and run["error_code"] == "TIMEOUT"
    assert len(model.seen) <= 3


def test_cancel_between_steps(db, secrets, sut_id):
    holder = {}

    def cancelling_tool(sut_id: str) -> str:
        holder["runtime"].cancel(holder["run_id"])
        return "[]"

    class Args(BaseModel):
        sut_id: str

    entry = Entry(name="demo", output_schema=Answer, tools=("slow_list",))
    model = FakeChatModel(script=[call("slow_list", {"sut_id": sut_id})] * 5)
    config = AgentConfigService(db, secrets)
    registry = ToolRegistry()
    registry.register(ToolSpec("slow_list", "test", "d", Args, cancelling_tool))
    runtime = AgentRuntime(db, registry, ModelFactory(config, lambda cfg: model), {"demo": entry})
    holder["runtime"] = runtime
    holder["run_id"] = runtime.start("demo", {})
    run = runtime.execute(holder["run_id"])
    assert run["status"] == "cancelled" and run["error_code"] == "CANCELLED"
    assert len(model.seen) == 1


def test_unknown_tool_in_entry_rejected(db, secrets):
    runtime = make_runtime(db, secrets, FakeChatModel())
    with pytest.raises(KeyError):
        runtime.register_entry(Entry(name="bad", output_schema=Answer, tools=("rm_rf",)))


def test_disabled_memory_not_injected(db, secrets, sut_id):
    with db.tx() as cur:
        cur.execute(
            "INSERT INTO agent_memory(scope, content, enabled) VALUES"
            " ('global', 'GLOBAL-ON', true), ('global', 'GLOBAL-OFF', false)"
        )
        cur.execute(
            "INSERT INTO agent_memory(scope, sut_id, content, tags) VALUES"
            " ('sut', %s, 'SUT-ON', '[\"demo\"]'), ('sut', %s, 'OTHER-ENTRY', '[\"x\"]')",
            (sut_id, sut_id),
        )
    model = FakeChatModel(script=[call("submit_result", {"summary": "abc", "count": 0})])
    make_runtime(db, secrets, model).run("demo", {}, sut_id=sut_id)
    system = model.seen[0][0].content
    assert "GLOBAL-ON" in system and "SUT-ON" in system
    assert "GLOBAL-OFF" not in system and "OTHER-ENTRY" not in system


def test_injected_items_recorded_in_run(db, secrets):
    with db.tx() as cur:
        cur.execute(
            "INSERT INTO prompt_template(name, version, content, active) VALUES"
            " ('system', 1, 'OLD', false), ('system', 2, 'CUSTOM SYSTEM v2', true)"
        )
        cur.execute("INSERT INTO agent_memory(scope, content) VALUES ('global', 'M1') RETURNING id")
        memory_id = str(cur.fetchone()["id"])
    model = FakeChatModel(script=[call("submit_result", {"summary": "abc", "count": 0})])
    run = make_runtime(db, secrets, model).run("demo", {})
    assert run["injected"]["template"]["version"] == 2
    assert run["injected"]["memory_ids"] == [memory_id]
    assert model.seen[0][0].content.startswith("CUSTOM SYSTEM v2")


def test_run_api_get_and_cancel(client, db):
    with db.tx() as cur:
        cur.execute("INSERT INTO agent_run(purpose) VALUES ('demo') RETURNING id")
        run_id = str(cur.fetchone()["id"])
    assert client.get(f"/api/v1/agent/runs/{run_id}").json()["status"] == "queued"
    assert client.post(f"/api/v1/agent/runs/{run_id}/cancel").json() == {"cancel_requested": True}
    assert client.get(f"/api/v1/agent/runs/{run_id}").json()["cancel_requested"] is True
    zero = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/v1/agent/runs/{zero}/cancel").status_code == 404


def test_concurrent_runs_are_independent(db, secrets, sut_id):
    results = []

    def go(n):
        model = FakeChatModel(script=[call("submit_result", {"summary": f"run{n}", "count": n})])
        results.append(make_runtime(db, secrets, model).run("demo", {})["result"]["count"])

    threads = [threading.Thread(target=go, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [0, 1, 2]
