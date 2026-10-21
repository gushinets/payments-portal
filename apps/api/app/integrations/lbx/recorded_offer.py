"""Explicit development-only selected GET recording; never opens a network socket."""

from __future__ import annotations

from pathlib import Path

import httpx

from app.integrations.lbx.client import API_PATH
from app.integrations.lbx.errors import LbxResponseInvalid
from app.integrations.lbx.offer_inputs import SelectedOfferRequest


def recorded_offer_transport(directory: Path, selection: SelectedOfferRequest) -> httpx.MockTransport:
    names = {
        "/auth": "auth",
        f"/tariffs/{selection.tariff_id}": "tariff",
        f"/tariffs/{selection.tariff_id}/periods": "periods",
        f"/tariffs/{selection.tariff_id}/services": "services",
        f"/tariffs/{selection.tariff_id}/services/{selection.tariff_service_id}/prices": "prices",
    }
    try:
        bodies = {}
        for suffix, name in names.items():
            with (directory / f"{name}.json").open("rb") as stream:
                body = stream.read(524289)
            if len(body) > 524288:
                raise LbxResponseInvalid()
            bodies[suffix] = body
    except OSError:
        raise LbxResponseInvalid() from None

    def respond(request: httpx.Request) -> httpx.Response:
        suffix = request.url.path.removeprefix(API_PATH)
        if request.method != "GET" or suffix not in bodies:
            raise LbxResponseInvalid()
        return httpx.Response(200, content=bodies[suffix], headers={"Content-Type": "application/json"})

    return httpx.MockTransport(respond)
