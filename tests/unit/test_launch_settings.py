"""Settings and launcher helpers used by Docker / headless runs."""

import logging

from testagent.core.config import Settings
from testagent.launch import display_host, legacy_token_set, ticket_url


def test_allowed_hosts_parsed_from_comma_list():
    s = Settings(_env_file=None, allowed_hosts="testagent.lan, 10.0.0.5 ,")
    assert s.allowed_host_list() == ["testagent.lan", "10.0.0.5"]
    assert Settings(_env_file=None).allowed_host_list() == []


def test_auth_defaults():
    s = Settings(_env_file=None)
    assert (s.cookie_secure, s.session_idle_hours, s.session_max_days) == ("auto", 12, 7)
    assert s.trusted_proxies == "127.0.0.1" and s.admin_user is None and s.admin_password is None


def test_legacy_token_only_detected():
    assert legacy_token_set(Settings(_env_file=None, access_token="fixed-token-123"))
    assert legacy_token_set(Settings(_env_file=None, dev_token="legacy-token-1"))
    assert not legacy_token_set(Settings(_env_file=None))


def test_display_host_and_ticket_url():
    assert display_host("0.0.0.0") == "localhost"
    assert display_host("::") == "localhost"
    assert display_host("127.0.0.1") == "127.0.0.1"
    assert ticket_url("0.0.0.0", 8765, "tk") == "http://localhost:8765/#ticket=tk"


def test_admin_password_is_secret():
    s = Settings(_env_file=None, admin_user="boss", admin_password="not-shown-anywhere")
    assert "not-shown-anywhere" not in repr(s) and "not-shown-anywhere" not in str(s.model_dump())
    logging.getLogger("t").info("%s", s)  # SecretStr renders as ********
