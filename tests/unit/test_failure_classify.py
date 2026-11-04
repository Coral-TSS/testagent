"""Batch 2: deterministic failure kinds, suspected causes and readable summaries."""

import pytest

from testagent.services.failure_classify import cause_of, classify, kind_of

ASSERT_REPORT = {
    "tests": [
        {
            "failure": {
                "type": "AssertionError",
                "kind": "assertion",
                "explain": "state: expected equals 'pending', got 'approved'",
                "expected": "'pending'",
                "actual": "'approved'",
                "check": "state is pending approval",
                "step": "Step 2: submit at the threshold",
            }
        }
    ]
}


@pytest.mark.parametrize(
    ("status", "kw", "kind"),
    [
        ("passed", {}, None),
        ("blocked", {}, None),
        ("skipped", {}, "non_functional"),
        ("skipped", {"forced": "no_script"}, "no_script"),
        ("error", {"error": "ENV_UNREACHABLE: the system is not running"}, "env_unreachable"),
        ("error", {"error": "NO_ENVIRONMENT: the task has no execution environment"}, "platform"),
        ("error", {"error": "CONFIG_MISSING: Test repo directory is not configured"}, "platform"),
        ("error", {"error": "MODEL_UNAVAILABLE: no model"}, "platform"),
        ("error", {"error": "NOT_FOUND: does not exist in the test repo tests/x.py"}, "platform"),
        ("error", {"error": "TIMEOUT: pytest exceeded 300s and was killed"}, "timeout"),
        ("failed", {"report": ASSERT_REPORT, "executor": "pytest"}, "assertion"),
        ("error", {"report": {"tests": [{"failure": {"type": "TimeoutError", "kind": "locator"}}]}}, "locator"),
        ("error", {"report": {"tests": [{"failure": {"type": "KeyError", "kind": "script_error"}}]}}, "script_error"),
        ("error", {"error": "no tests collected", "executor": "pytest"}, "script_error"),
        ("failed", {"executor": "agent_browser"}, "assertion"),
        ("error", {"error": "MAX_STEPS: budget", "executor": "agent_api"}, "agent_error"),
        ("error", {"error": "RuntimeError: boom"}, "unknown"),
    ],
)
def test_kind_mapping(status, kw, kind):
    assert kind_of(status, **kw) == kind


@pytest.mark.parametrize(
    ("kind", "cause"),
    [
        ("script_error", "script"),
        ("locator", "script"),
        ("timeout", "unknown"),
        ("http_error", "sut"),
        ("env_unreachable", "environment"),
        ("platform", "platform"),
        ("no_script", "platform"),
        ("agent_error", "platform"),
        ("non_functional", None),
        (None, None),
    ],
)
def test_default_causes(kind, cause):
    assert cause_of(kind) == cause


CASE = {
    "title": "Amount equal to the threshold needs approval",
    "expected": "State is pending",
    "steps": [{"action": "Create an order at the threshold", "expected": "state = pending"}],
}
REQS = [
    {"id": "r1", "code": "REQ-003", "title": "Approval threshold", "raw_text": "amount >= threshold needs approval"}
]


def test_self_check_verdicts():
    sut = {"verdict": "sut_mismatch", "expected": "'pending'", "actual": "'approved'"}
    assert cause_of("assertion", phase="self_check", verdict=sut, case=CASE, requirements=REQS) == "sut"
    # the expected value has no backing in the case or a requirement: stays unknown
    made_up = {**sut, "expected": "'escalated'"}
    assert cause_of("assertion", phase="self_check", verdict=made_up, case=CASE, requirements=REQS) == "unknown"
    by_req = {**made_up, "requirement_code": "REQ-003"}
    assert cause_of("assertion", phase="self_check", verdict=by_req, case=CASE, requirements=REQS) == "sut"
    script = {"verdict": "script_issue"}
    assert cause_of("assertion", phase="self_check", verdict=script, case=CASE) == "script"
    assert cause_of("assertion", phase="self_check", verdict=None, case=CASE) == "unknown"
    assert cause_of("assertion", phase="self_check", verdict={"verdict": "unclear"}) == "unknown"


def test_run_phase_assertions():
    assert cause_of("assertion", executor="pytest", code_commit="a", bound_commit="a") == "sut"
    assert cause_of("assertion", executor="pytest", code_commit=None, bound_commit="a") == "unknown"
    assert cause_of("assertion", executor="agent_browser") == "sut"
    assert cause_of("assertion", executor="manual") == "sut"


def test_summary_is_readable():
    out = classify(
        "failed",
        report=ASSERT_REPORT,
        executor="pytest",
        code_commit="a",
        bound_commit="a",
        requirements=REQS,
        failed_assertion="tests/x.py::test_a: assert 'approved' == 'pending'",
    )
    assert out["failure_kind"] == "assertion" and out["suspected_cause"] == "sut"
    s = out["summary"]
    assert s["headline"] == "state is pending approval: expected 'pending', got 'approved'"
    assert (s["expected"], s["actual"]) == ("'pending'", "'approved'")
    assert s["step"] == "Step 2: submit at the threshold"
    assert s["requirement_refs"][0]["code"] == "REQ-003"
    assert "create_defect" in s["next_actions"]


def test_summary_for_not_executed_and_platform():
    out = classify("skipped", forced="no_script", reason="no script yet")
    assert out["failure_kind"] == "no_script" and out["suspected_cause"] == "platform"
    assert out["summary"]["headline"] == "no script yet"
    platform = classify("error", error="NO_ENVIRONMENT: the task has no execution environment")
    assert platform["summary"]["headline"].startswith("Platform or configuration problem")
    assert platform["summary"]["next_actions"] == ["fix_config"]
    assert classify("passed") == {"failure_kind": None, "suspected_cause": None, "summary": None}


def test_agent_verdict_note_and_rule():
    verdict = {
        "verdict": "sut_mismatch",
        "expected": "'pending'",
        "actual": "'approved'",
        "requirement_code": "REQ-003",
        "rule": "amount >= threshold needs approval",
        "explanation": "The system approves at the threshold; the assertion follows the requirement.",
    }
    out = classify("failed", phase="self_check", verdict=verdict, case=CASE, requirements=REQS, executor="pytest")
    s = out["summary"]
    assert out["suspected_cause"] == "sut"
    assert s["requirement_refs"][0]["rule"] == "amount >= threshold needs approval"
    assert s["agent_note"].startswith("The system approves")
    assert s["headline"] == "Expected 'pending', got 'approved'"


def test_run_outcome():
    from testagent.services.runs import run_outcome

    def ex(status, kind=None):
        return {"status": status, "failure_kind": kind}

    no_script = ex("skipped", "no_script")
    assert run_outcome([no_script, no_script]) == "not_executed"
    assert run_outcome([no_script, ex("passed")]) == "passed"
    assert run_outcome([no_script, ex("failed", "assertion")]) == "failed"
    assert run_outcome([no_script, ex("error", "platform")]) == "failed"
    # other skips / awaiting manual keep the old behaviour
    assert run_outcome([no_script, ex("skipped", "non_functional")]) == "passed"
    assert run_outcome([no_script, ex("blocked")]) == "passed"
    assert run_outcome([]) == "passed"
