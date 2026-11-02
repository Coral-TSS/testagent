"""M1-11: defect statistics (requirement density, people ranking), reports (immutable)."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from tests.api.world import (
    V1,
    FakeRunner,
    build_world,
    install_runner,
    make_case,
    make_task,
    run_task,
)

from testagent.agent.fake import FakeChatModel, call
from testagent.core.errors import AppError
from testagent.services.stats import DEFAULT_WEIGHTS


@pytest.fixture(autouse=True)
def restore_weights(db):
    yield
    with db.tx() as cur:  # severity_weight survives the per-test TRUNCATE
        for severity, weight in DEFAULT_WEIGHTS.items():
            cur.execute("UPDATE severity_weight SET weight=%s WHERE severity=%s", (weight, severity))


def execute(client, case, status):
    resp = client.post(f"{V1}/cases/{case}/executions/manual", json={"status": status})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def defect(client, w, title, severity, reqs, cause):
    resp = client.post(
        f"{V1}/defects",
        json={
            "sut_id": w["sut"],
            "version_id": w["version"],
            "title": title,
            "severity": severity,
            "requirement_ids": [w["reqs"][r] for r in reqs],
            "cause_category": cause,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def s(client, db):
    """REQ-001: cases A, B, C(+REQ-002), D. Executions A pass (twice), B fail, C fail, D skipped.
    Defects: d1 critical development REQ-001; d2 minor design REQ-001+REQ-002;
    d3 major development REQ-001 rejected."""
    w = build_world(client, db)
    a = make_case(client, w, "A")
    b = make_case(client, w, "B")
    c = make_case(client, w, "C", req_codes=("REQ-001", "REQ-002"))
    d = make_case(client, w, "D")
    execute(client, a, "passed")
    execute(client, a, "passed")
    execute(client, b, "failed")
    execute(client, c, "failed")
    execute(client, d, "skipped")
    w["d1"] = defect(client, w, "Missing amount validation", "critical", ["REQ-001"], "development")
    w["d2"] = defect(client, w, "Ambiguous flow description", "minor", ["REQ-001", "REQ-002"], "design")
    w["d3"] = defect(client, w, "False positive", "major", ["REQ-001"], "development")
    client.post(f"{V1}/defects/{w['d3']}/status", json={"status": "rejected"})
    w["cases"] = {"A": a, "B": b, "C": c, "D": d}
    return w


def by_code(rows):
    return {r["code"]: r for r in rows}


def by_name(rows):
    return {r["name"]: r for r in rows}


# ------------------------------------------------------------------ T-11.1 / T-11.2
def test_requirement_count_weighted_density(client, s):
    rows = by_code(client.get(f"{V1}/stats/requirements", params={"version_id": s["version"]}).json())
    r1, r2 = rows["REQ-001"], rows["REQ-002"]
    assert (r1["defect_count"], r1["weighted_score"], r1["executed_cases"]) == (2, 11.0, 3)
    assert r1["density"] == pytest.approx(2 / 3)
    assert r1["by_severity"] == {"critical": 1, "minor": 1}
    assert (r2["defect_count"], r2["weighted_score"], r2["executed_cases"], r2["density"]) == (
        1,
        1.0,
        1,
        1.0,
    )
    assert r1["owner"] == ["Pat Product"] and r1["developers"] == ["Lee Dev"]


def test_person_attributed_vs_related(client, s):
    people = by_name(client.get(f"{V1}/stats/people", params={"version_id": s["version"]}).json())
    li, wang, zhao, qian = (people[n] for n in ("Lee Dev", "Pat Product", "Zhao Dev", "Quinn Tester"))
    assert (li["attributed_count"], li["attributed_score"], li["related_count"]) == (1, 10.0, 2)
    assert (wang["attributed_count"], wang["attributed_score"], wang["related_count"]) == (
        1,
        1.0,
        2,
    )
    assert (zhao["attributed_count"], zhao["related_count"]) == (0, 1)
    assert (qian["attributed_count"], qian["related_count"]) == (0, 2)
    assert li["requirements"] == [{"code": "REQ-001", "title": "Requirement1", "count": 1}]


def test_by_role_breakdown(client, s):
    qian = s["people"]["Quinn Tester"]
    client.put(
        f"{V1}/defects/{s['d1']}/responsible",
        json=[
            {"person_id": s["people"]["Lee Dev"], "role": "developer"},
            {"person_id": qian, "role": "developer"},
        ],
    )
    defect(client, s, "Wrong case", "major", ["REQ-002"], "test")  # → Quinn Tester as tester
    people = by_name(client.get(f"{V1}/stats/people", params={"version_id": s["version"]}).json())
    q = people["Quinn Tester"]
    assert q["attributed_count"] == 2 and q["attributed_score"] == 13.0
    assert q["attributed_by_role"] == {
        "developer": {"count": 1, "score": 10.0},
        "tester": {"count": 1, "score": 3.0},
    }


def test_rejected_excluded(client, s):
    client.post(f"{V1}/defects/{s['d1']}/status", json={"status": "rejected"})
    rows = by_code(client.get(f"{V1}/stats/requirements", params={"version_id": s["version"]}).json())
    assert rows["REQ-001"]["defect_count"] == 1 and rows["REQ-001"]["weighted_score"] == 1.0
    people = by_name(client.get(f"{V1}/stats/people", params={"version_id": s["version"]}).json())
    assert people["Lee Dev"]["attributed_count"] == 0 and people["Lee Dev"]["related_count"] == 1


def test_weights_change_affects_new_stats_only(client, s):
    old = client.post(f"{V1}/versions/{s['version']}/report").json()
    assert old["weights_used"]["critical"] == 10
    resp = client.put(
        f"{V1}/settings/severity-weights",
        json={"critical": 20, "major": 3, "minor": 1, "trivial": 0.1},
    )
    assert resp.status_code == 200 and resp.json()["critical"] == 20
    people = by_name(client.get(f"{V1}/stats/people", params={"version_id": s["version"]}).json())
    assert people["Lee Dev"]["attributed_score"] == 20.0
    again = client.get(f"{V1}/reports/{old['id']}").json()
    assert again["weights_used"]["critical"] == 10
    li_old = by_name(again["content"]["by_person"])["Lee Dev"]
    assert li_old["attributed_score"] == 10.0
    new = client.post(f"{V1}/versions/{s['version']}/report").json()
    assert by_name(new["content"]["by_person"])["Lee Dev"]["attributed_score"] == 20.0


def test_weights_validation(client):
    bad = client.put(
        f"{V1}/settings/severity-weights",
        json={"critical": -1, "major": 3, "minor": 1, "trivial": 0.1},
    )
    assert bad.status_code == 422
    assert client.get(f"{V1}/settings/severity-weights").json() == DEFAULT_WEIGHTS


def test_people_ranking_sorted_by_score(client, s):
    url = f"{V1}/stats/people"
    ranked = client.get(url, params={"version_id": s["version"]}).json()
    assert [p["name"] for p in ranked][:2] == ["Lee Dev", "Pat Product"]
    by_related = client.get(url, params={"version_id": s["version"], "sort": "related_count"}).json()
    assert [p["related_count"] for p in by_related] == sorted((p["related_count"] for p in by_related), reverse=True)
    assert client.get(url, params={"sort": "name; drop table x"}).status_code == 422


def test_stats_time_filter(client, s, db):
    with db.tx() as cur:
        cur.execute(
            "UPDATE defect SET created_at=%s WHERE id=%s",
            (datetime.now(UTC) - timedelta(days=30), s["d1"]),
        )
    since = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    people = by_name(client.get(f"{V1}/stats/people", params={"from": since}).json())
    assert "Lee Dev" not in people or people["Lee Dev"]["attributed_count"] == 0
    assert people["Pat Product"]["attributed_count"] == 1


# ------------------------------------------------------------------ T-11.3 .. T-11.5
def test_report_metrics_match_executions(client, db):
    w = build_world(client, db)
    ids = [make_case(client, w, t) for t in ("Passed", "failed", "Crash")]
    ids.append(make_case(client, w, "Performance", type_tag="performance"))
    ids.append(make_case(client, w, "Draft", status="draft"))
    install_runner(client, FakeRunner({"failed": "failed", "Crash": "crash"}))
    run = run_task(client, make_task(client, w, ids))
    assert run["report_id"], "report is generated when the run finishes"
    report = client.get(f"{V1}/reports/{run['report_id']}").json()
    assert report["scope_type"] == "task_run" and report["scope_id"] == run["id"]
    assert report["content"]["summary"] == {
        "total": 5,
        "passed": 1,
        "failed": 1,
        "error": 1,
        "blocked": 0,
        "skipped": 1,
        "not_executed": 1,
        "executed": 3,
        "pass_rate": pytest.approx(1 / 3),
    }
    failures = report["content"]["failures"]
    assert [(f["case"]["title"], f["status"]) for f in failures] == [
        ("failed", "failed"),
        ("Crash", "error"),
    ]
    assert failures[0]["requirement_codes"] == ["REQ-001"] and failures[0]["execution_id"]
    assert report["ai_summary"] is None  # no model configured (T-11.4)
    assert report["content"]["snapshot_id"] and report["content"]["generated_at"]


def test_report_by_requirement_and_person(client, db):
    w = build_world(client, db)
    ok = make_case(client, w, "Passed")
    bad = make_case(client, w, "failed")
    install_runner(client, FakeRunner({"failed": "failed"}))
    run = run_task(client, make_task(client, w, [ok, bad]))
    failed = [e for e in run["executions"] if e["status"] == "failed"][0]
    d = client.post(
        f"{V1}/executions/{failed['id']}/defect",
        json={"severity": "critical", "cause_category": "development"},
    ).json()
    report = client.post(f"{V1}/runs/{run['id']}/report").json()
    assert report["id"] != run["report_id"]  # a new immutable report
    req = by_code(report["content"]["by_requirement"])["REQ-001"]
    assert (req["defect_count"], req["weighted_score"], req["executed_cases"]) == (1, 10.0, 2)
    assert req["density"] == 0.5 and req["developers"] == ["Lee Dev"]
    li = by_name(report["content"]["by_person"])["Lee Dev"]
    assert (li["attributed_count"], li["attributed_score"]) == (1, 10.0)
    assert li["top_requirements"] == ["REQ-001"]
    assert report["content"]["failures"][0]["defect_ids"] == [d["id"]]
    assert [x["code"] for x in report["content"]["defects"]] == ["DEF-001"]
    listed = client.get(f"{V1}/reports", params={"scope_id": run["id"]}).json()
    assert len(listed) == 2


def test_report_code_links_via_nodes(client, db):
    w = build_world(client, db)
    node = client.post(
        f"{V1}/suts/{w['sut']}/nodes",
        json={"kind": "action", "name": "Submit purchase order", "code_ref": "svc/order.py:submit"},
    ).json()["id"]
    api = client.post(
        f"{V1}/suts/{w['sut']}/apis",
        json={"method": "POST", "path": "/orders", "code_ref": "api/orders.py:42"},
    ).json()["id"]
    client.put(f"{V1}/nodes/{node}/apis", json={"api_ids": [api]})
    with db.tx() as cur:
        cur.execute(
            "INSERT INTO requirement_node_link(requirement_id, node_id, role) VALUES (%s,%s,'action')",
            (w["reqs"]["REQ-001"], node),
        )
    report = client.post(f"{V1}/versions/{w['version']}/report").json()
    links = {x["requirement_code"]: x for x in report["content"]["code_links"]}
    assert links["REQ-001"]["apis"] == [{"method": "POST", "path": "/orders", "code_ref": "api/orders.py:42"}]
    assert links["REQ-001"]["nodes"] == [{"name": "Submit purchase order", "code_ref": "svc/order.py:submit"}]
    assert links["REQ-002"]["apis"] == []


def test_report_immutable(client, db):
    w = build_world(client, db)
    report = client.post(f"{V1}/versions/{w['version']}/report").json()
    with pytest.raises((AppError, psycopg.Error)):
        with db.tx() as cur:
            cur.execute("UPDATE report SET ai_summary='x' WHERE id=%s", (report["id"],))
    with pytest.raises((AppError, psycopg.Error)):
        with db.tx() as cur:
            cur.execute("DELETE FROM report WHERE id=%s", (report["id"],))
    assert client.patch(f"{V1}/reports/{report['id']}", json={}).status_code in (404, 405)
    assert client.get(f"{V1}/reports/{report['id']}").json()["content"] == report["content"]


def test_report_without_model_still_generated(client, db):
    w = build_world(client, db)
    plain = client.post(f"{V1}/versions/{w['version']}/report")
    assert plain.status_code == 201 and plain.json()["ai_summary"] is None
    fake = FakeChatModel(
        script=[call("submit_result", {"summary": "No cases executed in this version, no defects yet."})]
    )
    client.app.state.agent.models.builder = lambda cfg: fake
    with_ai = client.post(f"{V1}/versions/{w['version']}/report").json()
    assert with_ai["ai_summary"] == "No cases executed in this version, no defects yet."
    assert with_ai["agent_run_id"]


def test_version_report_uses_latest_execution_per_case(client, db):
    w = build_world(client, db)
    a = make_case(client, w, "fail then pass")
    b = make_case(client, w, "pass then fail")
    make_case(client, w, "Not run")
    execute(client, a, "failed")
    execute(client, b, "passed")
    execute(client, a, "passed")
    execute(client, b, "failed")
    report = client.post(f"{V1}/versions/{w['version']}/report").json()
    summary = report["content"]["summary"]
    assert (summary["total"], summary["passed"], summary["failed"], summary["not_executed"]) == (
        3,
        1,
        1,
        1,
    )
    assert [f["case"]["title"] for f in report["content"]["failures"]] == ["pass then fail"]
    assert report["scope_type"] == "version"


def test_sql_views_match_service(client, s, db):
    api_reqs = by_code(client.get(f"{V1}/stats/requirements", params={"version_id": s["version"]}).json())
    api_people = client.get(f"{V1}/stats/people", params={"version_id": s["version"]}).json()
    with db.tx() as cur:
        cur.execute(
            "SELECT r.code, v.defect_count, v.weighted_score, v.executed_cases, v.density,"
            " v.by_severity FROM v_defect_by_requirement v JOIN requirement r"
            " ON r.id=v.requirement_id WHERE v.version_id=%s",
            (s["version"],),
        )
        for row in cur.fetchall():
            mine = api_reqs[row["code"]]
            assert row["defect_count"] == mine["defect_count"]
            assert float(row["weighted_score"]) == mine["weighted_score"]
            assert row["executed_cases"] == mine["executed_cases"]
            assert row["by_severity"] == mine["by_severity"]
        cur.execute(
            "SELECT person_id::text AS person_id, attributed_count, attributed_score,"
            " related_count FROM v_defect_by_person WHERE version_id=%s",
            (s["version"],),
        )
        view = {r["person_id"]: r for r in cur.fetchall()}
    assert set(view) == {p["person_id"] for p in api_people}
    for p in api_people:
        v = view[p["person_id"]]
        assert (v["attributed_count"], float(v["attributed_score"]), v["related_count"]) == (
            p["attributed_count"],
            p["attributed_score"],
            p["related_count"],
        )


def test_default_weights_match_spec(client):
    # default weights: critical=10, major=3, minor=1, trivial=0.1
    assert DEFAULT_WEIGHTS == {"critical": 10, "major": 3, "minor": 1, "trivial": 0.1}
    assert client.get(f"{V1}/settings/severity-weights").json() == DEFAULT_WEIGHTS
    assert client.get(f"{V1}/settings/severity-weights/defaults").json() == DEFAULT_WEIGHTS
