"""argon2id hashing and the password rules."""

import pytest

from testagent.core.errors import AppError
from testagent.core.passwords import check_rules, hash_password, needs_rehash, verify_password


def test_hash_and_verify():
    h = hash_password("correct horse battery")
    assert h.startswith("$argon2id$") and "correct horse" not in h
    assert verify_password(h, "correct horse battery")
    assert not verify_password(h, "wrong password!!")
    assert not verify_password(None, "anything at all")  # unknown user: still false
    assert not verify_password("not-a-hash", "anything at all")
    assert not needs_rehash(h)


@pytest.mark.parametrize("pw", ["short", "x" * 129, "alice12345"])
def test_rules_reject(pw):
    with pytest.raises(AppError):
        check_rules(pw, "alice12345")


def test_rules_accept():
    check_rules("ten chars!", "alice")
