"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from testagent import __version__
from testagent.agent.container import build_agent
from testagent.api import (
    agent,
    auth,
    cases,
    defects,
    executions,
    jobs,
    learning,
    model,
    navigation,
    registry,
    reports,
    requirements,
    runs,
    strategy,
)
from testagent.core.artifacts import ArtifactStore
from testagent.core.auth import AuthMiddleware
from testagent.core.config import DEFAULT_TIMEZONE
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.core.jobs import JobQueue
from testagent.core.secrets import SecretStore
from testagent.core.worker import Worker
from testagent.services.environments import EnvironmentProcesses
from testagent.services.runs import JOB_KIND, RunService, run_channel
from testagent.services.scheduler import Scheduler

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIST = Path(__file__).resolve().parents[1] / "web"  # vite build output
DEFAULT_RUNTIME = REPO_ROOT / "runtime"

PLACEHOLDER = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>TestAgent</title><body><h1>TestAgent</h1>
<p>The web UI has not been built yet: run npm ci and npm run build in web/ (or run ops\\start.ps1).</p>
<p>The API is under /api/v1.</p></body></html>"""


def _describe_payload(db, payload: dict) -> str:
    from testagent.services.labels import describe, find_uuids, resolve_refs

    ids = find_uuids(payload)
    return describe(resolve_refs(db, ids), ids)


def create_app(
    db,
    bus: EventBus | None = None,
    web_dist: Path = WEB_DIST,
    secrets: SecretStore | None = None,
    model_builder=None,
    checkpointer=None,
    runtime_dir: Path = DEFAULT_RUNTIME,
    browser_headless: bool = True,
    pytest_timeout_s: float = 300,
    background: bool = False,
    instance_lock=None,
    timezone: str = DEFAULT_TIMEZONE,
    allowed_hosts: list[str] | tuple[str, ...] = (),
    cookie_secure: str = "auto",
    session_idle_hours: float = 12,
    session_max_days: float = 7,
    login_per_minute: int = 10,
    login_per_hour: int = 100,
) -> FastAPI:
    """`background=True` (launcher) starts the Worker thread; the scheduler additionally needs the
    held `instance_lock`. Tests leave both off and drive `app.state.worker.run_once()`."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if background:
            app.state.worker.start()
            app.state.scheduler.start()
        try:
            yield
        finally:
            if background:
                app.state.scheduler.stop()
                app.state.worker.stop()
            app.state.env_processes.stop_all()  # systems under test started by this instance

    app = FastAPI(title="TestAgent", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.db = db
    app.state.timezone = timezone
    app.state.bus = bus or EventBus()
    app.state.artifacts = ArtifactStore(runtime_dir / "artifacts")
    app.state.repos_root = runtime_dir / "repos"
    app.state.env_processes = EnvironmentProcesses(runtime_dir / "logs")
    app.state.browser_headless = browser_headless
    app.state.pytest_timeout_s = pytest_timeout_s
    app.state.agent = build_agent(
        db,
        app.state.bus,
        secrets or SecretStore(runtime_dir / "secrets.json"),
        model_builder,
        checkpointer,
    )
    from testagent.api.executions import execution_service

    state = app.state
    state.executor_runners = {}  # EP-03 overrides (tests install fakes here)
    state.jobs = JobQueue(db)
    from testagent.services.auth import AuthService, LocalTickets, LoginRateLimiter

    state.auth = AuthService(db, session_idle_hours, session_max_days)
    state.tickets = LocalTickets()
    state.login_limiter = LoginRateLimiter(login_per_minute, login_per_hour)
    state.cookie_secure = cookie_secure
    state.runs_factory = lambda actor=None: RunService(
        db, state.bus, executions=lambda: execution_service(state, "system"), actor=actor
    )
    state.runs_channel = lambda run_id: run_channel(db, run_id)
    from testagent.services.automation import AUTOMATE_JOB, AutomationService
    from testagent.services.case_complete import COMPLETE_JOB, CaseCompletionService
    from testagent.services.learning import DIGEST_JOB, DigestService

    def _automate_job(p: dict) -> None:
        AutomationService(
            db, state.bus, state.agent.runtime, state.repos_root, pytest_timeout_s=pytest_timeout_s
        ).automate(p["case_id"], p.get("environment_id"))

    state.worker = Worker(
        state.jobs,
        {
            JOB_KIND: lambda p: state.runs_factory("system").execute(p),
            DIGEST_JOB: lambda p: DigestService(db, state.bus, state.agent.runtime).digest(p["id"]),
            AUTOMATE_JOB: _automate_job,
            COMPLETE_JOB: lambda p: CaseCompletionService(db, state.bus, state.agent.runtime, actor="system").complete(
                p["case_id"]
            ),
        },
        describe=lambda payload: _describe_payload(db, payload),
    )
    state.scheduler = Scheduler(db, lambda: state.runs_factory("scheduler"), instance_lock)

    def _report_on_finish(_event: str, payload: dict) -> None:
        from testagent.services.reports import ReportService

        if payload.get("status") in ("passed", "failed", "cancelled", "not_executed"):
            ReportService(db, state.bus, state.agent.runtime, actor="system").for_run(payload["id"])

    state.bus.subscribe("task_run.finished", _report_on_finish)  # T-11.3

    def _digest_later(_event: str, payload: dict) -> None:  # C09: digest right away, in the worker
        state.jobs.enqueue(DIGEST_JOB, {"id": payload["id"]})

    def _reconcile_case(event: str, payload: dict) -> None:  # cases join matching tasks
        from testagent.services.task_binding import TaskBindingService

        TaskBindingService(db, state.bus, actor="system").reconcile_case(payload["id"], event)

    for event in ("case.ready", "case.draft", "case.deprecated", "case.updated"):
        state.bus.subscribe(event, _reconcile_case)
    state.bus.subscribe("correction.created", _digest_later)
    state.bus.subscribe("correction.reprocess", _digest_later)
    app.add_middleware(AuthMiddleware, auth=state.auth, allowed_hosts=allowed_hosts)
    from testagent.core.access_log import AccessLogMiddleware

    app.add_middleware(AccessLogMiddleware)  # outermost: also logs 401s

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]), "msg": e["msg"]} for e in exc.errors()]
        body = AppError("VALIDATION", "Invalid request parameters", field_errors=fields).body()
        return JSONResponse(status_code=422, content=body)

    @app.get("/api/v1/settings/general")
    def general_settings():
        return {"timezone": app.state.timezone}

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok" if db.ping() else "db_unavailable", "version": __version__}

    app.include_router(auth.router)
    app.include_router(learning.router)
    app.include_router(registry.router)
    app.include_router(model.router)
    app.include_router(agent.router)
    app.include_router(jobs.router)
    app.include_router(requirements.router)
    app.include_router(strategy.router)
    app.include_router(cases.router)
    app.include_router(executions.router)
    app.include_router(runs.router)
    app.include_router(defects.router)
    app.include_router(reports.router)
    app.include_router(navigation.router)

    index_file = web_dist / "index.html"
    if index_file.exists():
        if (web_dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise AppError("NOT_FOUND", "Endpoint not found")
            candidate = (web_dist / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(web_dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(index_file)  # client-side routes
    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def index():
            return PLACEHOLDER

    return app
