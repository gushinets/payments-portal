"""Private users/Client API boundary. Credentials exist only for one POST."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import string
import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class PrivateDto(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True, hide_input_in_errors=True)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<private>)"

    def __str__(self) -> str:
        return self.__repr__()


class LbxUser(PrivateDto):
    user_id: Annotated[int, Field(strict=True, gt=0)]
    outer_id: str | None = None
    # Explicitly excluded from diagnostics/serialization, including hostile GETs.
    password: SecretStr | None = Field(default=None, exclude=True, repr=False)


class CreatedUser(PrivateDto):
    user_id: Annotated[int, Field(strict=True, gt=0)]


class CreatedUserEnvelope(PrivateDto):
    code: Literal[200, 201]
    response: CreatedUser


class NewCustomer(PrivateDto):
    type: Literal[2] = 2
    outer_id: str
    email: str
    user_name: str | None = None
    user_surname: str | None = None
    user_patronymic: str | None = None

    def request_document(self) -> dict[str, Any]:
        alphabet = string.ascii_letters + string.digits
        while True:
            password = "".join(secrets.choice(alphabet) for _ in range(24))
            if (
                any(c.isupper() for c in password)
                and any(c.islower() for c in password)
                and any(c.isdigit() for c in password)
            ):
                break
        return {
            **self.model_dump(exclude_none=True),
            "login": "portal_" + secrets.token_hex(12),
            "password": password,
        }


def sign_widget_jwt(*, customer_id: str, secret: SecretStr, issued_at: int | None = None) -> SecretStr:
    if (
        not secret.get_secret_value()
        or not customer_id.isascii()
        or not customer_id.isdecimal()
        or int(customer_id) <= 0
        or str(int(customer_id)) != customer_id
    ):
        raise ValueError("invalid widget identity/configuration")

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    header = encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = encode(
        json.dumps(
            {"ident_type": 7, "ident": customer_id, "iat": int(time.time()) if issued_at is None else issued_at},
            separators=(",", ":"),
        ).encode()
    )
    message = f"{header}.{payload}"
    return SecretStr(
        message + "." + encode(hmac.new(secret.get_secret_value().encode(), message.encode(), hashlib.sha256).digest())
    )
