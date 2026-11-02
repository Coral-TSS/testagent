"""T-08.2 browser tool (real Chromium against a local fixture app)."""

import pytest
from tests.fixtures.mini_shop import MiniShop, browser_available

from testagent.core.artifacts import ArtifactStore
from testagent.integrations.browser import BrowserSession, Target

pytestmark = pytest.mark.skipif(not browser_available(), reason="playwright chromium not installed")

AMOUNT = Target(label="Amount")
SUBMIT = Target(role="button", name="Submit")
MSG = Target(role="status")


@pytest.fixture
def shop():
    with MiniShop() as app:
        yield app


def run_amount(session: BrowserSession, amount: str, expected: str):
    session.goto("/")
    session.fill(AMOUNT, amount)
    session.click(SUBMIT)
    return session.assert_("text", expected, MSG)


def test_assert_pass_and_fail_receipts(shop, tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    with BrowserSession(shop.url, store) as ok:
        step = run_amount(ok, "0", "Amount must be greater than 0")
    assert step["assertion"] == "passed" and ok.verdict().status == "passed"

    with BrowserSession(shop.url + "/bug/", store) as bad:
        step = run_amount(bad, "0", "Amount must be greater than 0")
    verdict = bad.verdict()
    assert step["assertion"] == "failed" and verdict.status == "failed"
    assert (
        "Amount must be greater than 0" in verdict.failed_assertion
        and "Submitted successfully" in verdict.failed_assertion
    )
    assert bad.receipts[0]["actual"] == "Submitted successfully"


def test_steps_recorded_with_screenshot(shop, tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    session = BrowserSession(shop.url, store).start()
    try:
        run_amount(session, "5", "Submitted successfully")
    finally:
        files = session.close()
    assert [s["action"] for s in session.steps] == ["goto", "fill", "click", "assert"]
    assert [s["seq"] for s in session.steps] == [1, 2, 3, 4]
    fill = session.steps[1]
    assert fill["target"] == {"label": "Amount"} and fill["value"] == "5"
    assert session.steps[2]["target"] == {"role": "button", "name": "Submit"}
    for step in session.steps:
        assert store.get(step["screenshot_sha"]).startswith(b"\x89PNG")
    assert files and files[0]["kind"] == "trace" and store.get(files[0]["sha256"])[:2] == b"PK"


def test_tool_timeout_is_error(shop, tmp_path):
    with BrowserSession(shop.url, ArtifactStore(tmp_path / "a"), timeout_ms=500) as session:
        session.goto("/")
        step = session.click(Target(role="button", name="Nonexistent button"))
        session.assert_("visible", None, Target(role="heading", name="New purchase order"))
    assert step["status"] == "error" and "timeout" in step["result"]
    verdict = session.verdict()
    assert verdict.status == "error" and "click" in verdict.error


def test_no_assertion_is_error_and_missing_element_fails(shop, tmp_path):
    with BrowserSession(shop.url, ArtifactStore(tmp_path / "a"), timeout_ms=500) as session:
        session.goto("/")
    assert session.verdict().status == "error" and "NO_ASSERTION" in session.verdict().error
    with BrowserSession(shop.url, ArtifactStore(tmp_path / "a"), timeout_ms=500) as session:
        session.goto("/")
        step = session.assert_("visible", None, Target(text=" does not exist"))
    assert step["status"] == "ok" and step["assertion"] == "failed"
    assert session.verdict().status == "failed"
