"""Local account credentials: scrypt hashing and input policy (decision D36).

No email flows, no recovery links: passwords are changed or reset by an
admin directly on the server through this API. Hashes use hashlib.scrypt
(OWASP-aligned parameters) with a per-user random salt; verification is
constant-time over the derived key.
"""

import hashlib
import hmac
import re
from base64 import b64decode, b64encode

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32

PASSWORD_MIN = 12
PASSWORD_MAX = 128

USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,32}$")


class AccountError(ValueError):
    pass


def validate_username(username: str) -> str:
    if not USERNAME_RE.match(username):
        raise AccountError("Username must be 3-32 chars: lowercase letters, digits, _ or -")
    return username


def validate_password(password: str) -> str:
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise AccountError(f"Password must be {PASSWORD_MIN}-{PASSWORD_MAX} characters")
    if password.isdigit():
        raise AccountError("Password cannot be only digits")
    if len(set(password)) < 4:
        raise AccountError("Password is too repetitive")
    return password


def hash_password(password: str) -> str:
    import os

    raw_salt = os.urandom(16)
    dk = hashlib.scrypt(
        password.encode(),
        salt=raw_salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P, b64encode(raw_salt).decode(), b64encode(dk).decode()
    )


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = b64decode(dk_b64)
        candidate = hashlib.scrypt(
            password.encode(),
            salt=b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False
