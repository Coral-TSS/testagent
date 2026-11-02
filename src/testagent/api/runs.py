"""/api/v1 task runs (M1-09): start, cancel, read, SSE progress."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from testagent.core.jobs import Listener
from testagent.services.runs import TERMINAL, RunService, run_channel

router = APIRouter(prefix="/api/v1")
KEEPALIVE_S = 15.0


def runs(request: Request) -> RunService:
    return request.app.state.runs_factory()


@router.post("/tasks/{task_id}/run", status_code=201)
def start_run(request: Request, task_id: UUID):
    return runs(request).start(task_id)


@router.get("/tasks/{task_id}/runs")
def list_runs(request: Request, task_id: UUID):
    return runs(request).list_for_task(task_id)


@router.get("/runs")
def recent_runs(request: Request, version_id: UUID | None = None, limit: int = Query(50, le=200)):
    return runs(request).list_recent(version_id, limit)


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: UUID):
    return runs(request).get(run_id)


@router.post("/runs/{run_id}/cancel")
def cancel_run(request: Request, run_id: UUID):
    return runs(request).cancel(run_id)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/runs/{run_id}/events")
def run_events(request: Request, run_id: UUID):
    """Server-sent events. Starts with a `snapshot` (full state, so a reconnecting client is
    complete again), then `case`/`run` progress, and `end` once the run is finished."""
    service = runs(request)
    service.get(run_id)  # 404 before the stream starts
    db = request.app.state.db

    def stream():
        listener = Listener(db, run_channel(db, run_id))  # LISTEN before the snapshot: no gaps
        try:
            snapshot = service.get(run_id)
            yield _sse("snapshot", snapshot)
            if snapshot["status"] in TERMINAL:
                yield _sse("end", {"status": snapshot["status"]})
                return
            while True:
                payload = listener.next(KEEPALIVE_S)
                if payload is None:
                    current = service.get(run_id)
                    if current["status"] in TERMINAL:  # finished while we were not told
                        yield _sse("snapshot", current)
                        yield _sse("end", {"status": current["status"]})
                        return
                    yield ": keepalive\n\n"
                    continue
                data = json.loads(payload)
                yield _sse(data.get("type", "message"), data)
                if data.get("type") == "run" and data.get("status") in TERMINAL:
                    yield _sse("end", {"status": data["status"]})
                    return
        finally:
            listener.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
