"""SIMULATED deterministic transport on the Step 2 selected-offer account.

No socket, Widget credential, payment or mutation of remote state is possible.
Receipts and GETs are recordings, not claims about current provider behavior.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.integrations.lbx.client import API_PATH
from app.integrations.lbx.errors import LbxResponseInvalid
from app.integrations.lbx.preparation_profile import PreparationProfile
from app.integrations.lbx.recorded_offer import recorded_offer_transport


class RecordedPreparationTransport(httpx.MockTransport):
    source_mode = "SIMULATED"

    def __init__(self, directory: Path, profile: PreparationProfile) -> None:
        selected = recorded_offer_transport(directory, profile.selection)
        names = {
            ("POST", "/users"): "created_user",
            ("POST", "/agreements"): "created_agreement",
            ("POST", "/subscriptions"): "created_subscription",
            ("GET", "/users/1501"): "user",
            ("GET", "/agreements/1601"): "agreement",
            ("GET", "/subscriptions/1701"): "subscription",
            ("GET", "/users"): "users",
            ("GET", "/agreements"): "agreements",
            ("GET", "/subscriptions"): "subscriptions",
        }
        bodies: dict[tuple[str, str], bytes] = {}
        try:
            for key, name in names.items():
                with (directory / f"{name}.json").open("rb") as stream:
                    body = stream.read(524289)
                if len(body) > 524288:
                    raise LbxResponseInvalid()
                bodies[key] = body
        except OSError:
            raise LbxResponseInvalid() from None

        async def respond(request: httpx.Request) -> httpx.Response:
            suffix = request.url.path.removeprefix(API_PATH)
            key = (request.method, suffix)
            body = bodies.get(key)
            if body is not None:
                status = 201 if request.method == "POST" else 200
                return httpx.Response(status, content=body, headers={"Content-Type": "application/json"})
            return await selected.handle_async_request(request)

        super().__init__(respond)
