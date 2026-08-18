from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None
    user_agent: str | None

    @property
    def ip_or_unknown(self) -> str:
        return self.ip or "unknown"


def get_client_info(request: Request) -> ClientInfo:
    forwarded_for = request.headers.get("x-forwarded-for")

    if forwarded_for:
        ip = forwarded_for.split(",", maxsplit=1)[0].strip()
    elif request.client:
        ip = request.client.host
    else:
        ip = None

    return ClientInfo(
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
