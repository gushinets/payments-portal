from __future__ import annotations

import hashlib
import hmac

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

PBKDF2_ITERATIONS = 120_000
ARGON2_MEMORY_COST = 19_456
ARGON2_TIME_COST = 2
ARGON2_PARALLELISM = 1
ARGON2_HASH_LEN = 32

_ARGON2_PREFIX = "$argon2id$"
_PBKDF2_PREFIX = "pbkdf2_sha256$"
_MAX_LEGACY_PBKDF2_ITERATIONS = 1_000_000
_PASSWORD_HASHER = PasswordHasher(
    memory_cost=ARGON2_MEMORY_COST,
    time_cost=ARGON2_TIME_COST,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LEN,
    type=Type.ID,
)


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def _parse_pbkdf2_password(encoded: str) -> tuple[int, str, bytes] | None:
    try:
        algorithm, iterations_raw, salt, expected = encoded.split("$", 3)
        iterations = int(iterations_raw)
        expected_digest = bytes.fromhex(expected)
    except (TypeError, ValueError):
        return None

    if (
        algorithm != "pbkdf2_sha256"
        or not 1 <= iterations <= _MAX_LEGACY_PBKDF2_ITERATIONS
        or not salt
        or len(expected_digest) != hashlib.sha256().digest_size
    ):
        return None

    return iterations, salt, expected_digest


def _verify_pbkdf2_password(password: str, encoded: str) -> bool:
    parsed = _parse_pbkdf2_password(encoded)
    if parsed is None:
        return False
    iterations, salt, expected_digest = parsed

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(digest, expected_digest)


def verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith(_ARGON2_PREFIX):
        try:
            return _PASSWORD_HASHER.verify(encoded, password)
        except (InvalidHashError, VerificationError):
            return False

    if encoded.startswith(_PBKDF2_PREFIX):
        return _verify_pbkdf2_password(password, encoded)

    return False


def password_hash_needs_rehash(encoded: str) -> bool:
    if encoded.startswith(_PBKDF2_PREFIX):
        return _parse_pbkdf2_password(encoded) is not None
    if not encoded.startswith(_ARGON2_PREFIX):
        return False

    try:
        return _PASSWORD_HASHER.check_needs_rehash(encoded)
    except InvalidHashError:
        return False
