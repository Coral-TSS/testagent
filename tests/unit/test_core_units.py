import logging
import sys

import pytest

from testagent.core.artifacts import ArtifactStore
from testagent.core.config import Settings
from testagent.core.db import assert_test_database
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.core.pipeline import DEFAULT_STAGES, StageRegistry
from testagent.core.redact import RedactingFilter, describe_dsn, redact
from testagent.core.secrets import SecretStore
from testagent.launch import build_url

DSN = "postgresql://postgres:" + "s3cr3t-Pw" + "@localhost:5432/testagent_test"


def test_app_error_body_and_status():
    err = AppError("NOT_FOUND", "x", related=["a"])
    assert err.status == 404
    assert err.body() == {"code": "NOT_FOUND", "message": "x", "field_errors": [], "related": ["a"]}
    with pytest.raises(ValueError):
        AppError("NOPE", "x")


def test_settings_missing_url_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("TESTAGENT_DATABASE_URL", raising=False)
    settings = Settings(_env_file=tmp_path / "none.env")
    with pytest.raises(AppError) as exc:
        settings.require_database_url()
    assert exc.value.code == "CONFIG_MISSING"


def test_settings_repr_hides_password(monkeypatch, tmp_path):
    monkeypatch.setenv("TESTAGENT_DATABASE_URL", DSN)
    settings = Settings(_env_file=tmp_path / "none.env")
    assert "s3cr3t-Pw" not in repr(settings)
    assert "s3cr3t-Pw" not in str(settings.model_dump())
    assert settings.require_database_url() == DSN


def test_redact_dsn_and_kv():
    out = redact(f"connect {DSN} password=abc api_key: zzz")
    assert "s3cr3t-Pw" not in out and "abc" not in out and "zzz" not in out
    assert "postgres:***@" in out
    assert describe_dsn(DSN) == "localhost:5432/testagent_test"


def test_redacting_filter_masks_known_secrets():
    record = logging.LogRecord("t", logging.INFO, "f", 1, "key is %s", ("sk-livekey123",), None)
    RedactingFilter(lambda: ("sk-livekey123",)).filter(record)
    assert record.getMessage() == "key is ***"


def test_refuses_non_test_database():
    with pytest.raises(AppError):
        assert_test_database("postgresql://u@localhost/testagent")
    assert assert_test_database(DSN) == "testagent_test"


def test_event_bus_isolates_failing_subscriber():
    bus = EventBus()
    seen = []

    def bad(event, payload):
        raise RuntimeError("boom")

    bus.subscribe("sut.created", bad)
    bus.subscribe("sut.created", lambda e, p: seen.append((e, p["id"])))
    unsubscribe = bus.subscribe("*", lambda e, p: seen.append(("*", e)))
    errors = bus.publish("sut.created", {"id": "1"})
    assert len(errors) == 1
    assert seen == [("sut.created", "1"), ("*", "sut.created")]
    unsubscribe()
    bus.publish("sut.created", {"id": "2"})
    assert ("*", "sut.created") in seen and len(seen) == 3


class _Stage:
    def __init__(self, name, result):
        self.name = name
        self.result = result

    def run(self, context):
        return {**context, self.name: self.result}


def test_stage_registry_override_and_insert():
    reg = StageRegistry()
    assert reg.order == list(DEFAULT_STAGES)
    with pytest.raises(NotImplementedError):
        reg.get("strategy").run({})
    reg.register(_Stage("strategy", "custom"))
    assert reg.get("strategy").run({}) == {"strategy": "custom"}
    assert reg.order == list(DEFAULT_STAGES)
    reg.register(_Stage("security_scan", 1), after="execution")
    assert reg.order.index("security_scan") == reg.order.index("execution") + 1
    with pytest.raises(TypeError):
        reg.register(object())
    reg.remove("security_scan")
    assert reg.order == list(DEFAULT_STAGES)


def test_artifact_store_roundtrip_dedupe_and_corruption(tmp_path):
    store = ArtifactStore(tmp_path, max_bytes=100)
    digest = store.put(b"hello")
    assert store.put(b"hello") == digest
    assert store.get(digest) == b"hello"
    store._path(digest).write_bytes(b"tampered")
    with pytest.raises(AppError) as exc:
        store.get(digest)
    assert exc.value.code == "ARTIFACT_CORRUPT"
    with pytest.raises(AppError) as exc:
        store.put(b"x" * 101)
    assert exc.value.code == "ARTIFACT_TOO_LARGE"
    with pytest.raises(AppError):
        store.get("../etc/passwd")


def test_secret_store_roundtrip_and_not_plaintext(tmp_path):
    store = SecretStore(tmp_path / "secrets.json")
    store.set("llm_api_key", "sk-very-secret-value")
    assert store.get("llm_api_key") == "sk-very-secret-value"
    assert "sk-very-secret-value" not in (tmp_path / "secrets.json").read_text()
    assert SecretStore.mask("sk-very-secret-value") == "****alue"
    assert store.values() == ("sk-very-secret-value",)
    store.delete("llm_api_key")
    assert store.get("llm_api_key") is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_secret_store_file_mode_600(tmp_path):
    store = SecretStore(tmp_path / "secrets.json")
    store.set("a", "b")
    assert (tmp_path / "secrets.json").stat().st_mode & 0o777 == 0o600


def test_launch_fragment_url():
    url = build_url("127.0.0.1", 8765, "tok")
    assert url == "http://127.0.0.1:8765/#t=tok"
    assert "?" not in url
