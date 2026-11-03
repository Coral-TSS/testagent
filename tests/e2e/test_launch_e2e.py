"""E2E: launcher ticket → signed in → create a SUT → still there after reload; password sign-in / sign-out."""

from __future__ import annotations

import socket
import threading
import time

import pytest
from tests.conftest import TEST_PASSWORD
from tests.fixtures.mini_shop import browser_available

from testagent.api.app import WEB_DIST, create_app
from testagent.core.secrets import SecretStore
from testagent.launch import ticket_url
from testagent.services.auth import AuthService

pytestmark = [
    pytest.mark.skipif(not browser_available(), reason="playwright chromium not installed"),
    pytest.mark.skipif(not (WEB_DIST / "index.html").exists(), reason="frontend not built"),
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(db, tmp_path):
    import uvicorn

    app = create_app(db, secrets=SecretStore(tmp_path / "secrets.json"), runtime_dir=tmp_path / "rt")
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not srv.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    yield port, app
    srv.should_exit = True
    thread.join(10)


def test_launcher_url_login_create_sut_persists(server):
    from playwright.sync_api import expect, sync_playwright

    port, app = server
    ticket = app.state.tickets.issue(app.state.auth.local_admin()["id"])

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(ticket_url("127.0.0.1", port, ticket))
            # the ticket is consumed from the fragment and removed from the address bar
            # the empty state repeats the primary action, so two buttons are fine
            create = page.get_by_role("button", name="New SUT").first
            expect(create).to_be_visible(timeout=15000)
            assert "#ticket=" not in page.url

            create.click()
            page.get_by_label("Code").fill("e2e_shop")
            page.get_by_label("Name").fill("E2E shop")
            page.get_by_role("dialog").get_by_role("button", name="OK").or_(
                page.get_by_role("dialog").get_by_role("button", name="OK")
            ).click()
            expect(page.get_by_text("E2E shop").first).to_be_visible()

            page.reload()
            expect(page.get_by_text("E2E shop").first).to_be_visible(timeout=15000)
            expect(page.get_by_text("e2e_shop")).to_be_visible()
        finally:
            browser.close()


def test_password_sign_in_and_sign_out(server, db):
    from playwright.sync_api import expect, sync_playwright

    port, _ = server
    AuthService(db).create_user("alice", TEST_PASSWORD, display_name="Alice")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/suts")
            page.get_by_label("User name").fill("alice")
            page.get_by_label("Password").fill("wrong-password-1")
            page.get_by_role("button", name="Sign in").click()
            expect(page.get_by_text("Wrong user name or password")).to_be_visible(timeout=15000)
            page.get_by_label("Password").fill(TEST_PASSWORD)
            page.get_by_role("button", name="Sign in").click()
            expect(page.get_by_role("button", name="New SUT").first).to_be_visible(timeout=15000)
            cookie = next(c for c in page.context.cookies() if c["name"] == "ta_session")
            assert cookie["httpOnly"] and cookie["sameSite"] == "Lax"
            assert page.evaluate("document.cookie").find("ta_session") == -1  # not readable by scripts
            page.reload()  # the session survives a reload
            expect(page.get_by_role("button", name="New SUT").first).to_be_visible(timeout=15000)
            page.get_by_role("button", name="Account").click()
            page.get_by_text("Sign out").click()
            expect(page.get_by_role("button", name="Sign in")).to_be_visible()
            page.reload()
            expect(page.get_by_role("button", name="Sign in")).to_be_visible(timeout=15000)
        finally:
            browser.close()
