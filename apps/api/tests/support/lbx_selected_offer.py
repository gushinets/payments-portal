"""Reusable isolated SIMULATED HTTP recording for Steps 4/5/7.

Only the transport is replaced. Auth, exact decoding, selected reads and the
normalization algorithm are the real implementations. Never import in runtime.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.integrations.lbx.client import API_PATH
from app.integrations.lbx.offer_inputs import SelectedOfferInputs, SelectedOfferRequest
from apps.api.tests.support.lbx import ACCOUNT, SERVICE, TARIFF, fixture_response


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/lbx/selected_offer"


def simulated_selection() -> SelectedOfferRequest:
    return SelectedOfferRequest.model_validate_json(
        (FIXTURES / "selection.json").read_text().replace("simulated-ru-lbx-account", ACCOUNT)
    )


def simulated_inputs() -> SelectedOfferInputs:
    return SelectedOfferInputs.model_validate_json(
        (FIXTURES / "inputs.json").read_text().replace("simulated-ru-lbx-account", ACCOUNT)
    )


class SelectedOfferRecording:
    def __init__(self) -> None:
        self.bodies = {
            name: (FIXTURES / f"{name}.json").read_bytes() for name in ("tariff", "periods", "services", "prices")
        }
        self.reread_bodies: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.counts: dict[str, int] = {}

    def replace(self, name: str, old: str, new: str, *, reread_only: bool = False) -> None:
        body = self.bodies[name]
        assert old.encode() in body
        target = self.reread_bodies if reread_only else self.bodies
        target[name] = body.replace(old.encode(), new.encode())

    def append_row(self, name: str, row: str, *, reread_only: bool = False) -> None:
        body = self.bodies[name].rstrip()
        assert body.endswith(b"]}")
        target = self.reread_bodies if reread_only else self.bodies
        target[name] = body[:-2] + b"," + row.encode() + b"]}"

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "GET"
        suffix = request.url.path.removeprefix(API_PATH)
        if suffix == "/auth":
            return fixture_response("auth")
        name = {
            f"/tariffs/{TARIFF}": "tariff",
            f"/tariffs/{TARIFF}/periods": "periods",
            f"/tariffs/{TARIFF}/services": "services",
            f"/tariffs/{TARIFF}/services/{SERVICE}/prices": "prices",
        }[suffix]
        self.counts[name] = self.counts.get(name, 0) + 1
        body = self.reread_bodies.get(name, self.bodies[name]) if self.counts[name] > 1 else self.bodies[name]
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})
