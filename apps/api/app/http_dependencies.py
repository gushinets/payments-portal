from __future__ import annotations

from fastapi import Request


async def get_raw_request_body(request: Request) -> bytes:
    return await request.body()
