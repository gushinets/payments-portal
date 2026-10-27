"""SIMULATED purchase transport. No live URLs, credentials, payments or grants."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx

from apps.api.tests.support.any709_step1 import recording
from apps.api.tests.support.kernel import manifest_fixture


class PurchaseTransport:
    def __init__(self) -> None:
        self.offer = recording()
        for name in ("services", "prices"):
            self.offer.replace(name, "100.01", "100")
            self.offer.replace(name, "7.03", "0")
        self.customer: dict[str, Any] | None = None
        self.agreements: list[dict[str, Any]] = []
        self.subscriptions: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self.fail_create: str | None = None
        self.hide: set[str] = set()
        self.pool: Any = None
        self.before_offer: Any = None

    def kernel(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=manifest_fixture())

    def response(self, value: Any, *, status: int = 200) -> httpx.Response:
        return httpx.Response(status, json={"code": status, "response": value})

    def respond(self, request: httpx.Request) -> httpx.Response:
        if self.pool is not None:
            assert self.pool.checkedout() == 0, "provider HTTP held a DB transaction/resource"
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/rest/v1")
        body = json.loads(request.content) if request.content else {}
        if path.startswith("/tariffs") or path == "/auth":
            if self.before_offer and path.startswith("/tariffs"):
                callback, self.before_offer = self.before_offer, None
                callback()
            return self.offer.respond(request)
        if request.method == "POST":
            if path == "/users":
                self.customer = {"user_id": 345, "outer_id": body["outer_id"]}
                return self.response({"user_id": 345}, status=201)
            if path == "/agreements":
                self.agreements.append({**body, "agreement_id": 456, "agreement_link": ""})
                value = {"agreement_id": 456}
            elif path == "/subscriptions":
                assert body["period_id"] == 901 and "subscription_start_date" not in body
                assert body["activate_by_balance"] is True and body["demo_period_length"] == 0
                assert body["activate_manually"] is False
                assert body["services"] == [{"tariff_service_id": 1001, "multiplicator": 1}]
                self.subscriptions.append(
                    {
                        "subscription_id": 567,
                        "agreement_id": body["agreement_id"],
                        "tariff_id": body["tariff_id"],
                        "period_id": body["period_id"],
                        "period_type": 3,
                        "period_length": 1,
                        "state": -2,
                        "current_blocking": 0,
                        "is_demo": False,
                        "is_offer_agrm": False,
                        "total_price": 100,
                        "currency_symbol": "руб",
                        "outer_id": body["outer_id"],
                        "subscription_start_date": None,
                        "last_tariffication_period_start": "1970-01-01 00:00:00",
                        "services": [
                            {
                                "tariff_service_id": 1001,
                                "multiplicator": 1,
                                "price": 100,
                                "bulk_price": None,
                                "bulk_include_amount": None,
                                "periodic_service": 1,
                                "bulk_service": False,
                            }
                        ],
                    }
                )
                value = {"subscription_id": 567}
            else:
                raise AssertionError(path)
            if self.fail_create == path:
                return httpx.Response(500, json={"code": 500, "response": {"error": "PRIVATE canary unknown refusal"}})
            return self.response(value, status=201)
        if path == "/users":
            return self.response([self.customer] if self.customer else [])
        if path in {"/users/345", "/client/user"}:
            return self.response(self.customer)
        if path == "/agreements":
            assert body["user_id"] == 345 and "agreement_number" in body
            return self.response(
                []
                if path in self.hide
                else [row for row in self.agreements if row["agreement_number"] == body["agreement_number"]]
            )
        if path.startswith("/agreements/"):
            return self.response(
                next(row for row in self.agreements if row["agreement_id"] == int(path.split("/")[-1]))
            )
        if path == "/subscriptions":
            assert body["user_id"] == 345
            return self.response(
                []
                if path in self.hide
                else [
                    row
                    for row in self.subscriptions
                    if "agreement_id" not in body or row["agreement_id"] == body["agreement_id"]
                ]
            )
        if path.startswith("/subscriptions/"):
            return self.response(
                next(row for row in self.subscriptions if row["subscription_id"] == int(path.split("/")[-1]))
            )
        raise AssertionError(path)

    def creates(self, path: str) -> int:
        return sum(request.method == "POST" and request.url.path.endswith(path) for request in self.requests)

    def change_price(self) -> None:
        for name in ("services", "prices"):
            self.offer.replace(name, '"price":100', '"price":110')

    def effective_subscription(self) -> dict[str, Any]:
        # Build through the actual transport before using this helper.
        return json.loads(json.dumps(self.subscriptions[0]), parse_float=Decimal)
