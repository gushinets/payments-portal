"""Run with PYTHONPATH=apps/api .venv/bin/python -m app.cli.commercial_mappings."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.composition.mapping_operator import authorize_operator, configured_mapping_scope
from app.core.errors import AppError
from app.core.settings import AppEnv, Settings
from app.domains.catalog.publication import publish_mapping, query_mapping


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Restricted immutable offer evidence operator")
    actions = command.add_subparsers(dest="command", required=True)
    query = actions.add_parser("query", help="Read scoped stored evidence without source configuration")
    query.add_argument("--offer-id", required=True, help="Complete selected-offer ID returned by dry-run/publish")
    query.add_argument("--revision", type=int)
    for action in ("dry-run", "publish"):
        source = actions.add_parser(action, help="Evaluate fresh configured sources and independent approval")
        source.add_argument("--proposal", type=Path, required=True)
        if action == "publish":
            source.add_argument("--expected-previous-revision", type=int, required=True)
    return command


def execute(arguments: argparse.Namespace, configuration: Settings) -> str:
    principal = authorize_operator(configuration)
    scope = configured_mapping_scope(configuration)
    allow_simulated = configuration.app_env in {AppEnv.DEVELOPMENT, AppEnv.TEST}
    audit = {
        "command": arguments.command,
        "execution_principal": principal,
        "started_at": datetime.now(UTC).isoformat(),
    }
    # Dispatch BEFORE creating source clients, an admission owner or an event loop.
    if arguments.command == "query":
        from app.core.database import SessionLocal

        stored = query_mapping(
            SessionLocal,
            scope=scope,
            offer_id=arguments.offer_id,
            revision=arguments.revision,
            allow_simulated=allow_simulated,
        )
        return json.dumps(
            {
                "operator_audit": audit,
                "mapping_revision_id": str(stored.mapping_revision_id),
                "billing_offer_id": stored.document.material.billing_offer_id,
                "revision_number": stored.revision_number,
                "document": stored.document.model_dump(mode="json"),
            }
        )

    from app.composition.mapping_operator import MappingProposal, fresh_mapping_evaluation, load_operator_input
    from app.domains.catalog.mapping_evidence import ApprovedMapping
    from app.integrations.lbx.offer_inputs import SelectedOfferInputs

    if arguments.command == "publish" and arguments.expected_previous_revision < 0:
        raise AppError("mapping_expected_revision_invalid")
    proposal = load_operator_input(arguments.proposal, MappingProposal)
    approval = load_operator_input(configuration.mapping_approval_file, ApprovedMapping)
    inputs = load_operator_input(configuration.mapping_source_inputs_file, SelectedOfferInputs)
    # Top-level process event-loop owner for genuine async source I/O only.
    # No Application/Domain/Persistence layer starts or bridges an event loop.
    with asyncio.Runner() as runner:
        evaluation = runner.run(
            fresh_mapping_evaluation(
                configuration, proposal=proposal, approval=approval, source_inputs=inputs, principal=principal
            )
        )
    if arguments.command == "dry-run":
        return json.dumps(
            {
                "operator_audit": audit,
                "persisted": False,
                "billing_offer_id": evaluation.document.material.billing_offer_id,
                "evaluation": evaluation.document.model_dump(mode="json"),
            }
        )
    if arguments.command != "publish":
        raise AppError("mapping_command_invalid")
    # Construct the DB capability only after all HTTP and source cleanup finished.
    from app.core.database import SessionLocal

    result = publish_mapping(
        SessionLocal,
        evaluation=evaluation.document,
        expected_previous_revision=arguments.expected_previous_revision,
        deadline=evaluation.deadline,
        lock_timeout_seconds=configuration.mapping_lock_timeout_seconds,
        allow_simulated=allow_simulated,
    )
    return json.dumps(
        {
            "operator_audit": audit,
            "mapping_revision_id": str(result.stored.mapping_revision_id),
            "billing_offer_id": result.stored.document.material.billing_offer_id,
            "revision_number": result.stored.revision_number,
            "inserted": result.inserted,
            "recovered_commit": result.recovered_commit,
            "stored_document": result.stored.document.model_dump(mode="json"),
            "current_evaluation": result.evaluation.model_dump(mode="json"),
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
        # A database failure remains a database failure, never a provider status.
        print('{"detail":{"code":"mapping_database_error"}}', file=sys.stderr)
        return 1
    # Restricted operator audit JSON: billing_offer_id is a tariff/component/
    # period key, not a credential. Protect stdout; audit text is preserved
    # verbatim. Settings and HTTP credentials are not part of MappingDocument.
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
