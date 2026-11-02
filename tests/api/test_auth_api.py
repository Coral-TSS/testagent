"""Auth middleware tests; no database needed."""

import re

import pytest
from fastapi.testclient import TestClient

from testagent.api.app import WEB_DIST, create_app

TOKEN = "unit-token-123456"


class FakeDb:
    def ping(self):
        return True


@pytest.fixture
def raw_client(tmp_path):
    app = create_app(FakeDb(), TOKEN, web_dist=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def test_requests_without_token_401(raw_client):
    resp = raw_client.get("/api/v1/suts")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_REQUIRED"
    assert raw_client.get("/api/v1/suts", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_health_and_index_are_public(raw_client):
    assert raw_client.get("/api/v1/health").json()["status"] == "ok"
    resp = raw_client.get("/")
    assert resp.status_code == 200 and "TestAgent" in resp.text


def test_cross_origin_403(raw_client):
    resp = raw_client.get(
        "/api/v1/health",
        headers={"Origin": "http://evil.example", "Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN_ORIGIN"
    same = raw_client.get("/api/v1/health", headers={"Origin": "http://127.0.0.1:8765"})
    assert same.status_code == 200


def test_non_loopback_host_403(tmp_path):
    app = create_app(FakeDb(), TOKEN, web_dist=tmp_path)
    with TestClient(app, base_url="http://attacker.example") as c:
        assert c.get("/api/v1/health").status_code == 403


def test_serves_built_frontend_when_present(tmp_path):
    (tmp_path / "index.html").write_text("<html>built-ui</html>", encoding="utf-8")
    app = create_app(FakeDb(), TOKEN, web_dist=tmp_path)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert "built-ui" in c.get("/").text
    assert "built-ui" in c.get("/suts/123/model?view=list").text  # SPA deep link


def test_spa_fallback_keeps_api_json_and_serves_assets(tmp_path):
    (tmp_path / "index.html").write_text("<html>built-ui</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(FakeDb(), TOKEN, web_dist=tmp_path)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/assets/missing.js").status_code == 404
        missing = c.get("/api/v1/no-such-endpoint", headers=auth)
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/json")
        assert c.get("/api/v1/no-such-endpoint").status_code == 401  # auth still first
        assert "built-ui" in c.get("/../../etc/passwd").text  # no traversal, falls back


def test_placeholder_when_frontend_not_built(tmp_path):
    app = create_app(FakeDb(), TOKEN, web_dist=tmp_path / "missing")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert "npm run build" in c.get("/").text


@pytest.mark.skipif(not (WEB_DIST / "index.html").exists(), reason="frontend not built")
def test_real_build_is_served():
    app = create_app(FakeDb(), TOKEN)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        page = c.get("/versions/abc")
        assert page.status_code == 200 and '<div id="root">' in page.text
        script = re.search(r'src="(/assets/[^"]+\.js)"', page.text).group(1)
        assert c.get(script).status_code == 200


def test_allowed_hosts_extend_loopback(tmp_path):
    """Docker / LAN: extra host names can be allowed explicitly; others stay forbidden."""
    app = create_app(FakeDb(), TOKEN, web_dist=tmp_path, allowed_hosts=["testagent.lan"])
    with TestClient(app, base_url="http://testagent.lan:8765") as c:
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/api/v1/suts").status_code == 401  # still needs the token
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.get("/api/v1/health").status_code == 200
    with TestClient(app, base_url="http://attacker.example") as c:
        assert c.get("/api/v1/health").status_code == 403
