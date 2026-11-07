"""List scope must be applied before recent-record limits."""

from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

V1 = "/api/v1"


@pytest.fixture
def scoped(client, db):
    groups = []
    for code in ("FIRST", "OTHER"):
        sut = client.post(f"{V1}/suts", json={"code": code, "name": code}).json()["id"]
        version = client.post(f"{V1}/suts/{sut}/versions", json={"name": "v1"}).json()["id"]
        task = client.post(f"{V1}/versions/{version}/tasks", json={"name": code}).json()["id"]
        groups.append({"sut": sut, "version": version, "task": task})
    return groups


def test_recent_runs_filter_system_before_limit_and_intersect_version(client, db, scoped):
    first, other = scoped
    with db.tx() as cur:
        cur.execute(
            "INSERT INTO task_run(task_id, executor, status, created_at) VALUES (%s,'agent','passed',%s)"
            " RETURNING id::text AS id",
            (first["task"], datetime.now(UTC) - timedelta(days=1)),
        )
        old = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task_run(task_id, executor, status) SELECT %s,'agent','passed' FROM generate_series(1,60)",
            (other["task"],),
        )
    rows = client.get(f"{V1}/runs", params={"sut_id": first["sut"]}).json()
    assert [r["id"] for r in rows] == [old]
    rows = client.get(f"{V1}/runs", params={"sut_id": other["sut"], "version_id": first["version"]}).json()
    assert rows == []
    assert client.get(f"{V1}/runs", params={"version_id": first["version"]}).json()[0]["id"] == old


def test_report_system_filter_handles_version_and_run_reports_before_limit(client, db, scoped):
    first, other = scoped
    content = Jsonb({"summary": {"total": 0}})
    with db.tx() as cur:
        cur.execute(
            "INSERT INTO task_run(task_id, executor, status) VALUES (%s,'agent','passed') RETURNING id",
            (first["task"],),
        )
        run = cur.fetchone()["id"]
        wanted = []
        for kind, scope in (("version", first["version"]), ("task_run", run)):
            cur.execute(
                "INSERT INTO report(scope_type, scope_id, content, weights_used, created_at)"
                " VALUES (%s,%s,%s,'{}'::jsonb,%s) RETURNING id::text AS id",
                (kind, scope, content, datetime.now(UTC) - timedelta(days=1)),
            )
            wanted.append(cur.fetchone()["id"])
        cur.execute(
            "INSERT INTO report(scope_type, scope_id, content, weights_used)"
            " SELECT 'version',%s,%s,'{}'::jsonb FROM generate_series(1,205)",
            (other["version"], content),
        )
    rows = client.get(f"{V1}/reports", params={"sut_id": first["sut"]}).json()
    assert {r["id"] for r in rows} == set(wanted)
    assert {r["scope_type"] for r in rows} == {"version", "task_run"}
    assert client.get(f"{V1}/reports", params={"sut_id": other["sut"], "version_id": first["version"]}).json() == []


@pytest.mark.parametrize("limit", [0, -1])
def test_recent_run_limit_must_be_positive(client, limit):
    assert client.get(f"{V1}/runs", params={"limit": limit}).status_code == 422
