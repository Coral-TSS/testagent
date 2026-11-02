"""/api/v1/agent: model configuration and agent runs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/v1/agent")


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str | None = Field(default=None, pattern=r"^https?://\S+$")
    model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=500, description="'' removes the key")
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_s: int | None = Field(default=None, ge=5, le=3600)
    max_steps: int | None = Field(default=None, ge=1, le=200)
    max_self_checks: int | None = Field(default=None, ge=1, le=20)
    auto_automate: bool | None = None


@router.get("/config")
def get_config(request: Request):
    return request.app.state.agent.config.public()


@router.put("/config")
def put_config(request: Request, body: ConfigIn):
    values = body.model_dump(exclude_unset=True)
    for key in ("temperature", "timeout_s", "max_steps", "max_self_checks", "auto_automate"):
        if key in values and values[key] is None:
            values.pop(key)
    return request.app.state.agent.config.update(values)


@router.post("/config/test")
def test_config(request: Request):
    return request.app.state.agent.models.test_connection()


SUBJECT_ORDER = ("case_id", "execution_id", "requirement_id", "task_run_id", "version_id")


def _subject_ids(row: dict) -> list[str]:
    """What a run was about, most specific first: case, requirement, run, version, SUT."""
    refs = row.get("refs") or {}
    ids = [refs[k] for k in SUBJECT_ORDER if refs.get(k)]
    ids += [v for k, v in refs.items() if k not in SUBJECT_ORDER and k != "sut_id"]
    if row.get("report_run_id"):
        ids.append(row["report_run_id"])
    sut = refs.get("sut_id") or row.get("sut_id")
    if sut:
        ids.append(str(sut))
    return list(dict.fromkeys(str(i) for i in ids))


def _subjects(ids: list[str], resolved: dict[str, dict]) -> list[dict]:
    return [{"id": i, **resolved[i]} for i in ids if i in resolved]


@router.get("/runs")
def list_runs(request: Request, limit: int = Query(50, ge=1, le=500), purpose: str | None = None):
    from testagent.services.labels import resolve_refs

    rows = request.app.state.agent.runtime.list_runs(limit, purpose)
    ids = {r["id"]: _subject_ids(r) for r in rows}
    resolved = resolve_refs(request.app.state.db, [i for v in ids.values() for i in v], 2000)
    for row in rows:
        row["subjects"] = _subjects(ids[row["id"]], resolved)
        row.pop("refs", None)
        row.pop("report_run_id", None)
    return rows


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: UUID):
    from testagent.services.labels import find_uuids, resolve_refs

    run = request.app.state.agent.runtime.get_run(run_id)
    resolved = resolve_refs(request.app.state.db, find_uuids(run))
    run["labels"] = {k: v["label"] for k, v in resolved.items()}
    inputs = (run.get("input_refs") or {}).get("inputs") or {}
    row = {
        "refs": {k: v for k, v in inputs.items() if k.endswith("_id") and isinstance(v, str)},
        "report_run_id": ((inputs.get("report") or {}).get("scope") or {}).get("task_run_id"),
        "sut_id": run.get("sut_id"),
    }
    run["subjects"] = _subjects(_subject_ids(row), resolved)
    return run


@router.post("/runs/{run_id}/cancel")
def cancel_run(request: Request, run_id: UUID):
    request.app.state.agent.runtime.cancel(run_id)
    return {"cancel_requested": True}
