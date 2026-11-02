"""Settings and launcher helpers used by Docker / headless runs."""

from testagent.core.config import Settings
from testagent.launch import access_token, display_host, sign_in_url


def test_allowed_hosts_parsed_from_comma_list():
    s = Settings(_env_file=None, allowed_hosts="testagent.lan, 10.0.0.5 ,")
    assert s.allowed_host_list() == ["testagent.lan", "10.0.0.5"]
    assert Settings(_env_file=None).allowed_host_list() == []


def test_access_token_from_env_or_generated():
    assert access_token(Settings(_env_file=None, access_token="fixed-token-123")) == (
        "fixed-token-123",
        True,
    )
    assert access_token(Settings(_env_file=None, dev_token="legacy-token-1")) == (
        "legacy-token-1",
        True,
    )
    token, fixed = access_token(Settings(_env_file=None))
    assert len(token) >= 32 and fixed is False


def test_display_host_and_sign_in_url():
    assert display_host("0.0.0.0") == "localhost"
    assert display_host("::") == "localhost"
    assert display_host("127.0.0.1") == "127.0.0.1"
    assert sign_in_url("0.0.0.0", 8765, "tok") == "http://localhost:8765/#t=tok"
