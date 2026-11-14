"""Explicit synthetic second backend; demonstrates Portal routing, never team adoption."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import Response

from apps.api.tests.support.kernel import manifest_fixture, resign

RUN = Path(os.environ["ANY766_RUN_DIR"])
CONSUMER = json.loads(os.environ["BACKEND_CONSUMERS"])[1]
app = FastAPI()


def authenticate(request: Request) -> None:
    if (
        request.headers.get("authorization")
        != "Bearer " + CONSUMER["portal_to_backend_current_secret"]
    ):
        raise HTTPException(401)
    with (RUN / "summary-requests.jsonl").open("a") as output:
        output.write(
            json.dumps({"method": request.method, "path": request.url.path}) + "\n"
        )


@app.get("/internal/v1/capability-manifest")
def manifest(request: Request) -> dict:
    authenticate(request)
    value = manifest_fixture()
    value["products"] = [{"product_id": "synthetic_summary", "enabled": True}]
    value["usage_metrics"] = [
        {
            "product_id": "synthetic_summary",
            "metric_key": "synthetic_summary.documents",
            "unit": "document",
            "enabled": True,
        }
    ]
    return resign(value)


@app.post("/internal/v1/access-invalidations")
async def invalidate(request: Request) -> Response:
    authenticate(request)
    if (RUN / "summary-outage").exists():
        raise HTTPException(503)
    payload = await request.json()
    with (RUN / "summary-acks.jsonl").open("a") as output:
        output.write(json.dumps(payload) + "\n")
    return Response(status_code=204)


@app.get("/internal/v1/usage/{user_id}")
async def usage(user_id: UUID, request: Request) -> dict:
    authenticate(request)
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.get(
            os.environ["ANY766_PORTAL_ORIGIN"]
            + f"/internal/v1/access-snapshots/{user_id}",
            params={"tenant_id": "anytoolai", "region": "ru"},
            headers={
                "Authorization": "Bearer "
                + CONSUMER["backend_to_portal_current_secret"]
            },
        )
        response.raise_for_status()
    allowances = {item["allowance_id"]: item for item in response.json()["allowances"]}
    items = []
    for identity in request.query_params.getlist("allowance_id"):
        item = allowances.get(identity)
        items.append(
            {
                **item,
                "status": "observed",
                "successful_used": 0,
                "reserved": 0,
                "remaining": item["quantity"],
                "available": item["quantity"],
                "read_at": datetime.now(UTC).isoformat(),
            }
            if item
            else {"allowance_id": identity, "status": "unobserved"}
        )
    return {
        "schema_version": 1,
        "tenant_id": "anytoolai",
        "region": "ru",
        "user_id": str(user_id),
        "items": items,
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["ANY766_SUMMARY_PORT"]),
        access_log=False,
        log_level="warning",
    )
