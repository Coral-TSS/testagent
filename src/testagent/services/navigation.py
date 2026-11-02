"""where am I and what next.

``context`` builds the breadcrumb chain of any detail object (SUT → version → … → object) with
readable "Name (code)" labels and front-end paths; ``progress`` reports the main flow of a SUT
(SUT → model → version/requirements → test strategy → tasks → cases → execution → defects/reports) for one version, with
the next suggested action. Read-only."""

from __future__ import annotations

from testagent.core.errors import AppError

KINDS = ("sut", "version", "requirement", "task", "run", "case", "execution", "defect", "report")


def _fmt_time(ts) -> str:
    return ts.astimezone().strftime("%m-%d %H:%M") if ts else ""


def sut_label(row: dict) -> str:
    return f"{row['name']} ({row['code']})"


def _one(cur, sql: str, args) -> dict:
    cur.execute(sql, args)
    row = cur.fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Object not found")
    return row


class _Chain:
    def __init__(self, cur):
        self.cur = cur
        self.items: list[dict] = []
        self.sut: dict | None = None
        self.version: dict | None = None

    def add(self, kind, id_, label, path):
        self.items.append({"kind": kind, "id": str(id_) if id_ else None, "label": label, "path": path})

    def add_sut(self, sut_id):
        row = _one(self.cur, "SELECT id, code, name FROM sut WHERE id=%s", (sut_id,))
        self.sut = {"id": str(row["id"]), "code": row["code"], "name": row["name"]}
        self.add("sut", row["id"], sut_label(row), f"/suts/{row['id']}")

    def add_version(self, version_id):
        row = _one(self.cur, "SELECT id, sut_id, name, status FROM version WHERE id=%s", (version_id,))
        self.add_sut(row["sut_id"])
        self.version = {"id": str(row["id"]), "name": row["name"], "status": row["status"]}
        self.add("version", row["id"], f"Version {row['name']}", f"/versions/{row['id']}")

    def add_task(self, task_id):
        row = _one(self.cur, "SELECT id, version_id, name FROM test_task WHERE id=%s", (task_id,))
        self.add_version(row["version_id"])
        self.add("strategy", None, "Test strategy & tasks", f"/versions/{row['version_id']}?tab=strategy")
        self.add("task", row["id"], row["name"], f"/tasks/{row['id']}")

    def add_run(self, run_id):
        row = _one(self.cur, "SELECT id, task_id, created_at FROM task_run WHERE id=%s", (run_id,))
        self.add_task(row["task_id"])
        self.add("run", row["id"], f"Run {_fmt_time(row['created_at'])}", f"/runs/{row['id']}")

    def add_case(self, case_id, with_parents=True):
        row = _one(
            self.cur,
            "SELECT c.id, c.sut_id, c.code, c.title, COALESCE(c.origin_version_id,"
            " (SELECT r.version_id FROM case_requirement_link l JOIN requirement r"
            "  ON r.id=l.requirement_id WHERE l.case_id=c.id LIMIT 1)) AS version_id"
            " FROM test_case c WHERE c.id=%s",
            (case_id,),
        )
        if with_parents:
            if row["version_id"]:
                self.add_version(row["version_id"])
                self.add("cases", None, "Case", f"/versions/{row['version_id']}?tab=cases")
            else:
                self.add_sut(row["sut_id"])
                self.add("cases", None, "Case library", f"/suts/{row['sut_id']}/cases")
        self.add("case", row["id"], f"{row['title']} ({row['code']})", f"/cases/{row['id']}")
        return row


def context(db, kind: str, id_) -> dict:
    if kind not in KINDS:
        raise AppError("VALIDATION", f"Unknown object type {kind}")
    with db.tx() as cur:
        chain = _Chain(cur)
        if kind == "sut":
            chain.add_sut(id_)
        elif kind == "version":
            chain.add_version(id_)
        elif kind == "requirement":
            row = _one(cur, "SELECT id, version_id, code, title FROM requirement WHERE id=%s", (id_,))
            chain.add_version(row["version_id"])
            chain.add(
                "requirement",
                row["id"],
                f"{row['title']} ({row['code']})",
                f"/versions/{row['version_id']}?req={row['id']}",
            )
        elif kind == "task":
            chain.add_task(id_)
        elif kind == "run":
            chain.add_run(id_)
        elif kind == "case":
            chain.add_case(id_)
        elif kind == "execution":
            row = _one(cur, "SELECT id, task_run_id, case_id FROM case_execution WHERE id=%s", (id_,))
            if row["task_run_id"]:
                chain.add_run(row["task_run_id"])
                case = _one(cur, "SELECT code, title FROM test_case WHERE id=%s", (row["case_id"],))
            else:
                case = chain.add_case(row["case_id"])
            chain.add(
                "execution",
                row["id"],
                f"{case['title']} ({case['code']}) execution",
                f"/executions/{row['id']}",
            )
        elif kind == "defect":
            row = _one(cur, "SELECT id, sut_id, version_id, code, title FROM defect WHERE id=%s", (id_,))
            if row["version_id"]:
                chain.add_version(row["version_id"])
                path = f"/defects?sut_id={row['sut_id']}&version_id={row['version_id']}"
            else:
                chain.add_sut(row["sut_id"])
                path = f"/defects?sut_id={row['sut_id']}"
            chain.add("defects", None, "Defect", path)
            chain.add("defect", row["id"], f"{row['title']} ({row['code']})", f"/defects/{row['id']}")
        else:  # report
            row = _one(cur, "SELECT id, scope_type, scope_id FROM report WHERE id=%s", (id_,))
            if row["scope_type"] == "version":
                chain.add_version(row["scope_id"])
                label = "Version report"
            else:
                chain.add_run(row["scope_id"])
                label = "Task report"
            chain.add("report", row["id"], label, f"/reports/{row['id']}")
        return {"sut": chain.sut, "version": chain.version, "crumbs": chain.items}


# ------------------------------------------------------------------ main-flow progress
STEP_TITLES = {
    "sut": "SUT",
    "model": "Model",
    "requirements": "Requirements",
    "strategy": "Strategy",
    "tasks": "Tasks",
    "cases": "Cases",
    "runs": "Runs",
    "results": "Results",
}
RUN_TEXT = {
    "queued": "Queued",
    "running": "Running",
    "passed": "Passed",
    "failed": "failed",
    "error": "Error",
    "cancelled": "Cancelled",
}


def _count(cur, sql: str, args) -> int:
    cur.execute(sql, args)
    return int(cur.fetchone()["n"])


def _pick_version(cur, sut_id, version_id) -> dict | None:
    if version_id:
        cur.execute("SELECT id, name, status FROM version WHERE id=%s AND sut_id=%s", (version_id, sut_id))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Version not found")
        return row
    cur.execute(
        "SELECT id, name, status FROM version WHERE sut_id=%s ORDER BY (status='closed'), created_at DESC LIMIT 1",
        (sut_id,),
    )
    return cur.fetchone()


def progress(db, sut_id, version_id=None, repos_root=None) -> dict:
    with db.tx() as cur:
        sut = _one(cur, "SELECT id, code, name, description FROM sut WHERE id=%s", (sut_id,))
        cur.execute(
            "SELECT id, name, status FROM version WHERE sut_id=%s ORDER BY created_at DESC",
            (sut_id,),
        )
        versions = [{**r, "id": str(r["id"])} for r in cur.fetchall()]
        version = _pick_version(cur, sut_id, version_id)
        steps: list[dict] = []

        def step(key, status, summary, path, action=None):
            steps.append(
                {
                    "key": key,
                    "title": STEP_TITLES[key],
                    "status": status,
                    "summary": summary,
                    "path": path,
                    "action": action,
                }
            )

        base = f"/suts/{sut_id}"
        envs = _count(cur, "SELECT count(*) AS n FROM environment WHERE sut_id=%s", (sut_id,))
        step(
            "sut",
            "done" if envs else "todo",
            f"Environment {envs} " if envs else "No environment yet (the SUT's address)",
            base,
            None if envs else {"label": "Add environment", "path": base},
        )

        cur.execute(
            "SELECT count(*) FILTER (WHERE kind='entity') AS entities,"
            " count(*) FILTER (WHERE kind='action') AS actions"
            " FROM model_node WHERE sut_id=%s AND deleted_at IS NULL",
            (sut_id,),
        )
        nodes = cur.fetchone()
        links = _count(
            cur,
            "SELECT count(*) AS n FROM model_link WHERE sut_id=%s AND deleted_at IS NULL",
            (sut_id,),
        )
        pending = _count(
            cur,
            "SELECT count(*) AS n FROM model_suggestion WHERE sut_id=%s AND status='pending'",
            (sut_id,),
        )
        model_done = nodes["entities"] > 0 and nodes["actions"] > 0
        summary = f"entities {nodes['entities']} · actions {nodes['actions']} · links {links}"
        if pending:
            summary += f" · pending suggestions {pending}"
        step(
            "model",
            "done" if model_done else ("doing" if nodes["entities"] or nodes["actions"] else "todo"),
            summary,
            f"{base}/model",
            None if model_done else {"label": "Build the model (entities, actions, links)", "path": f"{base}/model"},
        )

        vpath = f"/versions/{version['id']}" if version else f"{base}/versions"
        if version is None:
            step(
                "requirements",
                "todo",
                "No version yet",
                vpath,
                {"label": "New version", "path": vpath},
            )
            for key in ("strategy", "tasks", "cases", "runs", "results"):
                step(key, "todo", "Create a version first", vpath)
        else:
            vid = version["id"]
            cur.execute(
                "SELECT count(*) AS total, count(*) FILTER (WHERE status='confirmed') AS confirmed"
                " FROM requirement WHERE version_id=%s",
                (vid,),
            )
            reqs = cur.fetchone()
            frozen = version["status"] != "planning"
            if frozen:
                st, action = "done", None
            elif not reqs["total"]:
                st, action = "todo", {"label": "Add requirement", "path": vpath}
            elif reqs["confirmed"] < reqs["total"]:
                st, action = "doing", {"label": "Confirm requirements", "path": vpath}
            else:
                st, action = "doing", {"label": "Freeze requirements", "path": vpath}
            step(
                "requirements",
                st,
                f"Version {version['name']} · requirements {reqs['total']} (confirmed {reqs['confirmed']})"
                + (" · frozen" if frozen else ""),
                vpath,
                action,
            )

            spath = f"{vpath}?tab=strategy"
            cur.execute("SELECT status FROM test_strategy WHERE version_id=%s", (vid,))
            strategy = cur.fetchone()
            if strategy and strategy["status"] == "confirmed":
                step("strategy", "done", "Confirmed", spath)
            else:
                step(
                    "strategy",
                    "doing" if strategy else "todo",
                    "Draft, to be confirmed" if strategy else "No test strategy yet",
                    spath,
                    {"label": "Confirm test strategy" if strategy else "Create test strategy", "path": spath},
                )

            cur.execute(
                "SELECT count(*) AS n, count(*) FILTER (WHERE status IN ('ready','running','done'))"
                " AS ready FROM test_task WHERE version_id=%s AND status<>'archived'",
                (vid,),
            )
            tasks = cur.fetchone()
            step(
                "tasks",
                "done" if tasks["ready"] else ("doing" if tasks["n"] else "todo"),
                f"Task {tasks['n']} (ready/run {tasks['ready']})",
                spath,
                None if tasks["ready"] else {"label": "Set ready" if tasks["n"] else "New task", "path": spath},
            )

            cpath = f"{vpath}?tab=cases"
            cur.execute(
                "SELECT count(*) AS n, count(*) FILTER (WHERE c.status='ready') AS ready,"
                " count(*) FILTER (WHERE c.code_path IS NOT NULL) AS automated"
                " FROM test_case c WHERE c.status<>'deprecated' AND (c.origin_version_id=%(v)s"
                " OR EXISTS (SELECT 1 FROM case_requirement_link l JOIN requirement r"
                "  ON r.id=l.requirement_id WHERE l.case_id=c.id AND r.version_id=%(v)s))",
                {"v": vid},
            )
            cases = cur.fetchone()
            step(
                "cases",
                "done" if cases["ready"] else ("doing" if cases["n"] else "todo"),
                f"Case {cases['n']} (ready {cases['ready']}, automated {cases['automated']})",
                cpath,
                None
                if cases["ready"]
                else {"label": "Review and set ready" if cases["n"] else "Generate cases", "path": cpath},
            )

            cur.execute(
                "SELECT r.id, r.status, r.created_at, count(*) OVER () AS n FROM task_run r"
                " JOIN test_task t ON t.id=r.task_id WHERE t.version_id=%s"
                " ORDER BY r.created_at DESC LIMIT 1",
                (vid,),
            )
            last = cur.fetchone()
            if last:
                step(
                    "runs",
                    "done" if last["status"] not in ("queued", "running") else "doing",
                    f"Execution {last['n']} time(s), latest{RUN_TEXT.get(last['status'], last['status'])}",
                    f"/runs/{last['id']}",
                )
            else:
                step("runs", "todo", "Not run yet", spath, {"label": "Run task", "path": spath})

            cur.execute(
                "SELECT count(*) AS n, count(*) FILTER (WHERE status IN ('open','in_progress'))"
                " AS open FROM defect WHERE version_id=%s",
                (vid,),
            )
            defects = cur.fetchone()
            reports = _count(
                cur,
                "SELECT count(*) AS n FROM report r LEFT JOIN task_run tr"
                " ON r.scope_type='task_run' AND tr.id=r.scope_id LEFT JOIN test_task t"
                " ON t.id=tr.task_id WHERE COALESCE(t.version_id,"
                " CASE WHEN r.scope_type='version' THEN r.scope_id END)=%s",
                (vid,),
            )
            rpath = f"/reports?sut_id={sut_id}&version_id={vid}"
            step(
                "results",
                "done" if reports and not defects["open"] else ("doing" if reports else "todo"),
                f"Defect {defects['n']} (open {defects['open']}) · reports {reports}",
                f"/defects?sut_id={sut_id}&version_id={vid}" if defects["open"] else rpath,
                {"label": "Handle defects", "path": f"/defects?sut_id={sut_id}&version_id={vid}"}
                if defects["open"]
                else None,
            )

        nxt = next((s for s in steps if s["status"] != "done"), None)
        repo_path = None
        if repos_root is not None:
            from testagent.integrations.git_repo import TestRepo

            repo_path = str(TestRepo(repos_root, sut["code"]).path.resolve())
        return {
            "sut": {"id": str(sut["id"]), "code": sut["code"], "name": sut["name"]},
            "version": {**version, "id": str(version["id"])} if version else None,
            "versions": versions,
            "steps": steps,
            "next": {
                "key": nxt["key"],
                "title": nxt["title"],
                "label": (nxt["action"] or {}).get("label") or f"Next: {nxt['title']}",
                "path": (nxt["action"] or {}).get("path") or nxt["path"],
            }
            if nxt
            else None,
            "repo_path": repo_path,
        }
