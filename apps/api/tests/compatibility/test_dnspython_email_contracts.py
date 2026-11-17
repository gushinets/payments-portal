from __future__ import annotations

import secrets
import subprocess
import sys
from unittest.mock import Mock

import dns.name
import dns.resolver
import email_validator
import pytest
from pydantic import ValidationError

from app.domains.identity.password_reset import PasswordResetRequest
from app.domains.identity.router import LoginRequest, RegisterRequest
from app.domains.identity.services.auth import normalize_email


@pytest.fixture
def offline_email_validation(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Observe the actual validator while refusing DNS and socket operations."""
    import socket

    validator = Mock(wraps=email_validator.validate_email)
    monkeypatch.setattr(email_validator, "validate_email", validator)
    for owner, name in (
        (dns.resolver.Resolver, "resolve"),
        (dns.name, "from_wire_parser"),
        (socket, "getaddrinfo"),
        (socket, "socket"),
    ):
        monkeypatch.setattr(owner, name, Mock(side_effect=AssertionError("Email validation attempted network/DNS")))
    return validator


@pytest.mark.parametrize("model", [RegisterRequest, LoginRequest, PasswordResetRequest])
@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("USER@EXAMPLE.COM", "USER@example.com"),
        ("  Synthetic <Mixed.Case+tag@EXAMPLE.COM>  ", "Mixed.Case+tag@example.com"),
        ("user@xn--bcher-kva.de", "user@bücher.de"),
        ("e\u0301@example.com", "é@example.com"),
        ("user@synthetic-domain-does-not-exist.com", "user@synthetic-domain-does-not-exist.com"),
    ],
)
def test_identity_email_remains_offline_and_normalized(
    model: type[RegisterRequest] | type[LoginRequest] | type[PasswordResetRequest],
    email: str,
    expected: str,
    offline_email_validation: Mock,
) -> None:
    request = model.model_validate(
        {"email": email, "password": secrets.token_urlsafe(18), "personal_consent": True, "offer_consent": True}
    )
    assert str(request.email) == expected
    assert normalize_email(str(request.email)) == expected.strip().lower()
    assert offline_email_validation.call_count == 1
    assert offline_email_validation.call_args.kwargs == {"check_deliverability": False}


@pytest.mark.parametrize("model", [RegisterRequest, LoginRequest, PasswordResetRequest])
@pytest.mark.parametrize(
    "email", ["not-an-email", "user＠example.com", "user@localhost", "user@[127.0.0.1]", "a..b@example.com"]
)
def test_identity_rejects_invalid_email_without_dns(
    model: type[RegisterRequest] | type[LoginRequest] | type[PasswordResetRequest],
    email: str,
    offline_email_validation: Mock,
) -> None:
    with pytest.raises(ValidationError) as error:
        model.model_validate(
            {"email": email, "password": secrets.token_urlsafe(18), "personal_consent": True, "offer_consent": True}
        )
    assert error.value.errors()[0]["loc"] == ("email",)
    assert offline_email_validation.call_args.kwargs == {"check_deliverability": False}


@pytest.mark.parametrize("hops", [16, 17])
def test_upstream_dns_compression_chain_limit_in_bounded_process(hops: int) -> None:
    # Equivalent to the 16/17-pointer fixture in upstream b485e460c266540a1a09ca6d8d1d7b685b1d3023.
    # subprocess.run kills and reaps the child on timeout; this never sends a DNS query.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import dns.name, dns.exception, sys; "
            "hops = int(sys.argv[1]); "
            "wire = b'\\x00\\x00' + b''.join((0xC000 | (2*i)).to_bytes(2, 'big') for i in range(hops)); "
            "\ntry:\n name, consumed = dns.name.from_wire(wire, len(wire)-2)"
            "\nexcept dns.exception.FormError as error:\n print(type(error).__name__)"
            "\nelse:\n print(str(name), consumed)",
            str(hops),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout.strip() == (". 2" if hops == 16 else "PointerChainTooLong")
