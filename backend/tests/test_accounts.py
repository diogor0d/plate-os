"""Account credential service: hashing, policy, and login-shape rules."""

import pytest

from app.services.accounts import (
    AccountError,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)


def test_hash_roundtrip_and_wrong_password():
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("correct horse battery stapler", stored)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "garbage")


def test_hashes_are_salted():
    a = hash_password("same-password-123")
    b = hash_password("same-password-123")
    assert a != b


@pytest.mark.parametrize(
    "bad",
    ["short1x", "", "a" * 200, "aaaaaaaaaaaa", "123456789012"],
)
def test_weak_passwords_rejected(bad):
    with pytest.raises(AccountError):
        validate_password(bad)


def test_valid_password_accepted():
    assert validate_password("Cedar-Maple-47-River") == "Cedar-Maple-47-River"


@pytest.mark.parametrize(
    ("name", "ok"),
    [("admin", True), ("diogo", True), ("ab", False), ("Bad Name", False), ("x" * 33, False)],
)
def test_username_policy(name, ok):
    if ok:
        assert validate_username(name) == name
    else:
        with pytest.raises(AccountError):
            validate_username(name)
