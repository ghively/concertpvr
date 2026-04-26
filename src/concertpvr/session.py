"""Cookie-token serialization for session auth."""

from __future__ import annotations

import secrets
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "concertpvr-session-v1"


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def create_token(payload: dict[str, Any], secret: str) -> str:
    s = URLSafeTimedSerializer(secret, salt=_SALT)
    return s.dumps(payload)


def verify_token(token: str, secret: str, max_age_s: int) -> dict[str, Any] | None:
    if not token:
        return None
    s = URLSafeTimedSerializer(secret, salt=_SALT)
    try:
        return s.loads(token, max_age=max_age_s)
    except (BadSignature, SignatureExpired):
        return None
