"""Loopback ingress for the real Kernel API/web pair, preserving service headers.

BackendConsumer binds callback and API to one origin, as a deployed ingress does.
This local proxy supplies that topology without changing either application.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import Response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(trust_env=False, timeout=90) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None)
HOP_HEADERS = {
    "host",
    "connection",
    "transfer-encoding",
    "content-length",
    "content-encoding",
}


@app.api_route("/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def proxy(path: str, request: Request) -> Response:
    origin = (
        os.environ["ANY766_KERNEL_API_ORIGIN"]
        if path.startswith(("v1/", "internal/", "health"))
        else os.environ["ANY766_KERNEL_WEB_ORIGIN"]
    )
    url = (
        origin
        + request.url.path
        + ("?" + request.url.query if request.url.query else "")
    )
    response = await request.app.state.client.request(
        request.method,
        url,
        content=await request.body(),
        headers=[
            (key, value)
            for key, value in request.headers.items()
            if key.lower() not in HOP_HEADERS
        ],
    )
    return Response(
        response.content,
        status_code=response.status_code,
        headers={
            key: value
            for key, value in response.headers.items()
            if key.lower() not in HOP_HEADERS
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["ANY766_PEER_PORT"]),
        access_log=False,
        log_level="warning",
    )
