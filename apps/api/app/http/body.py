"""Bounded ASGI acquisition for authenticated integration payloads."""

from fastapi import HTTPException, Request


async def bounded_body(request: Request, *, max_bytes: int) -> bytes:
    lengths = request.headers.getlist("content-length")
    if lengths:
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
            raise HTTPException(400, detail={"code": "request_length_invalid"})
        if len(lengths[0]) > 10 or int(lengths[0]) > max_bytes:
            raise HTTPException(413, detail={"code": "request_body_too_large"})
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(413, detail={"code": "request_body_too_large"})
        body.extend(chunk)
    return bytes(body)
