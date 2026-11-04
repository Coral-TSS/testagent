"""Failure classification and readable summaries (batch 2 "result trustworthiness").

Two dimensions, decided by the platform without a model call:

- ``failure_kind``: what happened (assertion, locator, timeout, script_error, http_error,
  env_unreachable, platform, agent_error, no_script, non_functional, unknown);
- ``suspected_cause``: whose problem it most likely is (sut, script, environment, platform,
  unknown). Values line up with the defect cause categories: sut = requirement / design /
  development, script = test.

Assertion failures are the only ambiguous case. During AI automation the agent's structured
verdict is checked against the case and its requirements; in a task run a bound script that
still has the commit it was verified with points at the system; agent executors only count
assertion receipts, so a failed receipt points at the system too. Everything is a suggestion
("suspected"): a person confirms (C01)."""

from __future__ import annotations

import re

KINDS = (
    "assertion",
    "locator",
    "timeout",
    "script_error",
    "http_error",
    "env_unreachable",
    "platform",
    "agent_error",
    "no_script",
    "non_functional",
    "unknown",
)
CAUSES = ("sut", "script", "environment", "platform", "unknown")
DEFAULT_CAUSE = {
    "assertion": "unknown",
    "locator": "script",
    "timeout": "unknown",
    "script_error": "script",
    "http_error": "sut",
    "env_unreachable": "environment",
    "platform": "platform",
    "agent_error": "platform",
    "no_script": "platform",
    "non_functional": None,
    "unknown": "unknown",
}
PLATFORM_CODES = (
    "NO_ENVIRONMENT",
    "CONFIG_MISSING",
    "MODEL_UNAVAILABLE",
    "REPO_DIRTY",
    "NOT_FOUND",
    "VALIDATION",
    "NO_SCRIPT",
)
# Next steps the UI offers, by suspected cause (and kind for the platform ones).
NEXT_ACTIONS = {
    "sut": ["create_defect", "analyse"],
    "script": ["regenerate", "edit_case"],
    "environment": ["check_environment", "rerun"],
    "platform": ["fix_config"],
    "unknown": ["analyse", "rerun"],
}
HEADLINE = {
    "locator": "A page element could not be found",
    "timeout": "The test timed out",
    "script_error": "The test script failed with an error",
    "http_error": "The system returned an error response",
    "env_unreachable": "The system under test could not be reached",
    "platform": "Platform or configuration problem",
    "agent_error": "The agent executor did not finish",
    "no_script": "The case is in an automated task but has no automation script yet; it was not executed",
    "non_functional": "Non-functional case, not executed in this version",
    "unknown": "The execution failed",
}


def _norm(text) -> str:
    return re.sub(r"[\s'\"`“”‘’]+", "", str(text or "")).lower()


def first_failure(report: dict | None) -> dict | None:
    for test in (report or {}).get("tests") or []:
        if test.get("failure"):
            return test["failure"]
    return None


def kind_of(
    status: str,
    *,
    error: str | None = None,
    failed_assertion: str | None = None,
    report: dict | None = None,
    executor: str | None = None,
    forced: str | None = None,
) -> str | None:
    """The failure kind of one execution or self-check; None when it passed / is blocked."""
    if forced in ("no_script", "non_functional"):
        return forced
    if status in ("passed", "blocked", "queued", "running"):
        return None
    if status == "skipped":
        return "non_functional"
    text = error or ""
    code = text.split(":", 1)[0].strip()
    if code == "ENV_UNREACHABLE" or "ECONNREFUSED" in text or "Connection refused" in text:
        return "env_unreachable"
    if code in PLATFORM_CODES:
        return "platform"
    if code == "TIMEOUT":
        return "timeout"
    failure = first_failure(report)
    if failure is not None:
        if failure.get("type") == "AssertionError":
            return "assertion"
        if failure.get("kind") in KINDS:
            return failure["kind"]
    if executor in ("agent_browser", "agent_api"):
        if status == "failed":
            return "assertion"
        return "agent_error"
    if status == "failed":
        return "assertion"
    if "no tests collected" in text or "pytest exited" in text or "SyntaxError" in text or "ImportError" in text:
        return "script_error"
    if executor == "pytest" and status == "error":
        return "script_error"
    return "unknown"


def _verdict_supported(verdict: dict, case: dict | None, requirements: list[dict] | None) -> bool:
    """The agent says the system is wrong: is the expected value backed by the case or one of
    its requirements? Without that evidence it stays unknown."""
    req_codes = {r.get("code") for r in requirements or []}
    if verdict.get("requirement_code") and verdict["requirement_code"] in req_codes:
        return True
    expected = _norm(verdict.get("expected"))
    if not expected or case is None:
        return False
    texts = [case.get("expected"), case.get("title"), case.get("preconditions")]
    for st in case.get("steps") or []:
        texts += [st.get("expected"), st.get("action"), st.get("data")]
    texts += [str(case.get("test_data") or "")]
    texts += [r.get("title") for r in requirements or []] + [r.get("raw_text") for r in requirements or []]
    return any(expected in _norm(t) for t in texts if t)


def cause_of(
    kind: str | None,
    *,
    phase: str = "run",
    executor: str | None = None,
    code_commit: str | None = None,
    bound_commit: str | None = None,
    verdict: dict | None = None,
    case: dict | None = None,
    requirements: list[dict] | None = None,
) -> str | None:
    if kind is None:
        return None
    if kind != "assertion":
        return DEFAULT_CAUSE.get(kind, "unknown")
    if phase == "self_check":
        v = (verdict or {}).get("verdict")
        if v == "sut_mismatch":
            return "sut" if _verdict_supported(verdict, case, requirements) else "unknown"
        if v == "script_issue":
            return "script"
        return "unknown"
    if executor in ("agent_browser", "agent_api", "manual"):
        return "sut"
    if executor == "pytest" and code_commit and bound_commit and code_commit == bound_commit:
        return "sut"
    return "unknown"


def _short(value, limit: int = 300):
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def summarize(
    kind: str | None,
    cause: str | None,
    *,
    error: str | None = None,
    failed_assertion: str | None = None,
    report: dict | None = None,
    verdict: dict | None = None,
    requirements: list[dict] | None = None,
    reason: str | None = None,
) -> dict | None:
    """The readable summary (design §1.3): headline, expected / actual, requirement refs and
    the next actions the UI offers. Raw texts stay in failed_assertion / error."""
    if kind is None:
        return None
    failure = first_failure(report) or {}
    out: dict = {"kind": kind, "cause": cause}
    for key in ("expected", "actual", "subject", "check", "step"):
        if failure.get(key) is not None:
            out[key] = _short(failure[key])
    v = verdict or {}
    if v.get("expected") and "expected" not in out:
        out["expected"] = _short(v["expected"])
    if v.get("actual") and "actual" not in out:
        out["actual"] = _short(v["actual"])
    if kind == "assertion":
        if "expected" in out and "actual" in out:
            what = out.get("check") or out.get("subject")
            headline = f"Expected {out['expected']}, got {out['actual']}"
            if what:
                headline = f"{what}: {headline[0].lower()}{headline[1:]}"
        else:
            headline = failure.get("explain") or _short(
                (failed_assertion or "").splitlines()[0] if failed_assertion else None
            )
            headline = headline or "An expected result was not met"
    elif kind in ("script_error", "locator", "timeout", "http_error", "env_unreachable") and failure.get("explain"):
        headline = failure["explain"]
    elif kind == "platform" and error:
        headline = f"{HEADLINE['platform']}: {_short(error.split(':', 1)[-1].strip(), 200)}"
    else:
        headline = reason or HEADLINE.get(kind, HEADLINE["unknown"])
    out["headline"] = _short(headline, 300)
    refs = []
    codes = {r.get("code"): r for r in requirements or []}
    wanted = v.get("requirement_code")
    for code, r in codes.items():
        if not code:
            continue
        ref = {"code": code, "id": str(r["id"]) if r.get("id") else None, "title": r.get("title")}
        if wanted and code == wanted and v.get("rule"):
            ref["rule"] = _short(v["rule"], 300)
        refs.append(ref)
    if wanted:
        refs.sort(key=lambda r: r["code"] != wanted)
    if refs:
        out["requirement_refs"] = refs
    if v.get("explanation"):
        out["agent_note"] = _short(v["explanation"], 1000)
    out["next_actions"] = list(NEXT_ACTIONS.get(cause or "unknown", [])) if kind != "non_functional" else []
    return out


def classify(status: str, **kw) -> dict:
    """{failure_kind, suspected_cause, summary} for one execution or self-check."""
    kind = kind_of(
        status,
        error=kw.get("error"),
        failed_assertion=kw.get("failed_assertion"),
        report=kw.get("report"),
        executor=kw.get("executor"),
        forced=kw.get("forced"),
    )
    cause = cause_of(
        kind,
        phase=kw.get("phase", "run"),
        executor=kw.get("executor"),
        code_commit=kw.get("code_commit"),
        bound_commit=kw.get("bound_commit"),
        verdict=kw.get("verdict"),
        case=kw.get("case"),
        requirements=kw.get("requirements"),
    )
    summary = summarize(
        kind,
        cause,
        error=kw.get("error"),
        failed_assertion=kw.get("failed_assertion"),
        report=kw.get("report"),
        verdict=kw.get("verdict"),
        requirements=kw.get("requirements"),
        reason=kw.get("reason"),
    )
    return {"failure_kind": kind, "suspected_cause": cause, "summary": summary}
