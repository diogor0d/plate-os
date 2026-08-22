"""Session-token security tests (pure, no DB)."""

import time
import uuid

from app.api.deps import _sign, issue_session_token, verify_session_token


def test_roundtrip():
    uid = uuid.uuid4()
    assert verify_session_token(issue_session_token(uid)) == uid


def test_tampered_signature_rejected():
    token = issue_session_token(uuid.uuid4())
    uid, exp, _ = token.rsplit(":", 2)
    assert verify_session_token(f"{uid}:{exp}:deadbeef") is None


def test_garbage_rejected():
    assert verify_session_token("") is None
    assert verify_session_token("not-a-token") is None
    assert verify_session_token("x:y:z:w") is None


def test_expired_token_rejected():
    uid = uuid.uuid4()
    expired = int(time.time()) - 10
    payload = f"{uid}:{expired}"
    assert verify_session_token(f"{payload}:{_sign(payload)}") is None
