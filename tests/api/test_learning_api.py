"""M1-12 corrections → digest into memories / prompt versions → injection; P15 registry."""

from __future__ import annotations

import pytest
from tests.api.world import V1, FakeRunner, build_world, install_runner, make_case, make_task
from tests.api.world import run_task as run_task_now

from testagent.agent.fake import FakeChatModel, call
from testagent.agent.prompts import DEFAULT_SYSTEM


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


def no_model(client):
    client.app.state.agent.models.builder = None


@pytest.fixture
def w(client, db):
    world = build_world(client, db, n_reqs=1)
    world["case"] = make_case(client, world, "Amount 0 shows an error")
    return world


def correct(client, target_type, target_id, content, **extra):
    resp = client.post(
        f"{V1}/corrections",
        json={"target_type": target_type, "target_id": target_id, "content": content, **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def work(client):
    while client.app.state.worker.run_once():
        pass


def digest_script(memories=(), patches=()):
    return call("submit_result", {"memories": list(memories), "prompt_patches": list(patches)})


MEMORY = {"scope": "sut", "content": "Amount boundaries must cover 0, 0.01 and negatives", "tags": ["generate_cases"]}
PATCH = {"name": "generate_cases", "append_text": "At least one negative-amount case per requirement."}


def drafts(code="REQ-001", n=3):
    return [
        {
            "title": f"{code} Case {i}",
            "test_point": f"Test point {i}",
            "scenario": ("normal", "boundary", "exception")[i % 3],
            "priority": "P1",
            "steps": [{"action": "Open the page"}, {"action": "Submit", "expected": "Success"}],
            "test_data": {"i": i},
            "expected": "Meets the requirement",
            "requirement_codes": [code],
            "node_ids": [],
        }
        for i in range(n)
    ]


# ------------------------------------------------------------------ T-12.1
def test_correction_saved_raw(client, w):
    raw = "  Cases missed a boundary:\n\n  - amount 0.01 should be accepted \n\t(from review)\n"
    row = correct(client, "case", w["case"], raw)
    assert row["content"] == raw and row["status"] == "pending"
    assert row["kind"] == "correction" and row["sut_id"] == w["sut"]
    got = client.get(f"{V1}/corrections/{row['id']}").json()
    assert got["content"] == raw and got["target_label"].endswith("Amount 0 shows an error")
    blank = client.post(
        f"{V1}/corrections",
        json={"target_type": "case", "target_id": w["case"], "content": " \n "},
    )
    assert blank.status_code == 422


def test_post_run_omission_and_targets(client, w):
    install_runner(client, FakeRunner())
    task = make_task(client, w, [w["case"]])
    run = run_task_now(client, task)
    omission = correct(
        client, "task_run", run["id"], "This time we did not test that an approver cannot approve their own order"
    )
    assert omission["kind"] == "omission" and omission["sut_id"] == w["sut"]
    on_version = correct(client, "version", w["version"], "The whole version missed export", kind="omission")
    assert on_version["kind"] == "omission"
    strategy_like = client.post(
        f"{V1}/corrections",
        json={"target_type": "report", "target_id": w["case"], "content": "x"},
    )
    assert strategy_like.status_code == 404
    listed = client.get(f"{V1}/corrections", params={"kind": "omission"}).json()
    assert {c["id"] for c in listed} == {omission["id"], on_version["id"]}


# ------------------------------------------------------------------ T-12.2
def test_digest_creates_memory_with_source(client, w):
    use_model(client, digest_script([MEMORY]))
    corr = correct(client, "case", w["case"], "Boundary values should include 0.01")
    work(client)  # correction.created → digest job (C09)
    got = client.get(f"{V1}/corrections/{corr['id']}").json()
    assert got["status"] == "processed" and got["processed_at"] and got["agent_run_id"]
    mems = client.get(f"{V1}/agent/memories").json()
    assert len(mems) == 1
    m = mems[0]
    assert m["content"] == MEMORY["content"] and m["scope"] == "sut" and m["sut_id"] == w["sut"]
    assert m["source_correction_ids"] == [corr["id"]] and m["enabled"] is True
    assert m["created_by"] == f"agent:{got['agent_run_id']}"
    assert got["outputs"]["memory_ids"] == [m["id"]]
    run = client.get(f"{V1}/agent/runs/{got['agent_run_id']}").json()
    assert run["purpose"] == "digest_correction"


def test_prompt_patch_new_active_version(client, w):
    use_model(
        client,
        digest_script(patches=[PATCH, {"name": "system", "append_text": "Answer in English."}]),
    )
    corr = correct(client, "case", w["case"], "Cases keep missing negative amounts")
    work(client)
    prompts = {p["name"]: p for p in client.get(f"{V1}/agent/prompts").json()}
    gen = client.get(f"{V1}/agent/prompts/generate_cases").json()
    assert [(v["version"], v["active"]) for v in gen] == [(2, True), (1, False)]
    assert gen[1]["content"] == "" and gen[0]["content"] == PATCH["append_text"]
    assert gen[0]["source_correction_ids"] == [corr["id"]]
    system = client.get(f"{V1}/agent/prompts/system").json()
    assert system[1]["content"] == DEFAULT_SYSTEM
    assert system[0]["content"] == DEFAULT_SYSTEM + "\n\nAnswer in English."
    assert prompts["generate_cases"]["active_version"] == 2


def test_failed_digest_retryable(client, w):
    no_model(client)
    corr = correct(client, "case", w["case"], "Steps are too coarse")
    work(client)
    failed = client.get(f"{V1}/corrections/{corr['id']}").json()
    assert failed["status"] == "failed" and "MODEL_UNAVAILABLE" in failed["error"]
    assert failed["content"] == "Steps are too coarse"  # the raw text is never lost
    bad = {"memories": [{"scope": "global", "content": "x", "tags": ["no_such_entry"]}]}
    use_model(client, *[call("submit_result", {**bad, "prompt_patches": []})] * 3)
    assert client.post(f"{V1}/corrections/{corr['id']}/reprocess").status_code == 200
    work(client)
    again = client.get(f"{V1}/corrections/{corr['id']}").json()
    assert again["status"] == "failed" and again["attempts"] == 2
    use_model(client, digest_script([MEMORY]))
    resp = client.post(f"{V1}/corrections/{corr['id']}/reprocess")
    assert resp.json()["status"] == "pending"
    work(client)
    done = client.get(f"{V1}/corrections/{corr['id']}").json()
    assert done["status"] == "processed" and done["attempts"] == 3 and done["error"] is None
    assert client.post(f"{V1}/corrections/{corr['id']}/reprocess").status_code == 200  # allowed


# ------------------------------------------------------------------ T-12.3
def test_new_memory_injected_next_generation(client, w, db):
    use_model(
        client,
        digest_script(
            [
                MEMORY,
                {
                    **MEMORY,
                    "content": "Another unrelated system",
                    "scope": "global",
                    "tags": ["analyze_failure"],
                },
            ],
            [PATCH],
        ),
    )
    correct(client, "case", w["case"], "Boundary values should include 0.01")
    work(client)
    mem = next(m for m in client.get(f"{V1}/agent/memories").json() if m["scope"] == "sut")
    fake = use_model(client, call("submit_result", {"cases": drafts()}))
    body = client.post(f"{V1}/versions/{w['version']}/cases/generate", json={}).json()
    assert body["status"] == "succeeded", body
    run = client.get(f"{V1}/agent/runs/{body['agent_run_id']}").json()
    assert run["injected"]["memory_ids"] == [mem["id"]]  # tag-filtered: analyze_failure one skipped
    assert run["injected"]["entry_template"]["version"] == 2
    system = fake.seen[0][0].content
    assert MEMORY["content"] in system and PATCH["append_text"] in system
    assert "Another unrelated system" not in system
    # disabled memories are not injected
    assert client.patch(f"{V1}/agent/memories/{mem['id']}", json={"enabled": False}).json()["enabled"] is False
    fake = use_model(client, call("submit_result", {"cases": drafts()}))
    body = client.post(f"{V1}/versions/{w['version']}/cases/generate", json={}).json()
    run = client.get(f"{V1}/agent/runs/{body['agent_run_id']}").json()
    assert run["injected"]["memory_ids"] == []
    assert MEMORY["content"] not in fake.seen[0][0].content


# ------------------------------------------------------------------ T-12.4
def test_prompt_rollback(client, w):
    use_model(client, digest_script(patches=[PATCH]))
    correct(client, "case", w["case"], "missing negatives")
    work(client)
    resp = client.post(f"{V1}/agent/prompts/generate_cases/versions/1/activate")
    assert resp.status_code == 200
    versions = client.get(f"{V1}/agent/prompts/generate_cases").json()
    assert [(v["version"], v["active"]) for v in versions] == [(2, False), (1, True)]
    fake = use_model(client, call("submit_result", {"cases": drafts()}))
    client.post(f"{V1}/versions/{w['version']}/cases/generate", json={})
    assert PATCH["append_text"] not in fake.seen[0][0].content
    # human edit → new active version; history kept
    new = client.post(
        f"{V1}/agent/prompts/generate_cases/versions",
        json={"content": "Manually rewritten guidance", "note": "Rewritten after review"},
    ).json()
    assert new["version"] == 3 and new["active"] and new["created_by"] == "local-user"
    assert client.post(f"{V1}/agent/prompts/generate_cases/versions/9/activate").status_code == 404
    assert client.post(f"{V1}/agent/prompts/nope/versions", json={"content": "x"}).status_code == 422


def test_skill_mcp_register_only(client):
    tools_before = set(client.app.state.agent.registry.names())
    skill = client.post(
        f"{V1}/agent/skills",
        json={"name": "jira-export", "description": "Export to Jira", "source": "skills/jira"},
    )
    assert skill.status_code == 201, skill.text
    mcp = client.post(
        f"{V1}/agent/mcp-servers",
        json={
            "name": "fs",
            "transport": "stdio",
            "command": "npx fs-server",
            "description": "File",
        },
    ).json()
    assert client.post(f"{V1}/agent/skills", json={"name": "jira-export"}).status_code == 409
    off = client.patch(f"{V1}/agent/mcp-servers/{mcp['id']}", json={"enabled": False}).json()
    assert off["enabled"] is False
    assert [s["name"] for s in client.get(f"{V1}/agent/skills").json()] == ["jira-export"]
    assert [m["name"] for m in client.get(f"{V1}/agent/mcp-servers").json()] == ["fs"]
    # registration never loads or executes anything (C07)
    assert set(client.app.state.agent.registry.names()) == tools_before
    entries = client.app.state.agent.runtime.entries.values()
    assert all("jira-export" not in e.tools and "fs" not in e.tools for e in entries)
