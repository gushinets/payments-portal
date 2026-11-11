"""Local-only LBX fixture and persisted purchase preparation for joint acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from copy import deepcopy
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import Response
from sqlalchemy import select

from apps.api.tests.support.any709_step3 import PurchaseTransport

RUN = Path(os.environ["ANY766_RUN_DIR"])


def lbx() -> None:
    """Explicit deterministic external substitute; never a Portal/Kernel proxy."""
    transport = PurchaseTransport()
    offers = {}
    for tariff in range(701, 706):
        offer = deepcopy(transport.offer)
        offer.tariff_id = tariff
        offer.bodies = {
            name: body.replace(b'"tariff_id":701', f'"tariff_id":{tariff}'.encode())
            for name, body in offer.bodies.items()
        }
        # One timeless synthetic offer; real price-change behavior has its own tests.
        prices = json.loads(offer.bodies["prices"])
        price = prices["response"][1]
        price["start_date"] = "2000-01-01"
        price.pop("next_change_date", None)
        prices["response"] = [price]
        offer.bodies["prices"] = json.dumps(prices).encode()
        services = json.loads(offer.bodies["services"])
        services["response"][0]["prices"][0]["price_start_date"] = "2000-01-01"
        offer.bodies["services"] = json.dumps(services).encode()
        offers[tariff] = offer
    app = FastAPI()

    @app.post("/__test__/subscriptions/{identity}")
    async def change(identity: int, request: Request) -> dict[str, bool]:
        patch = await request.json()
        row = next(
            row for row in transport.subscriptions if row["subscription_id"] == identity
        )
        row.update(patch)
        return {"updated": True}

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def respond(request: Request) -> Response:
        wire = httpx.Request(
            request.method, str(request.url), content=await request.body()
        )
        path = request.url.path.removeprefix("/api/rest/v1")
        reply = (
            offers[int(path.split("/")[2])].respond(wire)
            if path.startswith("/tariffs/")
            else transport.respond(wire)
        )
        return Response(
            reply.content, status_code=reply.status_code, media_type="application/json"
        )

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["ANY766_LBX_PORT"]),
        access_log=False,
        log_level="warning",
    )


async def seed() -> None:
    from app.composition import purchases
    from app.composition.backend_consumers import initialize_backend_consumers
    from app.composition.mapping_operator import fresh_link_evaluation
    from app.composition.reconciliation import reconcile_subscription
    from app.composition.sources import source_resources
    from app.core.database import SessionLocal
    from app.core.settings import settings
    from app.domains.catalog.link_publication import publish_product_link
    from app.domains.catalog.product_link import ProductLinkRequest
    from app.domains.catalog.technical_offer import TechnicalOffer
    from app.legal_seed import seed_legal_documents
    from app.models import BillingProductAccessScope, ExternalSubscription, User
    from apps.api.tests.factories.purchase_terms import reviewed_meaning
    from apps.api.tests.factories.paid_access import reader_identity
    from apps.api.tests.test_any709_step2_postgres import TOKEN, seed as seed_identity

    seed_identity(SessionLocal)
    with SessionLocal() as db:
        seed_legal_documents(db, tenant_id="anytoolai", region="ru")
        user_id = str(db.scalars(select(User)).one().id)
        foreign, foreign_session = reader_identity("joint-second-owner-token")
        db.add(foreign)
        db.flush()
        db.add(foreign_session)
        db.commit()
    initialize_backend_consumers(settings, SessionLocal)
    products = (
        ("proposal_ai", "proposal_ai.generations", "generation"),
        ("client_update_writer", "client_update_writer.messages", "message"),
        ("brief_decoder", "brief_decoder.analyses", "analysis"),
        ("acceptance_builder", "acceptance_builder.results", "result"),
        ("synthetic_summary", "synthetic_summary.documents", "document"),
    )
    subscriptions: dict[str, dict[str, str | int]] = {}
    if os.environ.get("ANY766_BROWSER") == "true":
        products = tuple(
            item
            for item in products
            if item[0] in {"brief_decoder", "synthetic_summary"}
        )
    async with (
        source_resources(settings) as sources,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        for index, (product, metric, unit) in enumerate(products):
            fresh = await fresh_link_evaluation(
                settings,
                selection=ProductLinkRequest(
                    product_id=product,
                    tariff_id=701 + index,
                    tariff_service_id=1001,
                    period_id=901,
                ),
                principal=f"os-euid:{os.geteuid()}",
                technical_offer=TechnicalOffer(
                    product_id=product,
                    metric_key=metric,
                    unit=unit,
                    quantity=8,
                    quantity_mode="fixed_per_cycle",
                ),
            )
            publish_product_link(
                SessionLocal,
                evaluation=fresh.document,
                expected_previous_revision=0,
                deadline=fresh.deadline,
                lock_timeout_seconds=1,
                provider_origin=settings.lbx_provider_origin,
            )
            link, offer, documents, terms = await purchases.review_purchase(
                sources, settings, factory=SessionLocal, token=TOKEN, product_id=product
            )
            purchase = await purchases.confirm_purchase(
                sources,
                settings,
                factory=SessionLocal,
                token=TOKEN,
                key=f"joint-{product}",
                meaning=reviewed_meaning(
                    product,
                    link.mapping_revision_id,
                    offer.fingerprint,
                    documents,
                    terms,
                ),
            )
            await purchases.advance_purchase(
                sources,
                settings,
                factory=SessionLocal,
                token=TOKEN,
                purchase_id=purchase.id,
            )
            with SessionLocal() as db:
                sub = db.scalars(
                    select(ExternalSubscription).where(
                        ExternalSubscription.product_id == product
                    )
                ).one()
                db.add(
                    BillingProductAccessScope(
                        user_id=sub.user_id,
                        product_id=product,
                        primary_subscription_id=sub.subscription_id,
                    )
                )
                subscriptions[product] = {
                    "id": str(sub.subscription_id),
                    "provider_id": int(sub.external_subscription_id),
                }
                db.commit()
            # Authoritative fixture dates surround this run; no wall-clock advance grants access.
            now = datetime.now(UTC)
            cycle = now.replace(day=1) - timedelta(days=1)
            reply = await client.post(
                f"http://127.0.0.1:{os.environ['ANY766_LBX_PORT']}/__test__/subscriptions/"
                f"{subscriptions[product]['provider_id']}",
                json={
                    "state": 2,
                    "subscription_start_date": f"{now.year}-01-01",
                    "subscription_instance_start_date": f"{now.year}-01-01",
                    "last_tariffication_period_start": f"{cycle.year}-{cycle.month:02}-01",
                    "last_tariffication_period_end": f"{cycle.year}-{cycle.month:02}-{monthrange(cycle.year, cycle.month)[1]}",
                },
            )
            reply.raise_for_status()
            await reconcile_subscription(
                sources.require_lbx(),
                sources.billing,
                settings,
                factory=SessionLocal,
                subscription_id=UUID(str(subscriptions[product]["id"])),
            )
    path = RUN / "identity.json"
    path.write_text(
        json.dumps(
            {
                "user_id": user_id,
                "token": TOKEN,
                "foreign_token": "joint-second-owner-token",
                "subscriptions": subscriptions,
            }
        )
    )
    path.chmod(0o600)


def main() -> None:
    if sys.argv[1] == "lbx":
        lbx()
    elif sys.argv[1] == "seed":
        asyncio.run(seed())
    elif sys.argv[1] == "reconcile":
        from app.composition.reconciliation import reconcile_subscription
        from app.composition.sources import source_resources
        from app.core.database import SessionLocal
        from app.core.settings import settings

        async def reconcile() -> None:
            async with source_resources(settings) as sources:
                await reconcile_subscription(
                    sources.require_lbx(),
                    sources.billing,
                    settings,
                    factory=SessionLocal,
                    subscription_id=UUID(sys.argv[2]),
                )

        asyncio.run(reconcile())
    else:
        raise ValueError("Unknown joint acceptance role")


if __name__ == "__main__":
    main()
