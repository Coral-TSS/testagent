"""T-02.4 E2E: launcher URL → auto login → create a SUT in the UI → still there after reload."""

from __future__ import annotations

import socket
import threading
import time

import pytest
from tests.conftest import TOKEN
from tests.fixtures.mini_shop import browser_available

from testagent.api.app import WEB_DIST, create_app
from testagent.core.secrets import SecretStore
from testagent.launch import build_url

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

    app = create_app(db, TOKEN, secrets=SecretStore(tmp_path / "secrets.json"), runtime_dir=tmp_path / "rt")
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not srv.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    yield port
    srv.should_exit = True
    thread.join(10)


def test_launcher_url_login_create_sut_persists(server):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(build_url("127.0.0.1", server, TOKEN))
            # token is consumed from the fragment and removed from the address bar
            # the empty state repeats the primary action, so two buttons are fine
            create = page.get_by_role("button", name="New SUT").first
            expect(create).to_be_visible(timeout=15000)
            assert "#t=" not in page.url

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
