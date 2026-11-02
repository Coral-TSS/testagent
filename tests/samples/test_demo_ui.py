"""the demo UI drives the whole flow through stable data-testid hooks (real browser)."""

import socket
import threading
import time

import pytest

from examples.procurement.api import create_app


@pytest.fixture
def serve(tmp_path):
    import uvicorn

    servers = []

    def start(bugs: bool) -> str:
        app = create_app(tmp_path / f"ui-{bugs}.db", demo_bugs=bugs)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.monotonic() + 15
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        servers.append(server)
        return f"http://127.0.0.1:{port}"

    yield start
    for server in servers:
        server.should_exit = True


def walk(page, base):
    from playwright.sync_api import expect

    page.goto(base + "/")
    expect(page.get_by_test_id("notice")).to_have_text("Ready")
    page.get_by_test_id("order-title").fill("Procurement server")
    page.get_by_test_id("order-amount").fill("60000.00")
    page.get_by_test_id("order-submit").click()
    first = page.get_by_test_id("order-row").first
    expect(first.get_by_test_id("order-state")).to_have_text("Pending approval")
    expect(page.get_by_test_id("detail-supplier")).to_have_text("East China Office Supplies Co.")
    page.get_by_test_id("reject").click()
    return first


def test_ui_flow_without_bugs(serve):
    from playwright.sync_api import expect, sync_playwright

    base = serve(False)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            first = walk(page, base)
            expect(first.get_by_test_id("order-state")).to_have_text("Rejected")
            # small order: auto approved, pay once, replay keeps one ledger row
            page.get_by_test_id("order-amount").fill("1000")
            page.get_by_test_id("order-submit").click()
            expect(page.get_by_test_id("detail-state")).to_have_text("Approved")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("detail-state")).to_have_text("Paid")
            page.get_by_test_id("pay-submit").click()
            expect(page.get_by_test_id("payment-row")).to_have_count(1)
            page.get_by_test_id("tab-suppliers").click()
            page.get_by_test_id("supplier-name").fill("Grand Stationery Co.")
            page.get_by_test_id("supplier-submit").click()
            expect(page.get_by_test_id("supplier-row")).to_have_count(4)
            page.once("dialog", lambda d: d.accept())
            page.get_by_test_id("reset-demo").click()
            expect(page.get_by_test_id("supplier-row")).to_have_count(3)
            page.get_by_test_id("tab-orders").click()
            expect(page.get_by_test_id("order-list-empty")).to_be_visible()
        finally:
            browser.close()


def test_ui_seeded_display_bug(serve):
    from playwright.sync_api import expect, sync_playwright

    base = serve(True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            first = walk(browser.new_page(), base)
            expect(first.get_by_test_id("order-state")).to_have_text("Pending approval")  # bug 3
        finally:
            browser.close()
