"""In-memory sign-in rate limit and launcher tickets."""

import pytest

from testagent.core.errors import AppError
from testagent.services.auth import LocalTickets, LoginRateLimiter


def test_rate_limit_per_address():
    limiter = LoginRateLimiter(per_minute=3, per_hour=100)
    for _ in range(3):
        limiter.hit("198.51.100.1")
    with pytest.raises(AppError) as err:
        limiter.hit("198.51.100.1")
    assert err.value.code == "RATE_LIMITED" and err.value.status == 429
    limiter.hit("198.51.100.2")  # other addresses are not affected


def test_ticket_single_use_and_expiry():
    tickets = LocalTickets(ttl_s=60)
    raw = tickets.issue("u1")
    assert tickets.redeem(raw) == "u1"
    assert tickets.redeem(raw) is None  # single use
    assert tickets.redeem("made-up") is None
    expired = LocalTickets(ttl_s=-1)
    assert expired.redeem(expired.issue("u2")) is None
