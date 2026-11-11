"""Privileged direct link composition; all source I/O precedes DB resources."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import httpx

from app.composition.sources import source_resources
from app.core.settings import Settings
from app.domains.catalog.commercial_offer import CommercialScope, canonical_document, commercial_digest
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.admission import require_selected_capability
from app.domains.catalog.contracts import SourceProvenance
from app.domains.catalog.preview import require_enabled_product
from app.domains.catalog.product_link import (
    LINK_SCHEMA,
    OWNED_LINK_SCHEMA,
    CurrentOffer,
    ProductLinkDocument,
    ProductLinkRequest,
)
from app.domains.catalog.technical_offer import TechnicalOffer
from app.domains.catalog.technical_source import LEGACY_KERNEL_OWNERSHIP
from app.integrations.lbx.current_offer import read_current_offer


def resolve_operator_principal(*, resolve_uid: Callable[[], int] | None = None) -> str:
    resolver = resolve_uid if resolve_uid is not None else getattr(os, "geteuid", None)
    if resolver is None:
        raise MappingRefused("mapping_operator_identity_unavailable")
    try:
        uid = resolver()
    except OSError:
        raise MappingRefused("mapping_operator_identity_unavailable") from None
    if type(uid) is not int or uid < 0:
        raise MappingRefused("mapping_operator_identity_unavailable")
    return f"os-euid:{uid}"


def configured_mapping_scope(configuration: Settings) -> CommercialScope:
    if not configuration.lbx_external_billing_account_id:
        raise MappingRefused("mapping_account_not_configured")
    return CommercialScope(
        configuration.instance_tenant_id, configuration.instance_region, configuration.lbx_external_billing_account_id
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class FreshLinkEvaluation:
    document: ProductLinkDocument
    deadline: float
    offer: CurrentOffer


async def fresh_link_evaluation(
    configuration: Settings,
    *,
    selection: ProductLinkRequest,
    principal: str,
    technical_offer: TechnicalOffer | None = None,
    kernel_transport: httpx.AsyncBaseTransport | None = None,
    lbx_transport: httpx.AsyncBaseTransport | None = None,
) -> FreshLinkEvaluation:
    if configuration.lbx_configuration_error is not None:
        raise MappingRefused(configuration.lbx_configuration_error)
    scope = configured_mapping_scope(configuration)
    async with source_resources(
        configuration, kernel_transport=kernel_transport, lbx_transport=lbx_transport
    ) as sources:
        async with sources.preflight.operation() as budget:
            source = sources.technical_source(selection.product_id)
            manifest = await source.client.fetch_manifest(budget=budget)
            require_enabled_product(manifest, selection.product_id)
            if technical_offer is not None:
                if technical_offer.product_id != selection.product_id:
                    raise MappingRefused("mapping_technical_product_mismatch")
                if manifest.provenance != SourceProvenance.CONFIGURED_SOURCE:
                    raise MappingRefused("mapping_live_kernel_required")
                require_selected_capability(
                    manifest,
                    product_id=selection.product_id,
                    metric_units={technical_offer.metric_key: technical_offer.unit},
                )
            elif source.ownership != LEGACY_KERNEL_OWNERSHIP:
                raise MappingRefused("mapping_technical_offer_required")
            offer = await read_current_offer(
                sources.require_lbx(), selection=selection, configuration=configuration, budget=budget
            )
            now = utc_now()
            schema = OWNED_LINK_SCHEMA if technical_offer is not None else LINK_SCHEMA
            provenance = (
                {
                    "technical_source_id": source.ownership.technical_source_id,
                    "backend_consumer_id": source.ownership.backend_consumer_id,
                    "manifest_provenance": manifest.provenance,
                }
                if technical_offer is not None
                else {"kernel_provenance": manifest.provenance}
            )
            identity = canonical_document(
                {
                    "schema": schema,
                    "scope": asdict(scope),
                    "selection": selection.model_dump(mode="json"),
                    **provenance,
                    "lbx_evidence_mode": offer.evidence_mode,
                    **({"technical_offer": technical_offer.model_dump(mode="json")} if technical_offer else {}),
                }
            )
            document = ProductLinkDocument(
                schema_version=schema,
                scope=scope,
                selection=selection,
                technical_offer=technical_offer,
                **provenance,
                lbx_evidence_mode=offer.evidence_mode,
                manifest_version=manifest.manifest_version,
                manifest_generated_at=manifest.generated_at,
                evaluated_at=now,
                published_at=now,
                publisher_principal=principal,
                reason="Operator product link",
                identity_digest=commercial_digest(identity),
            )
            budget.check()
            return FreshLinkEvaluation(document, budget.work_deadline, offer)
