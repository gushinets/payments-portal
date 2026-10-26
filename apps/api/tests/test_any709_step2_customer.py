"""No network: real users/Client protocol and account-only security contracts."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from app.composition.sources import source_resources
from app.domains.identity.router import RegisterRequest
from app.integrations.lbx.customer import NewCustomer, sign_widget_jwt
from app.integrations.lbx.errors import LbxError, LbxResponseInvalid, LbxScopeMismatch
from apps.api.tests.support.any709_step1 import step1_settings


@pytest.mark.parametrize(
    "fields,expected",
    [
        ({}, (None, None, None)),
        ({"first_name": None, "surname": None, "patronymic": None}, (None, None, None)),
        ({"first_name": "", "surname": "", "patronymic": ""}, (None, None, None)),
        ({"first_name": "   ", "surname": "   ", "patronymic": "   "}, (None, None, None)),
        ({"first_name": "  Anna "}, ("Anna", None, None)),
        ({"surname": " Smith ", "patronymic": "  "}, (None, "Smith", None)),
        ({"patronymic": " Ивановна "}, (None, None, "Ивановна")),
        ({"first_name": " Анна ", "surname": " Иванова ", "patronymic": " Ивановна "}, ("Анна", "Иванова", "Ивановна")),
    ],
)
def test_any709_step2_optional_independent_names(
    fields: dict[str, str | None], expected: tuple[str | None, ...]
) -> None:
    request = RegisterRequest(
        email="synthetic@example.com", password="Strong-password1!", personal_consent=True, offer_consent=True, **fields
    )
    assert (request.first_name, request.surname, request.patronymic) == expected


@pytest.mark.parametrize("field", ["first_name", "surname", "patronymic"])
def test_any709_step2_name_length_limit_applies_after_trim(field: str) -> None:
    request = RegisterRequest(
        email="synthetic@example.com",
        password="Strong-password1!",
        personal_consent=True,
        offer_consent=True,
        **{field: "  " + "я" * 100 + "  "},
    )
    assert getattr(request, field) == "я" * 100


@pytest.mark.parametrize("field", ["first_name", "surname", "patronymic"])
@pytest.mark.parametrize(
    "value",
    [
        "x" * 101,
        "  " + "я" * 101 + "  ",
        "bad\x00name",
        "bad\tname",
        "bad\nname",
        "bad\x7fname",
        123,
        True,
        ["name"],
        {},
    ],
)
def test_any709_step2_invalid_name(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="synthetic@example.com",
            password="Strong-password1!",
            personal_consent=True,
            offer_consent=True,
            **{field: value},
        )


def test_any709_step2_credentials_are_transient_and_jwt_is_type7() -> None:
    command = NewCustomer(outer_id="opaque", email="synthetic@example.com", user_patronymic="Synthetic")
    body = command.request_document()
    assert body["type"] == 2 and "user_name" not in body and "user_surname" not in body
    password = body["password"]
    assert len(password) == 24 and password.isascii() and password.isalnum()
    assert (
        any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password)
    )
    assert body["login"] != command.request_document()["login"]
    assert "password" not in command.model_dump() and password not in repr(command)
    config = step1_settings()
    credential = sign_widget_jwt(customer_id="345", secret=config.lbx_widget_signing_secret, issued_at=1000)
    header, payload, signature = credential.get_secret_value().split(".")
    assert json.loads(base64.urlsafe_b64decode(payload + "==")) == {"ident_type": 7, "ident": "345", "iat": 1000}
    signed = hmac.new(
        config.lbx_widget_signing_secret.get_secret_value().encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    assert base64.urlsafe_b64decode(signature + "==") == signed
    assert credential.get_secret_value() not in repr(credential)


@pytest.mark.parametrize("status", [200, 201])
def test_any709_step2_real_users_and_client_envelopes(status: int, caplog: pytest.LogCaptureFixture) -> None:
    posts = []
    calls = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/auth"):
            return httpx.Response(
                200, json={"code": 200, "response": {"token": "private-server-token", "expires_in": 600}}
            )
        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(status, json={"code": status, "response": {"user_id": 345}})
        if request.url.path.endswith("/client/user"):
            assert "private-server-token" not in request.headers["authorization"]
        row = {
            "user_id": 345,
            "outer_id": "opaque",
            "email": "synthetic@example.com",
            "user_name": "Synthetic",
            "password": "",
        }
        return httpx.Response(
            200, json={"code": 200, "response": [row] if request.url.path.endswith("/users") else row}
        )

    async def scenario() -> None:
        config = step1_settings()
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            async with sources.billing.operation() as budget:
                client = sources.require_lbx()
                await client.prepare_customer_create(budget=budget)
                assert (
                    await client.create_user(
                        NewCustomer(outer_id="opaque", email="synthetic@example.com"), budget=budget
                    )
                    == 345
                )
                assert (await client.get_user(user_id=345, budget=budget)).outer_id == "opaque"
                assert await client.discover_users(outer_id="opaque", budget=budget) == (345,)
                token = sign_widget_jwt(customer_id="345", secret=config.lbx_widget_signing_secret)
                assert (await client.client_user(token=token, budget=budget)).user_id == 345

    with caplog.at_level(logging.DEBUG):
        asyncio.run(scenario())
    assert len(posts) == 1
    for forbidden in [posts[0]["password"], posts[0]["login"], "synthetic@example.com", "private-server-token"]:
        assert forbidden not in caplog.text
    assert ("GET", "/api/rest/v1/client/user") in calls


@pytest.mark.parametrize(
    "status,body",
    [
        (500, {"code": 500}),
        (401, {"code": 401}),
        (201, {"code": 201, "response": {}}),
        (200, {"code": 200, "response": {"user_id": "345"}}),
    ],
)
def test_any709_step2_possible_post_is_never_replayed(status: int, body: dict) -> None:
    sends = []

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "server", "expires_in": 600}})
        sends.append(request.method)
        return httpx.Response(status, json=body)

    async def scenario() -> None:
        async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(transport)) as sources:
            async with sources.billing.operation() as budget:
                await sources.lbx.prepare_customer_create(budget=budget)
                with pytest.raises(LbxError):
                    await sources.lbx.create_user(
                        NewCustomer(outer_id="opaque", email="synthetic@example.com"), budget=budget
                    )

    asyncio.run(scenario())
    assert sends == ["POST"]


@pytest.mark.parametrize(
    "row,exception",
    [
        ({"user_id": 346, "outer_id": "opaque"}, LbxScopeMismatch),
        ({"user_id": 345, "outer_id": "opaque", "password": "do-not-return"}, LbxResponseInvalid),
        ({"outer_id": "opaque"}, LbxResponseInvalid),
    ],
)
def test_any709_step2_invalid_user_read(row: dict, exception: type[LbxError]) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        body = {"token": "server", "expires_in": 600} if request.url.path.endswith("/auth") else row
        return httpx.Response(200, json={"code": 200, "response": body})

    async def scenario() -> None:
        async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(transport)) as sources:
            async with sources.billing.operation() as budget:
                with pytest.raises(exception):
                    await sources.lbx.get_user(user_id=345, budget=budget)

    asyncio.run(scenario())


def test_any709_step2_expired_server_session_is_definitely_not_sent() -> None:
    from dataclasses import replace
    from app.integrations.lbx.errors import LbxCreateNotSent

    calls = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"code": 200, "response": {"token": "private-server", "expires_in": 600}})

    async def scenario() -> None:
        async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(transport)) as sources:
            async with sources.billing.operation() as budget:
                await sources.lbx.prepare_customer_create(budget=budget)
                sources.lbx._session = replace(sources.lbx._session, expires_at=0)
                with pytest.raises(LbxCreateNotSent):
                    await sources.lbx.create_user(
                        NewCustomer(outer_id="opaque", email="synthetic@example.com"), budget=budget
                    )

    asyncio.run(scenario())
    assert calls == ["GET"]
