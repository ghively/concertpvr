import pytest

from concertpvr.auth import hash_password, verify_password
from concertpvr.session import create_token, verify_token


def test_hash_round_trip():
    h = hash_password("hunter2")
    assert isinstance(h, str)
    assert h.startswith("$argon2")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_unique_per_call():
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    assert verify_password("same", a)
    assert verify_password("same", b)


def test_verify_handles_invalid_hash_gracefully():
    assert verify_password("anything", "not-a-real-hash") is False
    assert verify_password("anything", "") is False


def test_create_and_verify_token():
    secret = "test-secret-32-bytes-long-enough"
    token = create_token({"user": "admin"}, secret)
    assert isinstance(token, str)
    payload = verify_token(token, secret, max_age_s=3600)
    assert payload == {"user": "admin"}


def test_verify_token_rejects_wrong_secret():
    secret = "real-secret"
    token = create_token({"user": "admin"}, secret)
    assert verify_token(token, "different-secret", max_age_s=3600) is None


def test_verify_token_rejects_expired():
    import time
    secret = "test-secret"
    token = create_token({"user": "admin"}, secret)
    time.sleep(1)
    assert verify_token(token, secret, max_age_s=0) is None


def test_verify_token_rejects_garbage():
    assert verify_token("garbage", "secret", max_age_s=3600) is None
    assert verify_token("", "secret", max_age_s=3600) is None
