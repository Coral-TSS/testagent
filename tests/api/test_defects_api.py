"""M1-10: defects, requirement ownership and responsibility attribution (BR-07, EP-09)."""

import pytest
from tests.api.world import V1, build_world, make_case

from testagent.agent.fake import FakeChatModel, call
from testagent.core.errors import AppError
from testagent.services.defects import DefectService


def use_model(client, *script):
    fake = FakeChatModel(script=list(script))
    client.app.state.agent.models.builder = lambda cfg: fake
    return fake


def failed_execution(client, case_id, assertion="Missing amount validation"):
    resp = client.post(
        f"{V1}/cases/{case_id}/executions/manual",
        json={"status": "failed", "failed_assertion": assertion, "result": "Submitted successfully"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def w(client, db):
    return build_world(client, db)


def defect_from(client, w, req_codes=("REQ-001",), **body):
    case = make_case(client, w, "Amount is 0", req_codes=req_codes)
    ex = failed_execution(client, case)
    resp = client.post(f"{V1}/executions/{ex}/defect", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def people(defect):
    return sorted((r["person_name"], r["role"], r["inferred"]) for r in defect["responsible"])


def test_defect_transitions(client, w):
    d = defect_from(client, w)
    assert d["status"] == "open" and d["code"] == "DEF-001" and d["created_by"] == "human"
    url = f"{V1}/defects/{d['id']}/status"
    assert client.post(url, json={"status": "closed"}).status_code == 409  # open → closed not allowed
    assert client.post(url, json={"status": "in_progress"}).json()["status"] == "in_progress"
    resolved = client.post(url, json={"status": "resolved"}).json()
    assert resolved["status"] == "resolved" and resolved["resolved_at"]
    assert client.post(url, json={"status": "closed"}).json()["status"] == "closed"
    reopened = client.post(url, json={"status": "open"}).json()
    assert reopened["status"] == "open" and reopened["resolved_at"] is None
    assert client.post(url, json={"status": "rejected"}).json()["status"] == "rejected"


def test_defect_requirements_inferred_from_case(client, w, db):
    sut = w["sut"]
    node = client.post(f"{V1}/suts/{sut}/nodes", json={"kind": "action", "name": "Submit purchase order"}).json()["id"]
    api = client.post(
        f"{V1}/suts/{sut}/apis",
        json={"method": "POST", "path": "/orders", "name": "Place order", "code_ref": "orders.py:10"},
    ).json()["id"]
    client.put(f"{V1}/nodes/{node}/apis", json={"api_ids": [api]})
    case = make_case(client, w, "Place order", req_codes=("REQ-001", "REQ-002"), node_ids=[node])
    ex = failed_execution(client, case)
    d = client.post(f"{V1}/executions/{ex}/defect", json={}).json()
    assert sorted((r["code"], r["inferred"]) for r in d["requirements"]) == [
        ("REQ-001", True),
        ("REQ-002", True),
    ]
    assert {(link["target_type"], link["name"]) for link in d["links"]} == {
        ("node", "Submit purchase order"),
        ("api", "POST /orders"),
    }
    assert d["title"].startswith("[TC-001]") and "Missing amount validation" in d["title"]
    assert d["version_id"] == w["version"] and d["execution_id"] == ex and d["case_id"] == case
    assert d["cause_category"] == "unknown" and d["responsible"] == []
    detail = client.get(f"{V1}/executions/{ex}").json()
    assert [x["code"] for x in detail["defects"]] == ["DEF-001"]


def test_defect_from_passed_execution_rejected(client, w):
    case = make_case(client, w, "passed")
    ok = client.post(f"{V1}/cases/{case}/executions/manual", json={"status": "passed"}).json()
    assert client.post(f"{V1}/executions/{ok['id']}/defect", json={}).status_code == 409


def test_edit_defect_requirements_marks_not_inferred(client, w):
    d = defect_from(client, w)
    out = client.put(f"{V1}/defects/{d['id']}/requirements", json={"requirement_ids": [w["reqs"]["REQ-002"]]}).json()
    assert [(r["code"], r["inferred"]) for r in out["requirements"]] == [("REQ-002", False)]


def test_cause_development_attributes_developers(client, w):
    d = defect_from(client, w)
    out = client.patch(f"{V1}/defects/{d['id']}", json={"cause_category": "development"}).json()
    assert people(out) == [("Lee Dev", "developer", True)]


def test_cause_design_attributes_owner(client, w):
    d = defect_from(client, w, cause_category="design")
    assert people(d) == [("Pat Product", "owner", True)]
    tested = client.patch(f"{V1}/defects/{d['id']}", json={"cause_category": "test"}).json()
    assert people(tested) == [("Quinn Tester", "tester", True)]


def test_environment_no_attribution(client, w):
    d = defect_from(client, w, cause_category="development")
    assert people(d) == [("Lee Dev", "developer", True)]
    env = client.patch(f"{V1}/defects/{d['id']}", json={"cause_category": "environment"}).json()
    assert env["responsible"] == []
    unknown = client.patch(f"{V1}/defects/{d['id']}", json={"cause_category": "unknown"}).json()
    assert unknown["responsible"] == []


def test_manual_responsible_not_overwritten(client, w):
    d = defect_from(client, w, cause_category="development")
    manual = client.put(
        f"{V1}/defects/{d['id']}/responsible",
        json=[{"person_id": w["people"]["Zhao Dev"], "role": "developer"}],
    ).json()
    assert people(manual) == [("Zhao Dev", "developer", False)]
    changed = client.patch(f"{V1}/defects/{d['id']}", json={"cause_category": "design"}).json()
    assert people(changed) == [("Zhao Dev", "developer", False)]  # automatic re-inference skipped
    explicit = client.post(f"{V1}/defects/{d['id']}/infer-responsible").json()
    assert people(explicit) == [("Pat Product", "owner", True), ("Zhao Dev", "developer", False)]


def test_reinfer_on_requirement_change(client, w):
    d = defect_from(client, w, cause_category="development")
    assert people(d) == [("Lee Dev", "developer", True)]
    out = client.put(f"{V1}/defects/{d['id']}/requirements", json={"requirement_ids": [w["reqs"]["REQ-002"]]}).json()
    assert people(out) == [("Zhao Dev", "developer", True)]


def test_multi_requirement_union_of_people(client, w):
    d = defect_from(client, w, req_codes=("REQ-001", "REQ-002"), cause_category="development")
    assert people(d) == [("Lee Dev", "developer", True), ("Zhao Dev", "developer", True)]
    owner = client.patch(f"{V1}/defects/{d['id']}", json={"cause_category": "requirement"}).json()
    assert people(owner) == [("Pat Product", "owner", True)]  # same person on both requirements: once


def test_inactive_person_not_attributed(client, w):
    client.patch(f"{V1}/persons/{w['people']['Lee Dev']}", json={"active": False})
    d = defect_from(client, w, cause_category="development")
    assert d["responsible"] == []


def test_defect_list_filters(client, w):
    a = defect_from(client, w, cause_category="development", severity="critical")
    defect_from(client, w, req_codes=("REQ-002",))
    rows = client.get(f"{V1}/defects", params={"version_id": w["version"]}).json()
    assert [r["code"] for r in rows] == ["DEF-002", "DEF-001"]
    assert rows[1]["requirement_codes"] == ["REQ-001"] and rows[1]["responsible_names"] == ["Lee Dev"]
    by_person = client.get(f"{V1}/defects", params={"person_id": w["people"]["Lee Dev"]}).json()
    assert [r["id"] for r in by_person] == [a["id"]]
    by_req = client.get(f"{V1}/defects", params={"requirement_id": w["reqs"]["REQ-002"]}).json()
    assert [r["code"] for r in by_req] == ["DEF-002"]
    crit = client.get(f"{V1}/defects", params={"severity": "critical", "q": "Amount"}).json()
    assert [r["code"] for r in crit] == ["DEF-001"]


def test_manual_defect_without_execution(client, w):
    resp = client.post(
        f"{V1}/defects",
        json={
            "sut_id": w["sut"],
            "version_id": w["version"],
            "title": "Export garbled",
            "severity": "minor",
            "requirement_ids": [w["reqs"]["REQ-002"]],
            "cause_category": "development",
        },
    )
    assert resp.status_code == 201, resp.text
    d = resp.json()
    assert [(r["code"], r["inferred"]) for r in d["requirements"]] == [("REQ-002", False)]
    assert people(d) == [("Zhao Dev", "developer", True)]


# ------------------------------------------------------------------ analyze_failure (T-10.4)
def analysis(cause, product=True):
    return call(
        "submit_result",
        {
            "suggested_cause": cause,
            "is_product_issue": product,
            "analysis": "Backend does not validate amount 0 and the frontend shows no message",
            "defect": {
                "title": "Amount 0 can be submitted",
                "description": "Repro: enter amount 0",
                "severity": "major",
            },
        },
    )


def test_agent_defect_has_suggestion_not_final_cause(client, w):
    case = make_case(client, w, "Amount is 0")
    ex = failed_execution(client, case)
    use_model(client, analysis("development"))
    out = client.post(f"{V1}/executions/{ex}/analyze").json()
    assert out["status"] == "succeeded" and out["suggested_cause"] == "development"
    d = client.get(f"{V1}/defects/{out['defect']['id']}").json()
    assert d["created_by"] == "agent" and d["agent_run_id"] == out["agent_run_id"]
    assert d["cause_category"] == "unknown" and d["suggested_cause"] == "development"
    assert d["responsible"] == [] and "does not validate" in d["analysis"]
    assert [r["code"] for r in d["requirements"]] == ["REQ-001"]
    accepted = client.post(f"{V1}/defects/{d['id']}/accept-suggestion").json()
    assert accepted["cause_category"] == "development"
    assert people(accepted) == [("Lee Dev", "developer", True)]
    agent = DefectService(client.app.state.db, client.app.state.bus, actor=f"agent:{out['agent_run_id']}")
    with pytest.raises(AppError):
        agent.update(d["id"], {"cause_category": "design"})


def test_non_product_cause_no_defect(client, w):
    case = make_case(client, w, "Amount is 0")
    ex = failed_execution(client, case)
    use_model(client, analysis("environment", product=False))
    out = client.post(f"{V1}/executions/{ex}/analyze").json()
    assert out["status"] == "succeeded" and out["defect"] is None
    assert out["suggested_cause"] == "environment" and "does not validate" in out["analysis"]
    assert client.get(f"{V1}/defects").json() == []
    # the model saying "product issue" with a non-product cause still creates nothing
    use_model(client, analysis("test", product=True))
    assert client.post(f"{V1}/executions/{ex}/analyze").json()["defect"] is None


def test_analyze_requires_model(client, w):
    ex = failed_execution(client, make_case(client, w, "Amount is 0"))
    assert client.post(f"{V1}/executions/{ex}/analyze").status_code == 503
