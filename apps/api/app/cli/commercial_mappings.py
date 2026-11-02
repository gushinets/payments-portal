"""Privileged direct product linking; no proposal, approval or source-policy files."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.composition.mapping_operator import configured_mapping_scope, fresh_link_evaluation, resolve_operator_principal
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.catalog.commercial_offer import CommercialScope, canonical_document
from app.domains.catalog.link_publication import (
    StoredProductLink,
    publish_product_link,
    query_link_history,
    query_product_link,
)
from app.domains.catalog.product_link import ProductLinkRequest
from app.domains.catalog.publication import StoredMapping
from app.infrastructure.operator_preflight import operator_preflight_lock


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Link a Kernel product to a current LBX offer")
    actions = command.add_subparsers(dest="command", required=True)
    query = actions.add_parser("query", help="Read the current product link or immutable offer history")
    identity = query.add_mutually_exclusive_group(required=True)
    identity.add_argument("--product-id")
    identity.add_argument("--offer-id")
    query.add_argument("--revision", type=int, help="Offer history sequence; requires --offer-id")
    for action in ("dry-run", "publish"):
        source = actions.add_parser(action, help="Validate live sources for one product association")
        source.add_argument("--product-id", required=True)
        source.add_argument("--tariff-id", type=int, required=True)
        source.add_argument("--tariff-service-id", type=int, required=True)
        source.add_argument("--period-id", type=int, required=True)
        source.add_argument("--quantity", type=int, default=1, help="Commercial service quantity; not a quota")
        if action == "publish":
            source.add_argument(
                "--expected-previous-revision",
                type=int,
                required=True,
                help="Current PRODUCT revision; 0 for no current link",
            )
    return command


def present_stored(stored: StoredProductLink | StoredMapping) -> dict[str, object]:
    offer_id = (
        stored.document.selection.billing_offer_id
        if isinstance(stored, StoredProductLink)
        else stored.document.material.billing_offer_id
    )
    result: dict[str, object] = {
        "mapping_revision_id": str(stored.mapping_revision_id),
        "billing_offer_id": offer_id,
        "revision_number": stored.revision_number,
        "document": stored.document.model_dump(mode="json"),
    }
    if isinstance(stored, StoredProductLink):
        result["offer_revision_number"] = stored.offer_revision_number
    return result


def execute(arguments: argparse.Namespace, configuration: Settings) -> str:
    principal = resolve_operator_principal()
    audit = {
        "command": arguments.command,
        "execution_principal": principal,
        "started_at": datetime.now(UTC).isoformat(),
    }
    if arguments.command == "query":
        from app.core.database import SessionLocal

        if arguments.product_id:
            if arguments.revision is not None:
                raise AppError("mapping_query_invalid")
            scope = configured_mapping_scope(configuration)
            stored = query_product_link(
                SessionLocal,
                scope=scope,
                product_id=arguments.product_id,
                provider_origin=configuration.lbx_provider_origin,
                legacy_account_id=configuration.lbx_legacy_credential_scope,
            )
            if stored is None:
                return json.dumps(
                    {
                        "operator_audit": audit,
                        "product_id": arguments.product_id,
                        "revision_number": 0,
                        "document": None,
                    }
                )
        else:
            scope = CommercialScope(
                configuration.instance_tenant_id,
                configuration.instance_region,
                configuration.lbx_external_billing_account_id,
            )
            stored = query_link_history(
                SessionLocal, scope=scope, offer_id=arguments.offer_id, revision=arguments.revision
            )
        return json.dumps({"operator_audit": audit, **present_stored(stored)})

    if arguments.command == "publish" and arguments.expected_previous_revision < 0:
        raise AppError("mapping_expected_revision_invalid")
    selection = ProductLinkRequest(
        product_id=arguments.product_id,
        tariff_id=arguments.tariff_id,
        tariff_service_id=arguments.tariff_service_id,
        period_id=arguments.period_id,
        quantity=arguments.quantity,
    )
    with operator_preflight_lock(configuration.mapping_operator_lock_file):
        with asyncio.Runner() as runner:
            evaluation = runner.run(fresh_link_evaluation(configuration, selection=selection, principal=principal))
        if arguments.command == "dry-run":
            return json.dumps(
                {
                    "operator_audit": audit,
                    "persisted": False,
                    "billing_offer_id": selection.billing_offer_id,
                    "evaluation": evaluation.document.model_dump(mode="json"),
                    "current_offer": json.loads(canonical_document(asdict(evaluation.offer))),
                }
            )
        from app.core.database import SessionLocal

        result = publish_product_link(
            SessionLocal,
            evaluation=evaluation.document,
            expected_previous_revision=arguments.expected_previous_revision,
            deadline=evaluation.deadline,
            lock_timeout_seconds=configuration.mapping_lock_timeout_seconds,
            provider_origin=configuration.lbx_provider_origin,
            legacy_account_id=configuration.lbx_legacy_credential_scope,
        )
        return json.dumps(
            {
                "operator_audit": audit,
                **present_stored(result.stored),
                "current_offer": json.loads(canonical_document(asdict(evaluation.offer))),
                "inserted": result.inserted,
                "recovered_commit": result.recovered_commit,
            }
        )


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        output = execute(arguments, Settings())
    except AppError as error:
        print(json.dumps({"detail": {"code": error.code}}), file=sys.stderr)
        return 1
    except ValidationError:
        print('{"detail":{"code":"mapping_configuration_invalid"}}', file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print('{"detail":{"code":"mapping_database_error"}}', file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
